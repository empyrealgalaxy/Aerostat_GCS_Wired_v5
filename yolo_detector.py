"""
YOLOv8 Detection Service for Person Detection, Object Detection, Counting, and Tracking
"""

import cv2
import numpy as np
import logging
from typing import List, Dict, Tuple, Any
from collections import defaultdict
import time
import os

# Workaround for Windows Ultralytics directory issue
# Set environment variable to use a different config directory
import tempfile
_ultralytics_temp_dir = os.path.join(tempfile.gettempdir(), "Ultralytics_Config")
os.environ["YOLO_CONFIG_DIR"] = _ultralytics_temp_dir
# Ensure the temp directory exists
try:
    os.makedirs(_ultralytics_temp_dir, exist_ok=True)
except:
    pass

# Now import ultralytics
# Note: The YOLO_CONFIG_DIR env var might not work for all versions
# If import fails, we'll provide a helpful error message
try:
    from ultralytics import YOLO
except (FileExistsError, OSError) as e:
    # If the env var didn't work, try to fix the default location
    if "Ultralytics" in str(e) or "183" in str(e):
        ultralytics_dir_str = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Ultralytics")
        error_msg = (
            f"Ultralytics import failed due to Windows file system issue.\n"
            f"The file/directory at '{ultralytics_dir_str}' is blocking Ultralytics.\n"
            f"Please run this PowerShell command (as Administrator if needed):\n"
            f"  Remove-Item -Path '{ultralytics_dir_str}' -Force -Recurse -ErrorAction SilentlyContinue\n"
            f"Then restart your server."
        )
        logger = logging.getLogger(__name__)
        logger.error(error_msg)
        raise ImportError(error_msg)
    else:
        raise

logger = logging.getLogger(__name__)

class PersonTracker:
    """Simple centroid-based tracker for people"""
    
    def __init__(self, max_disappeared=10, max_distance=100):
        self.next_id = 0
        self.objects = {}  # {id: {'centroid': (x, y), 'bbox': (x1, y1, x2, y2), 'disappeared': 0}}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
    
    def update(self, detections: List[Dict]) -> List[Dict]:
        """
        Update tracker with new detections
        detections: List of {'bbox': (x1, y1, x2, y2), 'confidence': float, 'class': str}
        Returns: List with added 'track_id' field
        """
        if len(detections) == 0:
            # Mark all objects as disappeared
            for obj_id in list(self.objects.keys()):
                self.objects[obj_id]['disappeared'] += 1
                if self.objects[obj_id]['disappeared'] > self.max_disappeared:
                    del self.objects[obj_id]
            return []
        
        # Calculate centroids for new detections
        input_centroids = []
        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            input_centroids.append((cx, cy))
        
        # If no existing objects, register all detections
        if len(self.objects) == 0:
            for i, det in enumerate(detections):
                x1, y1, x2, y2 = det['bbox']
                cx, cy = input_centroids[i]
                self.objects[self.next_id] = {
                    'centroid': (cx, cy),
                    'bbox': (x1, y1, x2, y2),
                    'disappeared': 0
                }
                det['track_id'] = self.next_id
                self.next_id += 1
        else:
            # Match existing objects to new detections
            object_centroids = [obj['centroid'] for obj in self.objects.values()]
            
            # Calculate distances
            D = self._calculate_distances(object_centroids, input_centroids)
            
            # Find minimum values in each row and column
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            
            used_row_indices = set()
            used_col_indices = set()
            
            # Match objects to detections
            for (row, col) in zip(rows, cols):
                if row in used_row_indices or col in used_col_indices:
                    continue
                
                if D[row, col] > self.max_distance:
                    continue
                
                obj_id = list(self.objects.keys())[row]
                self.objects[obj_id]['centroid'] = input_centroids[col]
                self.objects[obj_id]['bbox'] = detections[col]['bbox']
                self.objects[obj_id]['disappeared'] = 0
                detections[col]['track_id'] = obj_id
                
                used_row_indices.add(row)
                used_col_indices.add(col)
            
            # Handle unmatched objects and detections
            unused_rows = set(range(0, D.shape[0])).difference(used_row_indices)
            unused_cols = set(range(0, D.shape[1])).difference(used_col_indices)
            
            # Mark unmatched objects as disappeared
            for row in unused_rows:
                obj_id = list(self.objects.keys())[row]
                self.objects[obj_id]['disappeared'] += 1
                if self.objects[obj_id]['disappeared'] > self.max_disappeared:
                    del self.objects[obj_id]
            
            # Register new detections
            for col in unused_cols:
                x1, y1, x2, y2 = detections[col]['bbox']
                cx, cy = input_centroids[col]
                self.objects[self.next_id] = {
                    'centroid': (cx, cy),
                    'bbox': (x1, y1, x2, y2),
                    'disappeared': 0
                }
                detections[col]['track_id'] = self.next_id
                self.next_id += 1
        
        return detections
    
    def _calculate_distances(self, centroids1: List[Tuple], centroids2: List[Tuple]) -> np.ndarray:
        """Calculate Euclidean distances between two sets of centroids"""
        D = np.zeros((len(centroids1), len(centroids2)))
        for i, c1 in enumerate(centroids1):
            for j, c2 in enumerate(centroids2):
                D[i, j] = np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
        return D


