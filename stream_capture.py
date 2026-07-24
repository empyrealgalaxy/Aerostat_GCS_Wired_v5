"""
Stream capture and people detection for AeroStream (YouTube and direct URLs).

ROOT CAUSE FIX: yt-dlp was failing silently to resolve YouTube URLs,
so the raw watch-page URL was passed to ffmpeg which cannot open HTML.

NEW APPROACH for YouTube:
  - yt-dlp (Python module via subprocess) pipes the video to stdout
  - ffmpeg (bundled in imageio-ffmpeg) reads from that pipe and decodes frames
  - This bypasses all URL-resolution issues: yt-dlp handles auth/DASH/cookies internally.

For direct URLs (RTSP / HTTP / MP4):
  - OpenCV VideoCapture (fastest)
  - imageio-ffmpeg fallback
"""
import base64
import cv2
import numpy as np
import os
import sys
import threading
import logging
import time
import subprocess
import queue
from typing import Optional

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
_stream_url        = None
_stream_stop       = threading.Event()
_stream_thread     = None
_stream_last_detection  = {}
_stream_last_frame_b64  = None
_stream_lock       = threading.Lock()
_stream_capture_error   = None
_stream_last_publish_at = 0.0
_stream_preview_seq     = 0  # incremented on each new preview JPEG (MJPEG edge-trigger)
_stream_detection_enabled = True  # when False, capture/MJPEG only — no YOLO load or inference

# Phase 3: always live (VLC-like). No YouTube-style sleep-per-frame pacing.
_STREAM_PREVIEW_INTERVAL = 1.0 / 30.0
_STREAM_LIVE_PREVIEW_INTERVAL = 1.0 / 30.0
# Keep full HD so RTSP preview matches VLC resolution (camera is 1920x1080)
_STREAM_LIVE_MAX_WIDTH = 1920
_STREAM_LIVE_JPEG_QUALITY = 70

# Kept for any leftover callers; unused in Phase 3 live path
_PLAYBACK_FPS_DEFAULT = 25.0
_STREAM_YOUTUBE_TARGET_FPS = 25.0

# Current stream mode — Phase 3 always True (no playback throttling)
_stream_is_live = True

# Raw JPEG for MJPEG (avoids base64 round-trip on the hot path)
_stream_last_jpeg = None


def _pace_wall_clock(target_interval: float, loop_start: float) -> None:
    """Phase 3: disabled. Sleep-per-frame caused multi-second lag vs VLC."""
    return


def _opencv_frame_interval(cap) -> float:
    """Unused in Phase 3 live path (no wall-clock pacing)."""
    return 0.0


