"""
Intrusion Detection System with Real-time Tracking and Alerting
Detects when tracked people enter restricted zones and triggers alerts
"""

import cv2
import numpy as np
import logging
import time
import json
import os
from typing import List, Dict, Tuple, Any, Optional
from datetime import datetime
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


class IntrusionZone:
    """Represents a restricted zone for intrusion detection"""
    
    def __init__(self, zone_id: str, name: str, points: List[Tuple[int, int]], 
                 enabled: bool = True, alert_level: str = "high"):
        """
        Args:
            zone_id: Unique identifier for the zone
            name: Human-readable name
            points: List of (x, y) points defining the polygon (minimum 3 points)
            enabled: Whether the zone is active
            alert_level: "low", "medium", "high", "critical"
        """
        self.zone_id = zone_id
        self.name = name
        self.points = np.array(points, dtype=np.int32)
        self.enabled = enabled
        self.alert_level = alert_level
        self.created_at = datetime.now().isoformat()
        
        # Validate polygon
        if len(self.points) < 3:
            raise ValueError("Zone must have at least 3 points to form a polygon")
    
    def contains_point(self, point: Tuple[int, int]) -> bool:
        """Check if a point is inside the zone using ray casting algorithm"""
        if not self.enabled:
            return False
        
        x, y = point
        n = len(self.points)
        inside = False
        
        p1x, p1y = self.points[0]
        for i in range(1, n + 1):
            p2x, p2y = self.points[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def contains_bbox(self, bbox: Tuple[int, int, int, int]) -> bool:
        """
        Check if a bounding box intersects with the zone
        Args:
            bbox: (x1, y1, x2, y2)
        Returns:
            True if bbox center or any corner is inside the zone
        """
        if not self.enabled:
            return False
        
        x1, y1, x2, y2 = bbox
        
        # Check center point
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        if self.contains_point((center_x, center_y)):
            return True
        
        # Check corners
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        for corner in corners:
            if self.contains_point(corner):
                return True
        
        # Check if zone polygon intersects with bbox rectangle
        # Simple check: if any zone point is inside bbox
        for point in self.points:
            px, py = point
            if x1 <= px <= x2 and y1 <= py <= y2:
                return True
        
        return False
    
    def to_dict(self) -> Dict:
        """Convert zone to dictionary for JSON serialization"""
        return {
            'zone_id': self.zone_id,
            'name': self.name,
            'points': self.points.tolist(),
            'enabled': self.enabled,
            'alert_level': self.alert_level,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'IntrusionZone':
        """Create zone from dictionary"""
        return cls(
            zone_id=data['zone_id'],
            name=data['name'],
            points=[tuple(p) for p in data['points']],
            enabled=data.get('enabled', True),
            alert_level=data.get('alert_level', 'high')
        )


class IntrusionTracker:
    """Tracks objects (humans, animals, vehicles) and detects intrusions into restricted zones"""
    
    def __init__(self, cooldown_seconds: float = 5.0):
        """
        Args:
            cooldown_seconds: Minimum time between alerts for the same object in the same zone
        """
        self.zones: Dict[str, IntrusionZone] = {}
        self.tracked_people: Dict[int, Dict] = {}  # track_id -> {zone_ids: set, last_alert: timestamp, category, class}
        self.cooldown_seconds = cooldown_seconds
        self.intrusion_history: List[Dict] = []
        self.max_history = 1000  # Keep last 1000 intrusion events
        
        # Statistics
        self.stats = {
            'total_intrusions': 0,
            'active_intrusions': 0,
            'zones_count': 0,
            'last_intrusion_time': None
        }
    
    def _get_object_type_label(self, category: str, class_name: str) -> str:
        """Get human-readable label for object type"""
        if category == 'human':
            return 'Human'
        elif category == 'animal':
            return f'Animal ({class_name.capitalize()})'
        elif category == 'vehicle':
            return f'Vehicle ({class_name.capitalize()})'
        else:
            return f'Object ({class_name.capitalize()})'
    
    def add_zone(self, zone: IntrusionZone):
        """Add or update an intrusion zone"""
        self.zones[zone.zone_id] = zone
        self.stats['zones_count'] = len([z for z in self.zones.values() if z.enabled])
        logger.info(f"Added intrusion zone: {zone.name} (ID: {zone.zone_id})")
    
    def remove_zone(self, zone_id: str) -> bool:
        """Remove an intrusion zone"""
        if zone_id in self.zones:
            del self.zones[zone_id]
            self.stats['zones_count'] = len([z for z in self.zones.values() if z.enabled])
            logger.info(f"Removed intrusion zone: {zone_id}")
            return True
        return False
    
    def get_zones(self) -> List[Dict]:
        """Get all zones as dictionaries"""
        return [zone.to_dict() for zone in self.zones.values()]
    
    def check_intrusions(self, detections: List[Dict], frame_timestamp: float = None) -> List[Dict]:
        """
        Check for intrusions in current detections (humans, animals, vehicles)
        Args:
            detections: List of object detections with 'bbox', 'track_id', and 'category'
            frame_timestamp: Current frame timestamp (defaults to current time)
        Returns:
            List of intrusion events
        """
        if frame_timestamp is None:
            frame_timestamp = time.time()
        
        intrusions = []
        active_track_ids = set()
        
        # Check each detected object (human, animal, or vehicle)
        for detection in detections:
            if 'track_id' not in detection or 'bbox' not in detection:
                continue
            
            track_id = detection['track_id']
            bbox = detection['bbox']
            category = detection.get('category', 'unknown')
            class_name = detection.get('class', 'unknown')
            active_track_ids.add(track_id)
            
            # Initialize tracking for new object
            if track_id not in self.tracked_people:
                self.tracked_people[track_id] = {
                    'current_zones': set(),
                    'last_alert': {},
                    'first_seen': frame_timestamp,
                    'category': category,
                    'class': class_name
                }
            
            object_data = self.tracked_people[track_id]
            current_zones = object_data['current_zones']
            new_zones = set()
            
            # Check which zones this object is in
            for zone_id, zone in self.zones.items():
                if zone.contains_bbox(bbox):
                    new_zones.add(zone_id)
                    
                    # Check if this is a new intrusion (not in zone before)
                    if zone_id not in current_zones:
                        # Check cooldown
                        last_alert_time = object_data['last_alert'].get(zone_id, 0)
                        time_since_last_alert = frame_timestamp - last_alert_time
                        
                        if time_since_last_alert >= self.cooldown_seconds:
                            # New intrusion detected!
                            intrusion_event = {
                                'track_id': track_id,
                                'zone_id': zone_id,
                                'zone_name': zone.name,
                                'alert_level': zone.alert_level,
                                'bbox': bbox,
                                'timestamp': frame_timestamp,
                                'datetime': datetime.fromtimestamp(frame_timestamp).isoformat(),
                                'confidence': detection.get('confidence', 0.0),
                                'category': category,
                                'class': class_name,
                                'object_type': self._get_object_type_label(category, class_name)
                            }
                            intrusions.append(intrusion_event)
                            
                            # Update tracking
                            object_data['last_alert'][zone_id] = frame_timestamp
                            
                            # Log intrusion
                            object_label = self._get_object_type_label(category, class_name)
                            logger.warning(
                                f"🚨 INTRUSION DETECTED: {object_label} #{track_id} entered zone '{zone.name}' "
                                f"(Level: {zone.alert_level})"
                            )
                            
                            # Update statistics
                            self.stats['total_intrusions'] += 1
                            self.stats['last_intrusion_time'] = frame_timestamp
            
            # Update current zones for this object
            object_data['current_zones'] = new_zones
        
        # Remove tracking for objects no longer detected
        disappeared_tracks = set(self.tracked_people.keys()) - active_track_ids
        for track_id in disappeared_tracks:
            del self.tracked_people[track_id]
        
        # Update active intrusions count
        self.stats['active_intrusions'] = sum(
            len(person['current_zones']) 
            for person in self.tracked_people.values()
        )
        
        # Add to history
        for intrusion in intrusions:
            self.intrusion_history.append(intrusion)
            if len(self.intrusion_history) > self.max_history:
                self.intrusion_history.pop(0)
        
        return intrusions
    
    def get_statistics(self) -> Dict:
        """Get intrusion detection statistics"""
        return {
            **self.stats,
            'tracked_people_count': len(self.tracked_people),
            'recent_intrusions': len([
                i for i in self.intrusion_history 
                if time.time() - i['timestamp'] < 300  # Last 5 minutes
            ])
        }
    
    def get_recent_intrusions(self, limit: int = 50) -> List[Dict]:
        """Get recent intrusion events"""
        return sorted(
            self.intrusion_history,
            key=lambda x: x['timestamp'],
            reverse=True
        )[:limit]
    
    def clear_history(self):
        """Clear intrusion history"""
        self.intrusion_history.clear()
        logger.info("Intrusion history cleared")
    
    def draw_zones(self, image: np.ndarray) -> np.ndarray:
        """Draw intrusion zones on image"""
        img = image.copy()
        
        # Color mapping for alert levels
        level_colors = {
            'low': (0, 255, 255),      # Yellow
            'medium': (0, 165, 255),   # Orange
            'high': (0, 0, 255),        # Red
            'critical': (128, 0, 128)   # Purple
        }
        
        for zone in self.zones.values():
            if not zone.enabled:
                continue
            
            color = level_colors.get(zone.alert_level, (0, 0, 255))
            
            # Draw filled polygon with transparency
            overlay = img.copy()
            cv2.fillPoly(overlay, [zone.points], color)
            cv2.addWeighted(overlay, 0.3, img, 0.7, 0, img)
            
            # Draw polygon outline
            cv2.polylines(img, [zone.points], True, color, 2)
            
            # Draw zone label
            if len(zone.points) > 0:
                # Find centroid for label
                M = cv2.moments(zone.points)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    label = f"{zone.name} ({zone.alert_level})"
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                    )
                    
                    # Label background
                    cv2.rectangle(
                        img,
                        (cx - text_width // 2 - 5, cy - text_height - 10),
                        (cx + text_width // 2 + 5, cy + 5),
                        color,
                        -1
                    )
                    
                    # Label text
                    cv2.putText(
                        img, label,
                        (cx - text_width // 2, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2
                    )
        
        return img


class IntrusionAlertManager:
    """Manages alerts for intrusion events"""
    
    def __init__(self, config_path: str = None):
        """
        Args:
            config_path: Path to alert configuration file
        """
        self.config = {
            'sound_enabled': True,
            'visual_enabled': True,
            'log_enabled': True,
            'email_enabled': False,
            'alert_levels': {
                'low': {'sound': False, 'visual': True},
                'medium': {'sound': True, 'visual': True},
                'high': {'sound': True, 'visual': True},
                'critical': {'sound': True, 'visual': True}
            }
        }
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception as e:
                logger.warning(f"Could not load alert config: {e}")
        
        self.alert_log_path = Path("logs/intrusion_alerts.log")
        self.alert_log_path.parent.mkdir(exist_ok=True)
    
    def trigger_alert(self, intrusion_event: Dict):
        """Trigger alerts for an intrusion event"""
        alert_level = intrusion_event.get('alert_level', 'medium')
        zone_name = intrusion_event.get('zone_name', 'Unknown Zone')
        track_id = intrusion_event.get('track_id', 'Unknown')
        
        # Visual alert
        if self.config['visual_enabled']:
            level_config = self.config['alert_levels'].get(alert_level, {})
            if level_config.get('visual', True):
                logger.warning(
                    f"🔴 VISUAL ALERT: Person #{track_id} in zone '{zone_name}' "
                    f"(Level: {alert_level})"
                )
        
        # Sound alert
        if self.config['sound_enabled']:
            level_config = self.config['alert_levels'].get(alert_level, {})
            if level_config.get('sound', False):
                logger.warning(
                    f"🔊 SOUND ALERT: Person #{track_id} in zone '{zone_name}' "
                    f"(Level: {alert_level})"
                )
        
        # Log alert
        if self.config['log_enabled']:
            self._log_alert(intrusion_event)
        
        # Email alert (if configured)
        if self.config.get('email_enabled', False):
            # TODO: Implement email sending
            pass
    
    def _log_alert(self, intrusion_event: Dict):
        """Log intrusion alert to file"""
        try:
            with open(self.alert_log_path, 'a') as f:
                log_entry = {
                    'timestamp': intrusion_event.get('datetime', datetime.now().isoformat()),
                    'zone_name': intrusion_event.get('zone_name'),
                    'zone_id': intrusion_event.get('zone_id'),
                    'track_id': intrusion_event.get('track_id'),
                    'alert_level': intrusion_event.get('alert_level'),
                    'bbox': intrusion_event.get('bbox')
                }
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to log alert: {e}")


# Global instances
_intrusion_tracker = None
_alert_manager = None


def get_intrusion_tracker() -> IntrusionTracker:
    """Get or create global intrusion tracker instance"""
    global _intrusion_tracker
    if _intrusion_tracker is None:
        _intrusion_tracker = IntrusionTracker()
    return _intrusion_tracker


def get_alert_manager() -> IntrusionAlertManager:
    """Get or create global alert manager instance"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = IntrusionAlertManager()
    return _alert_manager

