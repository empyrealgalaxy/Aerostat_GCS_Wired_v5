"""
Gimbal control per Full Interface Control Document (ICD) v1.0.

GCS exposes:
  GET  /api/v1/gimbal/status
  POST /api/v1/gimbal/move
  POST /api/v1/gimbal/move/relative
  POST /api/v1/gimbal/jog
  POST /api/v1/gimbal/stop
  POST /api/v1/gimbal/home

If gimbal_host is configured, commands are forwarded to that host's same API paths
(Bearer token optional). Otherwise GCS keeps local pan/tilt state (software-only).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {
    "pan": 0.0,
    "tilt": 0.0,
    "moving": False,
    "stabilization": True,
}

# Soft angle limits (ICD ANGLE_LIMIT)
_PAN_MIN, _PAN_MAX = -180.0, 180.0
_TILT_MIN, _TILT_MAX = -90.0, 90.0

_DEFAULT_CONFIG = {
    "gimbal_host": "",          # e.g. http://192.168.144.25  (empty = local-only)
    "bearer_token": "",         # Sent to remote host as Authorization: Bearer …
    "require_auth": False,      # If True, inbound GCS calls must include same Bearer token
    "jog_speed": 12.0,
    "nudge_degrees": 3.0,
    "timeout_sec": 3.0,
    "use_https": False,
}


def _config_path() -> str:
    if getattr(__import__("sys"), "frozen", False):
        base = os.path.dirname(os.path.abspath(__import__("sys").executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    # Prefer data/gimbal_config.json; also accept root-level for frozen apps
    p = os.path.join(data_dir, "gimbal_config.json")
    legacy = os.path.join(base, "gimbal_config.json")
    return p if os.path.isfile(p) or not os.path.isfile(legacy) else legacy


def load_config() -> dict:
    path = _config_path()
    cfg = dict(_DEFAULT_CONFIG)
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
            if isinstance(raw, dict):
                cfg.update({k: raw[k] for k in raw if k in _DEFAULT_CONFIG})
    except Exception as e:
        logger.warning("Failed to load gimbal config: %s", e)
    return cfg


def save_config(updates: dict) -> dict:
    cfg = load_config()
    for k, v in (updates or {}).items():
        if k in _DEFAULT_CONFIG:
            cfg[k] = v
    path = _config_path()
    # Always write under data/
    if getattr(__import__("sys"), "frozen", False):
        base = os.path.dirname(os.path.abspath(__import__("sys").executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "data", "gimbal_config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def _clamp(pan: float, tilt: float):
    if pan < _PAN_MIN or pan > _PAN_MAX or tilt < _TILT_MIN or tilt > _TILT_MAX:
        return False, pan, tilt
    return True, pan, tilt


def _forward(method: str, path: str, body: Optional[dict] = None) -> Optional[dict]:
    """Forward request to remote gimbal host. Returns parsed JSON or None if no host / failed."""
    cfg = load_config()
    host = (cfg.get("gimbal_host") or "").strip().rstrip("/")
    if not host:
        return None
    url = host + path
    data = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = (cfg.get("bearer_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    timeout = float(cfg.get("timeout_sec") or 3.0)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return {"success": True}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            parsed = json.loads(err_body) if err_body.strip() else {}
        except Exception:
            parsed = {"success": False, "message": str(e)}
        parsed.setdefault("success", False)
        parsed["_http_status"] = e.code
        return parsed
    except Exception as e:
        logger.warning("Gimbal forward %s %s failed: %s", method, url, e)
        return {"success": False, "message": f"Gimbal host unreachable: {e}", "_http_status": 502}


def get_status() -> dict:
    remote = _forward("GET", "/api/v1/gimbal/status")
    if remote is not None and remote.get("success") and isinstance(remote.get("data"), dict):
        with _lock:
            _state.update({
                "pan": float(remote["data"].get("pan", _state["pan"])),
                "tilt": float(remote["data"].get("tilt", _state["tilt"])),
                "moving": bool(remote["data"].get("moving", False)),
                "stabilization": bool(remote["data"].get("stabilization", True)),
            })
            data = dict(_state)
        return {"success": True, "data": data, "source": "remote"}

    with _lock:
        data = dict(_state)
    out = {"success": True, "data": data, "source": "local"}
    if remote is not None and remote.get("success") is False:
        out["remote_error"] = remote.get("message")
    return out


def absolute_move(pan: float, tilt: float) -> dict:
    ok, pan, tilt = _clamp(float(pan), float(tilt))
    if not ok:
        return {
            "success": False,
            "errorCode": "ANGLE_LIMIT",
            "message": "Requested angle exceeds mechanical limits.",
        }
    remote = _forward("POST", "/api/v1/gimbal/move", {"pan": pan, "tilt": tilt})
    if remote is not None and "success" in remote:
        if remote.get("success"):
            with _lock:
                _state["pan"] = pan
                _state["tilt"] = tilt
                _state["moving"] = True
        return remote
    with _lock:
        _state["pan"] = pan
        _state["tilt"] = tilt
        _state["moving"] = True
    return {"success": True, "message": "Move command accepted.", "source": "local"}


def relative_move(pan_delta: float, tilt_delta: float) -> dict:
    remote = _forward(
        "POST",
        "/api/v1/gimbal/move/relative",
        {"panDelta": float(pan_delta), "tiltDelta": float(tilt_delta)},
    )
    if remote is not None and "success" in remote:
        if remote.get("success"):
            with _lock:
                np = _state["pan"] + float(pan_delta)
                nt = _state["tilt"] + float(tilt_delta)
                ok, np, nt = _clamp(np, nt)
                if ok:
                    _state["pan"] = np
                    _state["tilt"] = nt
                    _state["moving"] = True
        return remote

    with _lock:
        np = _state["pan"] + float(pan_delta)
        nt = _state["tilt"] + float(tilt_delta)
        ok, np, nt = _clamp(np, nt)
        if not ok:
            return {
                "success": False,
                "errorCode": "ANGLE_LIMIT",
                "message": "Requested angle exceeds mechanical limits.",
            }
        _state["pan"] = np
        _state["tilt"] = nt
        _state["moving"] = True
    return {"success": True, "message": "Relative movement initiated.", "source": "local"}


def jog(pan_velocity: float, tilt_velocity: float) -> dict:
    remote = _forward(
        "POST",
        "/api/v1/gimbal/jog",
        {"panVelocity": float(pan_velocity), "tiltVelocity": float(tilt_velocity)},
    )
    if remote is not None and "success" in remote:
        if remote.get("success"):
            with _lock:
                _state["moving"] = True
        return remote
    with _lock:
        _state["moving"] = True
    return {"success": True, "message": "Continuous movement started.", "source": "local"}


def stop() -> dict:
    remote = _forward("POST", "/api/v1/gimbal/stop", {})
    if remote is not None and "success" in remote:
        if remote.get("success"):
            with _lock:
                _state["moving"] = False
        return remote
    with _lock:
        _state["moving"] = False
    return {"success": True, "message": "Motion stopped.", "source": "local"}


def home() -> dict:
    remote = _forward("POST", "/api/v1/gimbal/home", {})
    if remote is not None and "success" in remote:
        if remote.get("success"):
            with _lock:
                _state["pan"] = 0.0
                _state["tilt"] = 0.0
                _state["moving"] = True
        return remote
    with _lock:
        _state["pan"] = 0.0
        _state["tilt"] = 0.0
        _state["moving"] = True
    return {"success": True, "message": "Returning to home position.", "source": "local"}


def direction_jog(direction: str) -> dict:
    """Map UI pad directions to ICD continuous jog velocities."""
    cfg = load_config()
    speed = abs(float(cfg.get("jog_speed") or 12.0))
    d = (direction or "").strip().lower()
    mapping = {
        "left": (-speed, 0.0),
        "right": (speed, 0.0),
        "up": (0.0, speed),
        "down": (0.0, -speed),
    }
    if d not in mapping:
        return {"success": False, "message": f"Unknown direction: {direction}"}
    pan_v, tilt_v = mapping[d]
    return jog(pan_v, tilt_v)


def direction_nudge(direction: str) -> dict:
    """Single click relative nudge (ICD relative move)."""
    cfg = load_config()
    step = abs(float(cfg.get("nudge_degrees") or 3.0))
    d = (direction or "").strip().lower()
    mapping = {
        "left": (-step, 0.0),
        "right": (step, 0.0),
        "up": (0.0, step),
        "down": (0.0, -step),
    }
    if d not in mapping:
        return {"success": False, "message": f"Unknown direction: {direction}"}
    pan_d, tilt_d = mapping[d]
    return relative_move(pan_d, tilt_d)