def _meta_frame_interval(meta: dict) -> float:
    """Unused in Phase 3 live path (no wall-clock pacing)."""
    return 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_ffmpeg_exe() -> str:
    """Return path to ffmpeg: bundled (imageio-ffmpeg) or system."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def _is_live_rtsp(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("rtsp://") or u.startswith("rtsps://")


def _resize_for_live_preview(frame: np.ndarray) -> np.ndarray:
    """Downscale live camera frames so JPEG encode stays cheap (lower glass-to-glass delay)."""
    try:
        h, w = frame.shape[:2]
        max_w = _STREAM_LIVE_MAX_WIDTH
        if w <= max_w:
            return frame
        new_w = max_w
        new_h = max(2, int(round(h * (new_w / float(w)))))
        if new_h % 2:
            new_h += 1
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    except Exception:
        return frame


def _encode_frame_jpeg(frame: np.ndarray, quality: int = 75):
    """Encode a frame as JPEG bytes."""
    try:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        if not ok:
            return None
        return buf.tobytes()
    except Exception:
        return None


def _encode_frame_b64(frame: np.ndarray, quality: int = 75):
    """Encode a frame as JPEG base64 for the MJPEG preview / API."""
    raw = _encode_frame_jpeg(frame, quality=quality)
    if raw is None:
        return None
    try:
        return base64.b64encode(raw).decode("utf-8")
    except Exception:
        return None


class _LatestFrameGrabber:
    """
    Background reader that always keeps only the newest camera frame.
    Prevents OpenCV/FFmpeg backlog from turning into multi-second display lag.
    """

    def __init__(self, cap):
        self._cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._ok = True
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="rtsp-latest-frame"
        )
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                ret, frame = self._cap.read()
            except Exception:
                self._ok = False
                break
            if not ret or frame is None:
                self._ok = False
                break
            with self._lock:
                self._frame = frame

    def get(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._frame

    def alive(self) -> bool:
        return self._ok and not self._stop.is_set() and self._thread.is_alive()

    def stop(self):
        self._stop.set()
        try:
            self._thread.join(timeout=2.0)
        except Exception:
            pass


def _draw_people_overlays(frame: np.ndarray, people: list) -> np.ndarray:
    """
    Draw the latest known detections on the freshest captured frame.

    This keeps the visible MJPEG feed responsive even when YOLO inference is slower
    than the input stream.
    """
    annotated = frame.copy()
    for person in people or []:
        try:
            bbox = person.get("bbox")
            if bbox is None:
                continue
            x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
            conf = float(person.get("confidence", 0))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{conf:.2f}"
            lx, ly = x1, max(y1 - 6, 14)
            cv2.putText(
                annotated, label, (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA,
            )
        except Exception:
            continue
    return annotated


def _publish_preview_frame(frame: np.ndarray, live: bool = False) -> None:
    """
    Publish a fresh preview frame for the browser without waiting for YOLO.

    The preview is throttled to avoid excessive JPEG work on high-FPS inputs.
    Live RTSP: downscale + faster cadence so the UI tracks the camera, not a backlog.
    """
    global _stream_last_frame_b64, _stream_last_jpeg, _stream_capture_error
    global _stream_last_publish_at, _stream_preview_seq

    now = time.time()
    interval = _STREAM_LIVE_PREVIEW_INTERVAL if live else _STREAM_PREVIEW_INTERVAL
    if now - _stream_last_publish_at < interval:
        return

    work = _resize_for_live_preview(frame) if live else frame

    if _stream_detection_enabled:
        with _stream_lock:
            people = list(_stream_last_detection.get("people", [])) if _stream_last_detection else []
        preview = _draw_people_overlays(work, people)
    else:
        preview = work

    quality = _STREAM_LIVE_JPEG_QUALITY if live else 75
    jpeg = _encode_frame_jpeg(preview, quality=quality)
    if jpeg is None:
        return
    try:
        frame_b64 = base64.b64encode(jpeg).decode("utf-8")
    except Exception:
        return

    with _stream_lock:
        _stream_last_jpeg = jpeg
        _stream_last_frame_b64 = frame_b64
        _stream_capture_error = None
        _stream_last_publish_at = now
        _stream_preview_seq += 1


def _ffmpeg_http_header_args(headers: dict) -> list:
    """Build ffmpeg -headers argv fragment from yt-dlp http_headers dict."""
    if not headers:
        return []
    lines = []
    for k, v in headers.items():
        if v is None:
            continue
        k_str, v_str = str(k), str(v).replace("\r", "").replace("\n", "")
        if not k_str.strip():
            continue
        lines.append(f"{k_str}: {v_str}")
    if not lines:
        return []
    blob = "\r\n".join(lines) + "\r\n"
    return ["-headers", blob]


def _resolve_youtube_direct_media_url(page_url: str) -> tuple:
    """
    Use yt-dlp in-process to get an HTTPS URL ffmpeg can read.
    Required for PyInstaller: ``sys.executable -m yt_dlp`` does not work when exe is not Python.
    """
    try:
        import yt_dlp
    except ImportError as e:
        logger.warning("yt_dlp import failed: %s", e)
        return None, {}
    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
        "format": "bestvideo[height<=480][vcodec!*=av01]/bestvideo[height<=480]/bestvideo/best",
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
    except Exception as e:
        logger.warning("yt-dlp extract_info failed: %s", e)
        return None, {}
    if not info:
        return None, {}
    base_headers = dict(info.get("http_headers") or {})

    url = info.get("url")
    if url:
        return url, base_headers

    best = None
    best_h = -1
    for f in info.get("formats") or []:
        if not f.get("url"):
            continue
        vcodec = (f.get("vcodec") or "none") or "none"
        if vcodec == "none":
            continue
        if (f.get("acodec") or "none") not in ("none", None):
            continue
        h = int(f.get("height") or 0)
        vc = str(f.get("vcodec", "")).lower()
        if "av01" in vc:
            continue
        if h > 480:
            continue
        if h >= best_h:
            best_h = h
            best = f
    if best:
        hdr = dict(base_headers)
        hdr.update(dict(best.get("http_headers") or {}))
        return best["url"], hdr

    return None, {}


def _ytdlp_subprocess_argv_prefix():
    """Argv prefix for yt-dlp subprocess; None if unavailable (e.g. frozen exe without yt-dlp on PATH)."""
    if getattr(sys, "frozen", False):
        import shutil
        for name in ("yt-dlp.exe", "yt-dlp", "yt_dlp.exe"):
            w = shutil.which(name)
            if w:
                return [w]
        return None
    return [sys.executable, "-m", "yt_dlp"]


# ── YouTube: yt-dlp pipe → ffmpeg pipe → BGR frames ─────────────────────────

class _YTDLPReader:
    """
    Reads BGR frames from YouTube by piping yt-dlp → ffmpeg.

    Key design decisions:
    - Uses `bestvideo` (no audio): avoids yt-dlp needing to mux audio+video,
      which simplifies the pipe and removes one failure mode.
    - Probes dimensions via yt-dlp API first so we know exact frame byte size.
    - Waits up to 60 s for the first frame (YouTube takes ~10 s to buffer).
    - Uses ffmpeg `-analyzeduration 60M` so ffmpeg also waits for data.
    """

    def __init__(self, url: str, width: int = 640):
        self.url         = url
        self.width       = width
        self.ytdlp_proc  = None
        self.ffmpeg_proc = None
        self.w           = width
        self.h           = width * 9 // 16   # fallback 16:9
        if self.h % 2:
            self.h += 1
        self._frame_size = self.w * self.h * 3
        self._first_frame = None

    def _probe_dimensions(self):
        """Use yt-dlp API to get the video's width/height before downloading."""
        try:
            import yt_dlp
            opts = {"quiet": True, "skip_download": True, "noplaylist": True,
                    "format": "bestvideo[height<=480][vcodec!*=av01]/bestvideo[height<=480]/bestvideo",
                    "nocheckcertificate": True,
                    "extractor_args": {"youtube": {"player_client": ["android"]}}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    return
                # Walk formats to find one with dimensions
                for f in [info] + list(reversed(info.get("formats") or [])):
                    fw, fh = f.get("width"), f.get("height")
                    if fw and fh:
                        self.w = min(self.width, fw)
                        self.h = int(fh * self.w / fw)
                        if self.h % 2:
                            self.h += 1
                        self._frame_size = self.w * self.h * 3
                        logger.info("Probed video dimensions: %dx%d → output %dx%d",
                                    fw, fh, self.w, self.h)
                        return
        except Exception as e:
            logger.warning("Dimension probe failed (will use 640×360): %s", e)

    def open(self) -> bool:
        import queue as _queue

        self._probe_dimensions()
        ffmpeg_exe = _get_ffmpeg_exe()

        def _start_ytdlp_pipe():
            """Disabled: subprocess pipe approach removed to avoid EDR false positives.
            Falls through to the in-process resolved-URL path below."""
            return False

        def _wait_first_frame():
            logger.info("Waiting for first frame from YouTube pipeline (up to 60 s)…")
            q = _queue.Queue(maxsize=1)

            def _bg_read():
                q.put(self._read_raw())

            threading.Thread(target=_bg_read, daemon=True).start()
            try:
                return q.get(timeout=60)
            except _queue.Empty:
                return None

        # 1) PyInstaller-friendly: resolved HTTPS URL → single ffmpeg (no yt-dlp subprocess)
        media_url, media_headers = _resolve_youtube_direct_media_url(self.url)
        if media_url:
            logger.info("YouTube: using resolved media URL with ffmpeg (bundled yt-dlp)")
            ffmpeg_cmd = [
                ffmpeg_exe, "-loglevel", "error",
                "-fflags", "+discardcorrupt",
                "-analyzeduration", "3000000",
                "-probesize", "10000000",
            ] + _ffmpeg_http_header_args(media_headers) + [
                "-i", media_url,
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-vf", f"scale={self.w}:{self.h}",
                # No -r / FPS throttle — pass frames through as they arrive (Phase 3)
                "pipe:1",
            ]
            try:
                self.ytdlp_proc = None
                self.ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                logger.error("Failed to start ffmpeg on resolved YouTube URL: %s", e)
                self.close()
                return False
            first = _wait_first_frame()
            if first is not None:
                self._first_frame = first
                logger.info("YTDLPReader ready (direct ffmpeg): %dx%d", self.w, self.h)
                return True
            try:
                err = self.ffmpeg_proc.stderr.read(1200).decode("utf-8", errors="replace").strip()
                if err:
                    logger.warning("ffmpeg stderr (direct URL): %s", err)
            except Exception:
                pass
            self.close()

        # 2) Classic pipe (development / yt-dlp on PATH)
        if not _start_ytdlp_pipe():
            return False
        first = _wait_first_frame()
        if first is None:
            for name, proc in (("yt-dlp", self.ytdlp_proc), ("ffmpeg", self.ffmpeg_proc)):
                if proc is None:
                    continue
                try:
                    err = proc.stderr.read(800).decode("utf-8", errors="replace").strip()
                    if err:
                        logger.warning("%s stderr: %s", name, err)
                except Exception:
                    pass
            self.close()
            return False

        self._first_frame = first
        logger.info("YTDLPReader ready: %dx%d", self.w, self.h)
        return True

    def _read_raw(self):
        """Read exactly one raw BGR frame from ffmpeg stdout. Returns ndarray or None."""
        needed = self._frame_size
        data = b""
        while len(data) < needed:
            try:
                chunk = self.ffmpeg_proc.stdout.read(needed - len(data))
            except Exception:
                return None
            if not chunk:
                return None
            data += chunk
        return np.frombuffer(data, dtype=np.uint8).reshape((self.h, self.w, 3))

    def read(self):
        """Return next BGR frame or None."""
        if self._first_frame is not None:
            f, self._first_frame = self._first_frame, None
            return f
        return self._read_raw()

    def close(self):
        for proc in (self.ffmpeg_proc, self.ytdlp_proc):
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.ffmpeg_proc = None
        self.ytdlp_proc  = None

    def is_alive(self) -> bool:
        return self.ffmpeg_proc is not None and self.ffmpeg_proc.poll() is None


# ── Direct URL readers (RTSP / HTTP / MP4) ───────────────────────────────────

def _try_opencv(url: str):
    """Try OpenCV VideoCapture. Returns cap or None."""
    try:
        live = _is_live_rtsp(url)
        # Prefer TCP + low-delay demux for RTSP IP cameras (VLC-like settings).
        if live:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|"
                "fflags;nobuffer+discardcorrupt|"
                "flags;low_delay|"
                "max_delay;0|"
                "analyzeduration;0|"
                "probesize;32"
            )
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap = cv2.VideoCapture(url)
        if cap.isOpened():
            try:
                # Keep OpenCV from buffering too many old frames.
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            # Drop stale buffered frames / wait for a decodable HEVC keyframe briefly.
            if live:
                for _ in range(45):
                    ok = cap.grab()
                    if not ok:
                        break
            ret, frame = cap.retrieve() if live else cap.read()
            if live and (not ret or frame is None):
                ret, frame = cap.read()
            if ret and frame is not None:
                logger.info("Stream opened via OpenCV: %dx%d%s",
                            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                            " (live/low-latency)" if live else "")
                return cap
            cap.release()
        return None
    except Exception:
        return None