class YOLODetector:
    """YOLOv8-based detector for people and objects"""
    
    @staticmethod
    def _calculate_iou(box1: Tuple[int, int, int, int], box2: Tuple[int, int, int, int]) -> float:
        """
        Calculate Intersection over Union (IoU) between two bounding boxes
        Args:
            box1: (x1, y1, x2, y2)
            box2: (x1, y1, x2, y2)
        Returns:
            IoU value between 0 and 1
        """
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Calculate intersection area
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Calculate union area
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    @staticmethod
    def _calculate_bbox_area(bbox: Tuple[int, int, int, int]) -> int:
        """Calculate area of bounding box"""
        x1, y1, x2, y2 = bbox
        return (x2 - x1) * (y2 - y1)
    
    @staticmethod
    def _calculate_bbox_center(bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
        """Calculate center point of bounding box"""
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @staticmethod
    def _calculate_center_distance(bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]) -> float:
        """Calculate distance between centers of two bounding boxes"""
        center1 = YOLODetector._calculate_bbox_center(bbox1)
        center2 = YOLODetector._calculate_bbox_center(bbox2)
        return ((center1[0] - center2[0])**2 + (center1[1] - center2[1])**2)**0.5
    
    @staticmethod
    def _filter_duplicate_detections(detections: List[Dict], iou_threshold: float = 0.40) -> List[Dict]:
        """
        Filter out duplicate detections of the same person using multiple criteria
        Uses IoU overlap, center distance, and area overlap to identify duplicates
        Args:
            detections: List of detection dictionaries with 'bbox' and 'confidence'
            iou_threshold: IoU threshold above which detections are considered duplicates (0.40 = 40% overlap)
                          Lower threshold (0.40) is more aggressive at removing duplicates
        Returns:
            Filtered list of detections
        """
        if len(detections) <= 1:
            return detections
        
        # Sort by confidence (highest first) - keep highest confidence detections
        sorted_detections = sorted(detections, key=lambda x: x['confidence'], reverse=True)
        filtered = []
        
        for det in sorted_detections:
            is_duplicate = False
            det_bbox = det['bbox']
            det_area = YOLODetector._calculate_bbox_area(det_bbox)
            
            for kept_det in filtered:
                kept_bbox = kept_det['bbox']
                kept_area = YOLODetector._calculate_bbox_area(kept_bbox)
                
                # Calculate IoU overlap
                iou = YOLODetector._calculate_iou(det_bbox, kept_bbox)
                
                # Calculate center distance
                center_dist = YOLODetector._calculate_center_distance(det_bbox, kept_bbox)
                
                # Calculate average box dimension for distance threshold
                avg_width = ((det_bbox[2] - det_bbox[0]) + (kept_bbox[2] - kept_bbox[0])) / 2
                avg_height = ((det_bbox[3] - det_bbox[1]) + (kept_bbox[3] - kept_bbox[1])) / 2
                avg_size = (avg_width + avg_height) / 2
                
                # Check if this is a duplicate using multiple criteria:
                # 1. High IoU overlap (>40%)
                # 2. OR centers are very close (<30% of average box size) AND some overlap (>20% IoU)
                # 3. OR one box is mostly inside the other (>70% area overlap)
                area_overlap_ratio = min(det_area, kept_area) / max(det_area, kept_area) if max(det_area, kept_area) > 0 else 0
                
                if (iou > iou_threshold or 
                    (center_dist < avg_size * 0.30 and iou > 0.20) or
                    (area_overlap_ratio > 0.70 and iou > 0.25)):
                    # This detection is likely the same person, so skip it
                    is_duplicate = True
                    logger.info(f"Filtered duplicate: IoU={iou:.2f}, center_dist={center_dist:.1f}, area_ratio={area_overlap_ratio:.2f}, kept conf={kept_det['confidence']:.2f}, removed conf={det['confidence']:.2f}")
                    break
            
            if not is_duplicate:
                filtered.append(det)
        
        return filtered
    
    def _get_category(self, class_id: int) -> str:
        """Get category name for a class ID"""
        if class_id == self.person_class_id:
            return 'human'
        elif class_id in self.animal_class_ids:
            return 'animal'
        elif class_id in self.vehicle_class_ids:
            return 'vehicle'
        else:
            return 'other'
    
    def __init__(self, model_path: str = None, confidence_threshold: float = 0.15):
        """
        Initialize YOLO detector (supports YOLOv8, YOLOv10, YOLOv11, YOLOv12)
        Args:
            model_path: Path to custom YOLO model (None for default - tries YOLOv12s, YOLOv11s, etc.)
            confidence_threshold: Minimum confidence for detections (default 0.15 for better accuracy)
        """
        # Lower confidence threshold for better detection accuracy
        self.confidence_threshold = confidence_threshold
        self.tracker = PersonTracker()
        
        try:
            if model_path:
                self.model = YOLO(model_path)
                logger.info(f"Loaded custom model from {model_path}")
            else:
                # Try to load the latest YOLO models for best accuracy
                # YOLOv12 is the latest (best accuracy), YOLOv11 is also excellent
                # Falls back through versions if newer ones aren't available
                model_loaded = False
                
                # Try YOLOv12s (small) - latest and most accurate
                try:
                    self.model = YOLO('yolov12s.pt')
                    logger.info("✅ Loaded YOLOv12s model (latest - best accuracy for multiple people)")
                    model_loaded = True
                except Exception as e1:
                    logger.debug(f"YOLOv12s not available: {e1}")
                    
                    # Try YOLOv11s (small) - excellent accuracy
                    if not model_loaded:
                        try:
                            self.model = YOLO('yolov11s.pt')
                            logger.info("✅ Loaded YOLOv11s model (excellent accuracy for multiple people)")
                            model_loaded = True
                        except Exception as e2:
                            logger.debug(f"YOLOv11s not available: {e2}")
                            
                            # Try YOLOv10s (small) - good alternative
                            if not model_loaded:
                                try:
                                    self.model = YOLO('yolov10s.pt')
                                    logger.info("✅ Loaded YOLOv10s model (good accuracy)")
                                    model_loaded = True
                                except Exception as e3:
                                    logger.debug(f"YOLOv10s not available: {e3}")
                                    
                                    # Fallback to YOLOv8s
                                    if not model_loaded:
                                        try:
                                            self.model = YOLO('yolov8s.pt')
                                            logger.info("✅ Loaded YOLOv8s model (fallback)")
                                            model_loaded = True
                                        except Exception as e4:
                                            # Final fallback to YOLOv8n
                                            self.model = YOLO('yolov8n.pt')
                                            logger.info("✅ Loaded YOLOv8n model (final fallback)")
        except Exception as e:
            logger.error(f"Error loading YOLO model: {e}")
            raise
        
        # COCO class names (YOLOv8 default)
        self.class_names = self.model.names
        
        # Define class categories for humans, animals, and vehicles
        self.person_class_id = 0  # 'person' is class 0 in COCO
        
        # Animal classes in COCO dataset
        self.animal_class_ids = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23]  # bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe
        
        # Vehicle classes in COCO dataset
        self.vehicle_class_ids = [1, 2, 3, 4, 5, 6, 7, 8]  # bicycle, car, motorcycle, airplane, bus, train, truck, boat
        
        # All target classes (humans, animals, vehicles)
        self.target_class_ids = [self.person_class_id] + self.animal_class_ids + self.vehicle_class_ids
        
        logger.info("YOLOv8 detector initialized successfully")
        logger.info(f"Target classes: Humans (0), Animals ({len(self.animal_class_ids)} types), Vehicles ({len(self.vehicle_class_ids)} types)")
    
    # Minimum confidence floor — applied after the model's own filter.
    # 0.08 catches borderline-visible people without drowning in false positives.
    MIN_CONFIDENCE: float = 0.08

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        """Return a safe empty detection result with all expected keys."""
        return {
            'humans': [], 'animals': [], 'vehicles': [],
            'people': [],          # backward compat
            'objects': [],
            'human_count': 0, 'animal_count': 0, 'vehicle_count': 0,
            'people_count': 0,     # backward compat
            'total_targets': 0,
            'class_counts': {},
            'all_detections': [],
            'tracked_objects': [],
        }

    def detect(self, image: np.ndarray, track: bool = True,
               classes: List[int] = None) -> Dict[str, Any]:
        """
        Detect humans, animals, and vehicles in an image.

        Args:
            image : BGR numpy array
            track : maintain object IDs across frames
            classes : COCO class IDs to detect (None → all target classes)
        Returns:
            dict with detection results; never raises – returns _empty_result() on error
        """
        # Guard: reject invalid frames immediately
        if image is None or image.size == 0:
            logger.debug("detect(): empty/None image, skipping")
            return self._empty_result()

        if classes is None:
            classes = self.target_class_ids

        try:
            # Use a low inference-level threshold (0.05) so the model returns all
            # candidate boxes; we apply our own stricter filter below.
            # This prevents the model from silently discarding low-confidence
            # people in compressed / aerial video streams before we even see them.
            results = self.model(
                image,
                conf=0.05,
                iou=0.30,
                classes=classes,
                verbose=False,
            )
        except Exception as e:
            logger.error("YOLO inference failed: %s", e)
            return self._empty_result()

        # ── Parse detections ───────────────────────────────────────────────
        detections: List[Dict] = []
        human_detections:  List[Dict] = []
        animal_detections: List[Dict] = []
        vehicle_detections: List[Dict] = []
        other_detections:  List[Dict] = []

        try:
            # Safely check that results are non-empty
            if not results or results[0].boxes is None or len(results[0].boxes) == 0:
                logger.debug("No detections in this frame")
            else:
                boxes = results[0].boxes

                # Convert entire tensors to numpy once (avoids per-index tensor ops
                # and eliminates "list index out of range" on empty slices)
                try:
                    xyxy_np = boxes.xyxy.cpu().numpy()   # (N, 4)
                    cls_np  = boxes.cls.cpu().numpy()    # (N,)
                    conf_np = boxes.conf.cpu().numpy()   # (N,)
                except Exception as e:
                    logger.error("Failed to convert YOLO tensors to numpy: %s", e)
                    xyxy_np = cls_np = conf_np = []

                for xyxy, cls_id_f, confidence in zip(xyxy_np, cls_np, conf_np):
                    try:
                        confidence = float(confidence)

                        # Apply post-inference confidence threshold
                        # Use the instance threshold (set per detector), floored by MIN_CONFIDENCE
                        effective_threshold = max(self.confidence_threshold, self.MIN_CONFIDENCE)
                        if confidence < effective_threshold:
                            logger.debug("Skipping detection conf=%.3f < threshold=%.3f", confidence, effective_threshold)
                            continue

                        x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
                        cls_id = int(cls_id_f)

                        # Safely look up class name (unknown class → skip)
                        class_name = self.class_names.get(cls_id)
                        if class_name is None:
                            logger.debug("Unknown class_id %d, skipping", cls_id)
                            continue

                        category = self._get_category(cls_id)
                        detection = {
                            'bbox':       (x1, y1, x2, y2),
                            'confidence': confidence,
                            'class':      class_name,
                            'class_id':   cls_id,
                            'category':   category,
                        }
                        detections.append(detection)

                        if cls_id == self.person_class_id:
                            human_detections.append(detection)
                        elif cls_id in self.animal_class_ids:
                            animal_detections.append(detection)
                        elif cls_id in self.vehicle_class_ids:
                            vehicle_detections.append(detection)
                        else:
                            other_detections.append(detection)

                    except Exception as box_err:
                        # One bad box must never crash the whole frame
                        logger.debug("Skipping malformed box: %s", box_err)
                        continue

                logger.debug("Raw detections: %d humans, %d animals, %d vehicles",
                             len(human_detections), len(animal_detections), len(vehicle_detections))

        except Exception as parse_err:
            logger.error("Error parsing YOLO results: %s", parse_err)
            # Return whatever we managed to collect so far
            pass

        # ── Duplicate filtering ────────────────────────────────────────────
        if len(human_detections) > 1:
            before = len(human_detections)
            human_detections = self._filter_duplicate_detections(human_detections, iou_threshold=0.40)
            if len(human_detections) != before:
                logger.debug("Removed %d duplicate human detection(s)", before - len(human_detections))
        if len(animal_detections) > 1:
            animal_detections = self._filter_duplicate_detections(animal_detections, iou_threshold=0.40)
        if len(vehicle_detections) > 1:
            vehicle_detections = self._filter_duplicate_detections(vehicle_detections, iou_threshold=0.40)

        # ── Tracking ───────────────────────────────────────────────────────
        if track:
            if not hasattr(self, '_frame_count'):
                self._frame_count = 0
            self._frame_count += 1
            if self._frame_count % 150 == 0:
                self.tracker = PersonTracker()
                self._frame_count = 0

        all_target = human_detections + animal_detections + vehicle_detections
        tracked_objects: List[Dict] = []
        if track:
            try:
                tracked_objects = self.tracker.update(all_target) if all_target else []
                if not all_target:
                    self.tracker.update([])
            except Exception as track_err:
                logger.error("Tracker update failed: %s", track_err)
                tracked_objects = all_target  # fall back to untracked

        tracked_humans   = [o for o in tracked_objects if o.get('category') == 'human']
        tracked_animals  = [o for o in tracked_objects if o.get('category') == 'animal']
        tracked_vehicles = [o for o in tracked_objects if o.get('category') == 'vehicle']

        human_count   = len(tracked_humans)   if track else len(human_detections)
        animal_count  = len(tracked_animals)  if track else len(animal_detections)
        vehicle_count = len(tracked_vehicles) if track else len(vehicle_detections)
        total_targets = human_count + animal_count + vehicle_count

        class_counts: Dict[str, int] = defaultdict(int)
        for det in all_target:
            class_counts[det['class']] += 1

        if total_targets > 0:
            logger.info("Detected: %d humans, %d animals, %d vehicles",
                        human_count, animal_count, vehicle_count)
        else:
            logger.debug("No people/animals/vehicles detected in this frame")

        return {
            'humans':         tracked_humans   if track else human_detections,
            'animals':        tracked_animals  if track else animal_detections,
            'vehicles':       tracked_vehicles if track else vehicle_detections,
            'people':         tracked_humans   if track else human_detections,
            'objects':        other_detections,
            'human_count':    human_count,
            'animal_count':   animal_count,
            'vehicle_count':  vehicle_count,
            'people_count':   human_count,
            'total_targets':  total_targets,
            'class_counts':   dict(class_counts),
            'all_detections': detections,
            'tracked_objects': tracked_objects if track else all_target,
        }
    
    def draw_detections(self, image: np.ndarray, detections: Dict[str, Any]) -> np.ndarray:
        """
        Draw bounding boxes and labels on image.  Never raises.
        Green = human, Yellow = animal, Cyan = vehicle, Blue = other.
        """
        if image is None or image.size == 0:
            return image if image is not None else np.zeros((480, 640, 3), dtype=np.uint8)
        if not detections:
            return image.copy()

        img = image.copy()

        COLORS = {
            'human':   (0, 255, 0),
            'animal':  (0, 255, 255),
            'vehicle': (255, 255, 0),
            'other':   (255, 80, 0),
        }
        FONT       = cv2.FONT_HERSHEY_SIMPLEX
        FONT_SCALE = 0.5
        THICKNESS  = 2

        def _draw_box(obj: Dict, default_label: str, color: tuple) -> None:
            try:
                bbox = obj.get('bbox')
                if not bbox or len(bbox) != 4:
                    return
                x1, y1, x2, y2 = (int(v) for v in bbox)
                conf     = float(obj.get('confidence', 0))
                track_id = obj.get('track_id')
                name     = obj.get('class', default_label).capitalize()

                label = name
                if track_id is not None:
                    label += f" #{track_id}"
                label += f" {conf:.2f}"

                cv2.rectangle(img, (x1, y1), (x2, y2), color, THICKNESS)

                (tw, th), _ = cv2.getTextSize(label, FONT, FONT_SCALE, 1)
                label_y = max(y1, th + 10)
                cv2.rectangle(img, (x1, label_y - th - 6), (x1 + tw, label_y), color, -1)
                cv2.putText(img, label, (x1, label_y - 4), FONT, FONT_SCALE, (0, 0, 0), 1)
            except Exception as draw_err:
                logger.debug("draw_box error: %s", draw_err)

        for obj in detections.get('humans',   detections.get('people', [])):
            _draw_box(obj, 'Human',   COLORS['human'])
        for obj in detections.get('animals',  []):
            _draw_box(obj, 'Animal',  COLORS['animal'])
        for obj in detections.get('vehicles', []):
            _draw_box(obj, 'Vehicle', COLORS['vehicle'])
        for obj in detections.get('objects',  []):
            _draw_box(obj, 'Object',  COLORS['other'])

        return img


