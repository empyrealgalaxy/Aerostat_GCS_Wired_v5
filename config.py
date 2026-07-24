import json
import os
from typing import Dict, Any

class ConfigManager:
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.default_config = {
            "mqtt": {
                "broker": "3ec254ca2f5d4fc38600fa7277517ea0.s1.eu.hivemq.cloud",
                "port": 8883,
                "username": "Parveenespcode",
                "password": "Galaxy21",
                "use_tls": True,
                "topic": "parveenesp32/sensor_data"
            },
            "parameters": {
                "helium_pressure_mbar": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 20.0,
                    "unit": "mbar",
                    "display_name": "Helium Pressure",
                    "category": "pressure"
                },
                "ballonet_pressure_mbar": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 20.0,
                    "unit": "mbar",
                    "display_name": "Ballonet Pressure",
                    "category": "pressure"
                },
                "windscreen_pressure_mbar": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 20.0,
                    "unit": "mbar",
                    "display_name": "Windscreen Pressure",
                    "category": "pressure"
                },
                "ambient_pressure_mbar": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 25.0,
                    "unit": "mbar",
                    "display_name": "Ambient Pressure",
                    "category": "pressure"
                },
                "confluence_point_tension_N": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 25.0,
                    "unit": "N",
                    "display_name": "Confluence Point Tension",
                    "category": "tether"
                },
                "winch_tether_tension_kg": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 5.0,
                    "threshold_max": 25.0,
                    "unit": "N",
                    "display_name": "Winch Tension",
                    "category": "tether"
                },
                "helium_temp_C": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 10.0,
                    "threshold_max": 30.0,
                    "unit": "°C",
                    "display_name": "Helium Temperature",
                    "category": "temperature"
                },
                "payload_temp_C": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 10.0,
                    "threshold_max": 30.0,
                    "unit": "°C",
                    "display_name": "Payload Temperature",
                    "category": "temperature"
                },
                "ambient_temp_C": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 10.0,
                    "threshold_max": 30.0,
                    "unit": "°C",
                    "display_name": "Ambient Temperature",
                    "category": "temperature"
                },
                "windscreen_temp_C": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 10.0,
                    "threshold_max": 30.0,
                    "unit": "°C",
                    "display_name": "Windscreen Temperature",
                    "category": "temperature"
                },
                "pitch_degrees": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": -90.0,
                    "threshold_max": 90.0,
                    "unit": "°",
                    "display_name": "Pitch",
                    "category": "position"
                },
                "roll_degrees": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": -90.0,
                    "threshold_max": 90.0,
                    "unit": "°",
                    "display_name": "Roll",
                    "category": "position"
                },
                "yaw_degrees": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 360.0,
                    "unit": "°",
                    "display_name": "Yaw",
                    "category": "position"
                },
                "altitude_m": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 1000.0,
                    "unit": "m",
                    "display_name": "Altitude",
                    "category": "position"
                },
                "voltage_V": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 20.0,
                    "threshold_max": 40.0,
                    "unit": "V",
                    "display_name": "Voltage",
                    "category": "electrical"
                },
                "current_A": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 50.0,
                    "unit": "A",
                    "display_name": "Current",
                    "category": "electrical"
                },
                "ground_voltage_V": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 20.0,
                    "threshold_max": 40.0,
                    "unit": "V",
                    "display_name": "Ground Voltage",
                    "category": "electrical"
                },
                "ground_current_A": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 50.0,
                    "unit": "A",
                    "display_name": "Ground Current",
                    "category": "electrical"
                },
                "wind_direction_degrees": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 360.0,
                    "unit": "°",
                    "display_name": "Wind Direction",
                    "category": "weather"
                },
                "ground_wind_direction_degrees": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": 0.0,
                    "threshold_max": 360.0,
                    "unit": "°",
                    "display_name": "Ground Wind Direction",
                    "category": "weather"
                },
                "ground_temperature_C": {
                    "enabled": True,
                    "visible": True,
                    "threshold_min": -20.0,
                    "threshold_max": 50.0,
                    "unit": "°C",
                    "display_name": "Ground Temperature",
                    "category": "weather"
                }
            },
            "screens": {
                "primary": {
                    "name": "Primary Monitor",
                    "categories": ["pressure", "temperature", "position"]
                },
                "secondary": {
                    "name": "Secondary Monitor",
                    "categories": ["electrical", "weather", "status"]
                },
                "controls": {
                    "name": "Control Panel",
                    "categories": ["pressurization", "charts", "video"]
                }
            },
            "users": {
                "admin": {
                    "password": "admin123",
                    "role": "admin",
                    "permissions": ["view", "configure", "control"]
                },
                "operator": {
                    "password": "operator123",
                    "role": "operator",
                    "permissions": ["view", "control"]
                },
                "viewer": {
                    "password": "viewer123",
                    "role": "viewer",
                    "permissions": ["view"]
                }
            },
            "alerts": {
                "enabled": True,
                "email_notifications": False,
                "sound_alerts": True,
                "alert_thresholds": {
                    "critical": 0.9,
                    "warning": 0.7,
                    "info": 0.5
                }
            }
        }
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file or create default"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                # Merge with default config to ensure all keys exist
                return self._merge_config(self.default_config, loaded_config)
            else:
                self.save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.default_config.copy()

    def save_config(self, config: Dict[str, Any] = None) -> bool:
        """Save configuration to file"""
        try:
            config_to_save = config if config else self.config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def _merge_config(self, default: Dict, loaded: Dict) -> Dict:
        """Recursively merge loaded config with default config"""
        result = default.copy()
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key_path: str, default=None):
        """Get configuration value using dot notation (e.g., 'mqtt.broker')"""
        keys = key_path.split('.')
        value = self.config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value: Any) -> bool:
        """Set configuration value using dot notation"""
        keys = key_path.split('.')
        target = self.config
        try:
            for key in keys[:-1]:
                if key not in target:
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
            return self.save_config()
        except Exception as e:
            print(f"Error setting config value: {e}")
            return False

    def get_parameter_config(self, parameter: str = None):
        """Get parameter configuration"""
        if parameter:
            return self.config.get("parameters", {}).get(parameter, {})
        return self.config.get("parameters", {})

    def update_parameter_config(self, parameter: str, config: Dict[str, Any]) -> bool:
        """Update parameter configuration"""
        if "parameters" not in self.config:
            self.config["parameters"] = {}
        
        if parameter not in self.config["parameters"]:
            self.config["parameters"][parameter] = {}
        
        self.config["parameters"][parameter].update(config)
        return self.save_config()

    def get_user(self, username: str):
        """Get user configuration"""
        return self.config.get("users", {}).get(username, {})

    def get_mqtt_config(self):
        """Get MQTT configuration"""
        return self.config.get("mqtt", {})

    def get_screen_config(self, screen: str = None):
        """Get screen configuration"""
        if screen:
            return self.config.get("screens", {}).get(screen, {})
        return self.config.get("screens", {})

    def get_visible_parameters(self):
        """Get list of visible parameters"""
        visible = {}
        for param, config in self.config.get("parameters", {}).items():
            if config.get("visible", True):
                visible[param] = config
        return visible

    def get_enabled_parameters(self):
        """Get list of enabled parameters for monitoring"""
        enabled = {}
        for param, config in self.config.get("parameters", {}).items():
            if config.get("enabled", True):
                enabled[param] = config
        return enabled

    def check_threshold_violation(self, parameter: str, value: float):
        """Check if parameter value violates thresholds"""
        param_config = self.get_parameter_config(parameter)
        if not param_config or not param_config.get("enabled", True):
            return None
        
        min_threshold = param_config.get("threshold_min")
        max_threshold = param_config.get("threshold_max")
        
        if min_threshold is not None and value < min_threshold:
            return {
                "type": "min_violation",
                "parameter": parameter,
                "value": value,
                "threshold": min_threshold,
                "severity": "warning"
            }
        
        if max_threshold is not None and value > max_threshold:
            return {
                "type": "max_violation", 
                "parameter": parameter,
                "value": value,
                "threshold": max_threshold,
                "severity": "critical"
            }
        
        return None

# Global config instance
config_manager = ConfigManager()