def _imageio_input_params(url: str) -> list:
    """
    FFmpeg flags before -i for imageio-ffmpeg.
    Use -re for file / non-network URLs so decoding follows real-time (normal playback speed).
    """
    u = (url or "").strip().lower()
    if u.startswith(("rtsp://", "rtsps://")):
        return [
            "-rtsp_transport", "tcp",
            "-fflags", "nobuffer+discardcorrupt",
            "-flags", "low_delay",
            "-strict", "experimental",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-max_delay", "0",
            "-reconnect", "1",
        ]
    if u.startswith(("http://", "https://")):
        return ["-reconnect", "1"]
    return ["-re"]


def _try_imageio_ffmpeg(url: str):
    """Open with imageio-ffmpeg (bundled ffmpeg). Returns (gen, w, h, meta) or None."""
    try:
        import imageio_ffmpeg
        gen = imageio_ffmpeg.read_frames(
            url, bits_per_pixel=24,
            input_params=_imageio_input_params(url),
        )
        meta = next(gen)
        w, h = meta["size"]
        logger.info("Stream opened via imageio-ffmpeg: %dx%d", w, h)
        return gen, w, h, meta
    except Exception as e:
        logger.warning("imageio-ffmpeg failed: %s", e)
        return None


# ── Dual-model helpers ────────────────────────────────────────────────────────