# Global detector instances: one for people (YOLOv8s), one for movement/activity gate (YOLOv8n)
_people_detector_instance = None
_movement_gate_detector_instance = None


def _model_path(name: str) -> str:
    """Resolve model path: try script directory first, then current dir, then name as-is for Ultralytics."""
    base = os.path.dirname(os.path.abspath(__file__))
    for candidate in [os.path.join(base, name), name]:
        if os.path.isfile(candidate):
            return candidate
    return name


def get_people_detector(model_path: str = None) -> YOLODetector:
    """
    Get detector for people (person) detection.
    Prefers yolov8l (large) for highest accuracy, falls back down the size chain.
    """
    global _people_detector_instance
    if _people_detector_instance is None:
        if model_path:
            candidates = [model_path]
        else:
            # yolov8s has the highest recall for people in practice benchmarks.
            # yolov10s and yolov8m as fallbacks, then larger/smaller models.
            candidates = [
                _model_path("yolov8s.pt")  or "yolov8s.pt",
                _model_path("yolov10s.pt") or "yolov10s.pt",
                _model_path("yolov8m.pt")  or "yolov8m.pt",
                _model_path("yolov8l.pt")  or "yolov8l.pt",
                _model_path("yolov8n.pt")  or "yolov8n.pt",
            ]
        last_err = None
        for path in candidates:
            try:
                _people_detector_instance = YOLODetector(model_path=path)
                logger.info(f"People detector loaded: {path}")
                break
            except Exception as e:
                last_err = e
                logger.warning(f"Could not load model {path}: {e}")
        if _people_detector_instance is None:
            raise RuntimeError(f"Could not load any people detection model: {last_err}")
    return _people_detector_instance


def get_movement_gate_detector(model_path: str = None) -> YOLODetector:
    """
    Get lightweight detector for movement/activity gating (frame-by-frame).
    Uses YOLOv8n. Run first; only run people detector when this detects activity.
    """
    global _movement_gate_detector_instance
    if _movement_gate_detector_instance is None:
        path = model_path or _model_path("yolov8n.pt") or "yolov8n.pt"
        _movement_gate_detector_instance = YOLODetector(model_path=path, confidence_threshold=0.2)
        logger.info(f"Movement gate detector loaded: {path}")
    return _movement_gate_detector_instance


def get_detector() -> YOLODetector:
    """Get or create global people detector (backward compatible)."""
    return get_people_detector()