def _iou(box1, box2) -> float:
    """Compute Intersection-over-Union between two (x1,y1,x2,y2) boxes."""
    try:
        ix1 = max(box1[0], box2[0]);  iy1 = max(box1[1], box2[1])
        ix2 = min(box1[2], box2[2]);  iy2 = min(box1[3], box2[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        a1 = max(0, box1[2]-box1[0]) * max(0, box1[3]-box1[1])
        a2 = max(0, box2[2]-box2[0]) * max(0, box2[3]-box2[1])
        union = a1 + a2 - inter
        return inter / union if union > 0 else 0.0
    except Exception:
        return 0.0


def _merge_detections(primary: list, motion: list, iou_thr: float = 0.40) -> list:
    """
    Merge two people-detection lists.
    Keep all primary detections. Add motion detections only if they do NOT
    overlap (IoU > iou_thr) with any already-kept detection.
    Where two boxes DO overlap, keep the one with higher confidence.
    """
    if not motion:
        return list(primary)
    if not primary:
        return list(motion)

    merged = list(primary)
    for md in motion:
        best_iou  = 0.0
        best_idx  = -1
        for i, pd in enumerate(merged):
            iou = _iou(md.get("bbox", (0,0,0,0)), pd.get("bbox", (0,0,0,0)))
            if iou > best_iou:
                best_iou = iou
                best_idx = i
        if best_iou > iou_thr:
            # Same person detected by both – keep higher-confidence box
            if md.get("confidence", 0) > merged[best_idx].get("confidence", 0):
                merged[best_idx] = md
        else:
            # Unique detection from motion model – add it
            merged.append(md)
    return merged


def _has_significant_motion(prev_gray: np.ndarray, curr_gray: np.ndarray,
                             min_frac: float = 0.005) -> bool:
    """Return True if more than min_frac of pixels changed significantly."""
    try:
        diff   = cv2.absdiff(prev_gray, curr_gray)
        _, thr = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
        ratio  = np.count_nonzero(thr) / thr.size
        return ratio >= min_frac
    except Exception:
        return True   # assume motion on error so we don't skip frames


# ── Detection helper ──────────────────────────────────────────────────────────

def _run_detection(frame: np.ndarray, detector,
                   motion_detector=None, prev_gray_ref: list = None) -> None:
    """
    Run dual-model detection on a single frame.

    detector        – primary model (yolov8l): detects ALL people
    motion_detector – secondary model (yolov8m): detects MOVING people only,
                      triggered by frame-differencing; None = disabled
    prev_gray_ref   – [gray_frame] single-element list used as a mutable ref
                      so the caller's previous-frame state is updated in-place
    """
    global _stream_last_detection, _stream_last_frame_b64, _stream_capture_error
    try:
        fh, fw = frame.shape[:2]

        # ── Primary: detect all people ────────────────────────────────────────
        primary_result = detector.detect(frame, track=True, classes=[0])
        primary_people = primary_result.get("humans", primary_result.get("people", []))

        # ── Motion gate + secondary model ─────────────────────────────────────
        motion_people = []
        if motion_detector is not None and prev_gray_ref is not None:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (15, 15), 0)
                prev_gray = prev_gray_ref[0]

                if prev_gray is not None and _has_significant_motion(prev_gray, gray):
                    motion_result  = motion_detector.detect(frame, track=False, classes=[0])
                    motion_people  = motion_result.get("humans",
                                                       motion_result.get("people", []))
                    if motion_people:
                        logger.debug("Motion model: %d extra people candidates", len(motion_people))

                prev_gray_ref[0] = gray   # update for next frame
            except Exception as me:
                logger.debug("Motion detection error (non-fatal): %s", me)

        # ── Merge ─────────────────────────────────────────────────────────────
        all_people = _merge_detections(primary_people, motion_people)
        count      = len(all_people)

        logger.info("Stream YOLO: %d people  (primary=%d motion=%d)  frame %dx%d",
                    count, len(primary_people), len(motion_people), fw, fh)

        with _stream_lock:
            _stream_last_detection = {
                "people":       all_people,
                "people_count": count,
                "human_count":  count,
                "frame_width":  fw,
                "frame_height": fh,
            }
            _stream_capture_error  = None
    except Exception as e:
        logger.error("Detection error: %s", e)


# ── Capture loop ──────────────────────────────────────────────────────────────

def _stream_capture_loop():
    global _stream_capture_error

    url = _stream_url
    if not url:
        return

    detection_on = _stream_detection_enabled
    consumer_thread = None
    frame_q: Optional[queue.Queue] = None

    if detection_on:
        # ── Load primary detector – detects ALL people ────────────────────────
        try:
            from yolo_detector import YOLODetector
            base = os.path.dirname(os.path.abspath(__file__))

            for _m in ("yolov8s.pt", "yolov10s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8n.pt"):
                _c = os.path.join(base, _m)
                if os.path.isfile(_c):
                    primary_model_path = _c
                    break
            else:
                primary_model_path = "yolov8s.pt"

            detector = YOLODetector(model_path=primary_model_path, confidence_threshold=0.10)
            logger.info("Primary detector loaded: %s  (conf>=0.10)", primary_model_path)
        except Exception as e:
            logger.error("Primary detector load failed: %s", e)
            with _stream_lock:
                _stream_capture_error = f"Detector load failed: {e}"
            return

        motion_detector = None
        try:
            from yolo_detector import YOLODetector as _YD
            for _m in ("yolov8n.pt", "yolov8s.pt", "yolov8m.pt"):
                _c = os.path.join(base, _m)
                if os.path.isfile(_c) and _c != primary_model_path:
                    motion_model_path = _c
                    break
            else:
                motion_model_path = None

            if motion_model_path:
                motion_detector = _YD(model_path=motion_model_path, confidence_threshold=0.08)
                logger.info("Motion detector loaded: %s  (conf>=0.08)", motion_model_path)
            else:
                logger.info("No separate motion model found; single-model mode")
        except Exception as e:
            logger.warning("Motion detector load failed (non-fatal): %s", e)

        frame_q = queue.Queue(maxsize=1)
        prev_gray_ref = [None]

        def _yolo_consumer():
            while not _stream_stop.is_set():
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    continue
                _run_detection(frame, detector, motion_detector, prev_gray_ref)
                frame_q.task_done()

        consumer_thread = threading.Thread(target=_yolo_consumer,
                                           daemon=True, name="yolo-consumer")
        consumer_thread.start()
        logger.info("Frame-by-frame YOLO consumer thread started")
    else:
        logger.info("Stream capture: video only (YOLO / people detection disabled)")

    def _enqueue(frame: np.ndarray):
        """Push frame; drop oldest if queue is full so we stay current."""
        if not detection_on or frame_q is None:
            return
        if frame_q.full():
            try:
                frame_q.get_nowait()
                frame_q.task_done()
            except queue.Empty:
                pass
        try:
            frame_q.put_nowait(frame)
        except queue.Full:
            pass

    while not _stream_stop.is_set():

        # ── YouTube: yt-dlp pipe ───────────────────────────────────────────
        if _is_youtube(url):
            logger.info("YouTube detected → using yt-dlp pipe approach")
            reader = _YTDLPReader(url, width=640)
            if reader.open():
                with _stream_lock:
                    _stream_capture_error = None
                while not _stream_stop.is_set() and reader.is_alive():
                    frame = reader.read()
                    if frame is None:
                        logger.warning("Stream (yt-dlp): no frame, reconnecting…")
                        break
                    # No sleep-per-frame: show frames as soon as they arrive
                    _publish_preview_frame(frame, live=True)
                    _enqueue(frame)
                reader.close()
                if _stream_stop.is_set():
                    break
                time.sleep(2)
                continue
            else:
                msg = ("yt-dlp pipe failed. Make sure yt-dlp is installed: "
                       "pip install yt-dlp")
                logger.error(msg)
                with _stream_lock:
                    _stream_capture_error = msg
                time.sleep(10)
                continue

        # ── Direct URL / RTSP: OpenCV latest-frame (VLC-like, no sleep pacing) ──
        cap = _try_opencv(url)
        if cap is not None:
            with _stream_lock:
                _stream_capture_error = None
            grabber = _LatestFrameGrabber(cap)
            logger.info("Low-latency mode: latest-frame grabber (no YouTube sleep-per-frame)")
            try:
                while not _stream_stop.is_set() and grabber.alive():
                    frame = grabber.get()
                    if frame is None:
                        time.sleep(0.005)
                        continue
                    _publish_preview_frame(frame, live=True)
                    # Copy before enqueue so YOLO never races the grabber overwrite
                    _enqueue(frame.copy() if detection_on else frame)
                    time.sleep(0.001)
            finally:
                grabber.stop()
                try:
                    cap.release()
                except Exception:
                    pass
            if _stream_stop.is_set():
                break
            time.sleep(2)
            continue

        # ── Direct URL: imageio-ffmpeg fallback (no sleep pacing) ───────────
        result = _try_imageio_ffmpeg(url)
        if result is not None:
            gen, w, h, meta = result
            with _stream_lock:
                _stream_capture_error = None
            logger.info("ffmpeg fallback (low-latency flags, no playback pacing)")
            while not _stream_stop.is_set():
                try:
                    frame_bytes = next(gen)
                    frame_bgr = cv2.cvtColor(
                        np.frombuffer(frame_bytes, dtype=np.uint8).reshape((h, w, 3)),
                        cv2.COLOR_RGB2BGR)
                    _publish_preview_frame(frame_bgr, live=True)
                    _enqueue(frame_bgr)
                except StopIteration:
                    break
                except Exception as e:
                    logger.error("imageio-ffmpeg read error: %s", e)
                    break
            if _stream_stop.is_set():
                break
            time.sleep(2)
            continue

        # ── All failed ─────────────────────────────────────────────────────
        msg = "Cannot open stream URL. Check the URL and installed packages."
        logger.error(msg)
        with _stream_lock:
            _stream_capture_error = msg
        time.sleep(10)

    if consumer_thread is not None:
        consumer_thread.join(timeout=5)


# ── Public API ────────────────────────────────────────────────────────────────

def start_stream_capture(stream_url: str, detection_enabled: bool = True) -> dict:
    global _stream_url, _stream_stop, _stream_thread
    global _stream_last_detection, _stream_last_frame_b64, _stream_last_jpeg, _stream_capture_error
    global _stream_last_publish_at, _stream_preview_seq, _stream_detection_enabled
    global _stream_is_live

    stop_stream_capture()
    _stream_stop.clear()

    _stream_url = (stream_url or "").strip()
    if not _stream_url:
        return {"ok": False, "error": "No stream URL"}

    _stream_detection_enabled = bool(detection_enabled)
    # Phase 3: always live/low-latency path (match VLC; no YouTube sleep pacing)
    _stream_is_live = True

    _stream_last_detection  = {}
    _stream_last_frame_b64  = None
    _stream_last_jpeg       = None
    _stream_capture_error   = None
    _stream_last_publish_at = 0.0
    _stream_preview_seq     = 0

    _stream_thread = threading.Thread(target=_stream_capture_loop,
                                      daemon=True, name="stream-capture")
    _stream_thread.start()
    logger.info("Stream capture started: %s  (detection=%s)", _stream_url[:80], _stream_detection_enabled)
    return {"ok": True, "url": _stream_url, "detection_enabled": _stream_detection_enabled}


def stop_stream_capture():
    global _stream_thread, _stream_stop
    _stream_stop.set()
    if _stream_thread is not None:
        _stream_thread.join(timeout=8)
        _stream_thread = None


def get_stream_detection() -> dict:
    with _stream_lock:
        err  = _stream_capture_error
        det  = dict(_stream_last_detection) if _stream_last_detection else {
            "people": [], "people_count": 0, "human_count": 0,
            "frame_width": 640, "frame_height": 360,
        }
        b64  = _stream_last_frame_b64
        det_on = _stream_detection_enabled

    people_list = []
    for p in det.get("people", []):
        bbox = p.get("bbox", (0, 0, 0, 0))
        if hasattr(bbox, "__iter__") and not isinstance(bbox, (str, bytes)):
            bbox = list(bbox)
        people_list.append({
            "bbox":       bbox,
            "confidence": p.get("confidence", 0),
            "track_id":   p.get("track_id"),
            "category":   p.get("category", "human"),
            "class":      p.get("class", "person"),
        })

    return {
        "people":          people_list,
        "people_count":    det.get("people_count", 0),
        "human_count":     det.get("human_count",  0),
        "frame_width":     det.get("frame_width",  640),
        "frame_height":    det.get("frame_height", 360),
        "frame_base64":    b64,    # annotated frame with green boxes drawn by backend
        "error":           err,
        "intrusions":      [],
        "intrusion_count": 0,
        "detection_enabled": det_on,
    }


def is_stream_capture_active() -> bool:
    return _stream_thread is not None and _stream_thread.is_alive()
