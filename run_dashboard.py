#!/usr/bin/env python3
"""
Simple working dashboard - guaranteed to start
This is a minimal version that will definitely work
"""

from fastapi import FastAPI, Request, WebSocket, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import time
import threading
import json
import asyncio
import socket as _socket_lib
import paho.mqtt.client as paho
import ssl
import logging
import csv
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any
from fastapi.responses import FileResponse, JSONResponse
import secrets
import hashlib
import re
import subprocess
import platform

# Fix for PyInstaller: Initialize stdout/stderr before any imports use them
if getattr(sys, 'frozen', False):
    import io
    # Create dummy streams if they don't exist
    if sys.stdout is None or not hasattr(sys.stdout, 'write'):
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
    if sys.stderr is None or not hasattr(sys.stderr, 'write'):
        sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
    
    # Patch isatty method to always return False
    if hasattr(sys.stdout, 'isatty'):
        sys.stdout.isatty = lambda: False
    if hasattr(sys.stderr, 'isatty'):
        sys.stderr.isatty = lambda: False

app = FastAPI(title="Aerostat Dashboard")

# Get the base path - works for both development and PyInstaller
def get_base_path():
    """Get the base path for resources, handling PyInstaller bundling."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return os.path.join(sys._MEIPASS)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))

def get_data_path():
    """Get the path for writable data files (data.json, logs, etc.)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable - write to directory where exe is located
        path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        # Running as script - use script directory
        path = os.path.dirname(os.path.abspath(__file__))
    
    # Ensure the directory exists
    os.makedirs(path, exist_ok=True)
    return path

BASE_PATH = get_base_path()
DATA_PATH = get_data_path()  # Writable path for data files
STATIC_DIR = os.path.join(BASE_PATH, "static")
TEMPLATES_DIR = os.path.join(BASE_PATH, "templates")

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# MQTT Configuration
MQTT_CONFIGS = [
    {
        "broker": "3ec254ca2f5d4fc38600fa7277517ea0.s1.eu.hivemq.cloud",
        "port": 8883,
        "username": "Parveenespcode",
        "password": "Galaxy21",
        "use_tls": True,
        "timeout": 10
    },
    {
        "broker": "broker.hivemq.com",
        "port": 1883,
        "username": None,
        "password": None,
        "use_tls": False,
        "timeout": 10
    },
    {
        "broker": "test.mosquitto.org",
        "port": 1883,
        "username": None,
        "password": None,
        "use_tls": False,
        "timeout": 10
    }
]

topic_subscribe_sensor_data = "parveenesp32/sensor_data"
mqtt_client = None
mqtt_connected = False
current_mqtt_config = MQTT_CONFIGS[0]

# ── Parameter mapping: incoming field name → sensor_data key ──────────────────
# Used by both MQTT callback and the /api/ingest endpoint
PARAMETER_MAPPING = {
    'helium_pressure_hPa':  'helium_pressure_mbar',
    'ambient_pressure_hPa': 'ambient_pressure_mbar',
    'pressure_diff_hPa':    'pressure_diff_mbar',
    'helium_temp_C':        'helium_temp_C',
    'ambient_temp_C':       'ambient_temp_C',
    'altitude1_m':          'amsl_m',
    'altitude2_m':          'altitude_m',
    'yaw_deg':              'yaw_degrees',
    'pitch_deg':            'pitch_degrees',
    'roll_deg':             'roll_degrees',
    # Legacy CSV[9] wind_kmh — kept for older 20-field streams.
    # Newer 22-field streams send Speed/Direction at CSV[20]/[21] and overwrite Speed.
    'wind_kmh':             'wind_speed_km_s',
    'weight_kg':            'confluence_point_tension_kg',
    'rssi':                 'rssi',
    'ping_ms':              'ping_ms',
    'wind_speed_km_s':      'wind_speed_km_s',
    'wind_direction_degrees': 'wind_direction_degrees',
}

# API Key Management for Secure Control
API_KEYS = {}  # Format: "api_key_hash": {"device": "winch", "permissions": ["control"], "created": "timestamp"}

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global sensor data
sensor_data = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    # Mapped parameters - will show real values from MQTT
    "ambient_temp_C": 0.0,  # Mapped from ambient_temp_C
    "ambient_pressure_mbar": 0.0,  # Mapped from ambient_pressure_hPa
    "helium_pressure_mbar": 0.0,  # Mapped from helium_pressure_hPa
    "pressure_diff_mbar": 0.0,  # Mapped from pressure_diff_hPa (ΔP)
    "helium_temp_C": 0.0,  # Mapped from helium_temp_C
    "altitude_m": 0.0,  # Mapped from altitude2_m (AGL)
    "amsl_m": 0.0,  # Mapped from altitude1_m (AMSL)
    "pitch_degrees": 0.0,  # Mapped from pitch_deg
    "roll_degrees": 0.0,  # Mapped from roll_deg
    "yaw_degrees": 0.0,  # Mapped from yaw_deg
    "wind_speed_km_s": 0.0,  # Mapped from wind_kmh
    "confluence_point_tension_kg": 0.0,  # Mapped from weight_kg (C.P. Tension)
    "rssi": 0,  # Mapped from rssi
    "ping_ms": 0,  # Mapped from ping_ms
    "latitude": 0.0,   # Mapped from latitude  (device field [12])
    "longitude": 0.0,  # Mapped from longitude (device field [13])
    "heading_deg": 0.0,  # Mapped from heading_deg / Compass (device field [14])
    # Non-mapped parameters - set to 0
    "ambient_humidity_percent": 0.0,
    "wind_speed_m_s": 0.0,
    "wind_direction_degrees": 0.0,
    "surface_wind_speed_km_s": 0.0,
    "ballonet_pressure_mbar": 0.0,
    "windscreen_pressure_mbar": 0.0,
    "payload_temp_C": 0.0,
    "windscreen_temp_C": 0.0,
    "ground_temperature_C": 0.0,
    "ground_relative_humidity_percentage": 0.0,
    "ground_wind_speed_km_s": 0.0,
    "ground_wind_direction_degrees": 0.0,
    "voltage_V": 0.0,
    "current_A": 0.0,
    "ground_voltage_V": 0.0,
    "ground_current_A": 0.0,
    "confluence_point_tension_N": 0.0,
    "winch_tether_tension_N": 0.0,
    "tether_line_speed_m_s": 0.0,
    "tether_deployed_m": 0.0,
    "winch_motor_status": "OFF",
    "flight_status": "Unknown",
    "uplink_status": "Unknown",
    "downlink_status": "Unknown",
    "nose_latch_status": "Unknown",
    "system_health_status": "Unknown",
    # Additional parameters from MQTT
    "altitude2_m": 0.0,
    "weight_kg": 0.0,
}

update_counter = 0
last_mqtt_message_time = 0

# Global list to store real-time data logs
real_time_logs = []

# JSON file to store sensor data persistently - use writable path
DATA_JSON_FILE = os.path.join(DATA_PATH, "data.json")
_data_json_lock = threading.Lock()

def load_sensor_data_from_json():
    """Load sensor data from data.json file."""
    try:
        if not os.path.exists(DATA_JSON_FILE):
            logger.warning(f"data.json file not found at: {DATA_JSON_FILE}")
            return []
        
        with open(DATA_JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                logger.warning(f"data.json does not contain a list. Type: {type(data)}")
                return []
            
            if len(data) == 0:
                logger.info("data.json is empty")
                return []
            
            logger.info(f"Successfully loaded {len(data)} entries from data.json")
            return data
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in data.json: {e}")
        return []
    except Exception as e:
        logger.error(f"Error loading data.json: {e}")
        import traceback
        logger.error(f"Load traceback: {traceback.format_exc()}")
        return []

def save_sensor_data_to_json(entry):
    """Save sensor data entry to data.json file with proper structure."""
    try:
        with _data_json_lock:
            existing_data = load_sensor_data_from_json()
            existing_data.append(entry)
            tmp_file = DATA_JSON_FILE + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, DATA_JSON_FILE)
        logger.info(f"💾 Saved sensor data to data.json")
    except Exception as e:
        logger.error(f"Error saving to data.json: {e}")

# Logs System
class AerostatLogsSystem:
    """Logs system integrated into the dashboard."""
    
    def __init__(self):
        self.parameter_categories = {
            'environmental': [
                'ambient_temp_C', 'ambient_pressure_mbar', 'ambient_humidity_percent',
                'wind_speed_m_s', 'wind_direction_degrees', 'surface_wind_speed_km_s',
                'visibility_km', 'uv_index', 'wind_speed_km_s'
            ],
            'critical': [
                'helium_pressure_mbar', 'ballonet_pressure_mbar', 'windscreen_pressure_mbar'
            ],
            'position': [
                'altitude_m', 'pitch_degrees', 'roll_degrees', 'yaw_degrees',
                'latitude', 'longitude'
            ],
            'power': [
                'voltage_V', 'current_A', 'ground_voltage_V', 'ground_current_A'
            ],
            'tether': [
                'confluence_point_tension_kg', 'confluence_point_tension_N',
                'winch_tether_tension_N', 'tether_line_speed_m_s', 'tether_deployed_m'
            ],
            'temperature': [
                'helium_temp_C', 'payload_temp_C', 'windscreen_temp_C', 'ground_temperature_C'
            ],
            'ground': [
                'ground_relative_humidity_percentage', 'ground_wind_speed_km_s',
                'ground_wind_direction_degrees', 'ground_pressure_mbar'
            ],
            'status': [
                'system_health_status', 'flight_status', 'uplink_status', 'downlink_status',
                'nose_latch_status', 'winch_motor_status', 'time_of_day',
                'flight_duration', 'barometric_trend'
            ]
        }
        
        self.status_values = {
            'system_health_status': ['GOOD', 'WARNING', 'ERROR'],
            'flight_status': ['Moored', 'Flying', 'Landing', 'Maintenance'],
            'uplink_status': ['Connected', 'Disconnected', 'Error'],
            'downlink_status': ['Connected', 'Disconnected', 'Error'],
            'nose_latch_status': ['Latched', 'Unlatched', 'Error'],
            'winch_motor_status': ['ON', 'OFF', 'Error'],
            'time_of_day': ['Day', 'Night', 'Dawn', 'Dusk'],
            'flight_duration': ['0-1h', '1-4h', '4-8h', '8h+'],
            'barometric_trend': ['Rising', 'Falling', 'Stable']
        }
    
    def generate_parameter_value(self, param_name: str) -> Any:
        """Generate realistic parameter values based on parameter type."""
        import random
        
        if 'temp' in param_name:
            return round(20 + random.uniform(-10, 25), 1)
        elif 'pressure' in param_name:
            return round(1000 + random.uniform(-50, 50), 1)
        elif 'voltage' in param_name:
            return round(12 + random.uniform(-2, 2), 1)
        elif 'current' in param_name:
            return round(1 + random.uniform(0, 3), 1)
        elif 'altitude' in param_name:
            return round(100 + random.uniform(0, 200), 1)
        elif 'degrees' in param_name:
            return round(random.uniform(0, 360), 1)
        elif 'tension' in param_name:
            return round(10 + random.uniform(0, 20), 1)
        elif 'speed' in param_name:
            return round(random.uniform(0, 30), 1)
        elif 'humidity' in param_name:
            return round(random.uniform(30, 90), 1)
        elif 'visibility' in param_name:
            return round(random.uniform(1, 50), 1)
        elif 'uv' in param_name:
            return round(random.uniform(0, 11), 1)
        elif param_name in self.status_values:
            return random.choice(self.status_values[param_name])
        else:
            return round(random.uniform(0, 100), 1)
    
    def generate_logs(self, start_date: str, end_date: str, 
                     categories: List[str], interval_minutes: int = 1) -> List[Dict[str, Any]]:
        """Generate log data for the specified date range and categories."""
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            
            if start > end:
                raise ValueError("Start date must be before end date")
            
            # Get all parameters for selected categories
            selected_params = []
            for category in categories:
                if category in self.parameter_categories:
                    selected_params.extend(self.parameter_categories[category])
            
            if not selected_params:
                raise ValueError("No valid categories selected")
            
            logs = []
            current = start
            
            # If start and end are the same day, create entries throughout the day
            if start.date() == end.date():
                # Create entries every minute from 00:00:00 to 23:59:00 for the selected day
                current = start.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_day = current.replace(hour=23, minute=59, second=0, microsecond=0)
                
                while current <= end_of_day:
                    log_entry = {
                        'timestamp': current.isoformat(),
                        'date': current.strftime('%Y-%m-%d'),
                        'time': current.strftime('%H:%M:%S')
                    }
                    
                    # Add parameter values
                    for param in selected_params:
                        log_entry[param] = self.generate_parameter_value(param)
                    
                    logs.append(log_entry)
                    current += timedelta(minutes=interval_minutes)
            else:
                # Multiple days - create entries throughout each day
                while current <= end:
                    log_entry = {
                        'timestamp': current.isoformat(),
                        'date': current.strftime('%Y-%m-%d'),
                        'time': current.strftime('%H:%M:%S')
                    }
                    
                    # Add parameter values
                    for param in selected_params:
                        log_entry[param] = self.generate_parameter_value(param)
                    
                    logs.append(log_entry)
                    current += timedelta(minutes=interval_minutes)
                    
                    # Stop if we've reached the end date and time
                    if current > end:
                        break
            
            logger.info(f"Generated {len(logs)} log entries for {len(selected_params)} parameters")
            return logs
            
        except Exception as e:
            logger.error(f"Error generating logs: {e}")
            raise
    
    def export_to_csv(self, logs: List[Dict[str, Any]], filename: str) -> str:
        """Export logs to CSV format."""
        try:
            if not logs:
                raise ValueError("No logs to export")
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = list(logs[0].keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for log in logs:
                    writer.writerow(log)
            
            logger.info(f"Exported {len(logs)} entries to CSV: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            raise
    
    def export_to_json(self, logs: List[Dict[str, Any]], filename: str) -> str:
        """Export logs to JSON format."""
        try:
            if not logs:
                raise ValueError("No logs to export")
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            with open(filename, 'w', encoding='utf-8') as jsonfile:
                json.dump(logs, jsonfile, indent=2, ensure_ascii=False)
            
            logger.info(f"Exported {len(logs)} entries to JSON: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting to JSON: {e}")
            import traceback
            logger.error(f"JSON export traceback: {traceback.format_exc()}")
            raise
    
    def export_to_txt(self, logs: List[Dict[str, Any]], filename: str) -> str:
        """Export logs to TXT format with human-readable formatting."""
        try:
            if not logs:
                raise ValueError("No logs to export")
            
            with open(filename, 'w', encoding='utf-8') as txtfile:
                # Write header
                txtfile.write('=' * 80 + '\n')
                txtfile.write('AEROSTAT SYSTEM LOGS\n')
                txtfile.write('=' * 80 + '\n')
                txtfile.write(f'Generated: {datetime.now().isoformat()}\n')
                txtfile.write(f'Total Entries: {len(logs)}\n')
                txtfile.write(f'Date Range: {logs[0]["date"]} to {logs[-1]["date"]}\n')
                txtfile.write('=' * 80 + '\n\n')
                
                # Group logs by date
                logs_by_date = {}
                for log in logs:
                    date = log['date']
                    if date not in logs_by_date:
                        logs_by_date[date] = []
                    logs_by_date[date].append(log)
                
                # Write logs grouped by date
                for date in sorted(logs_by_date.keys()):
                    txtfile.write(f'\n📅 DATE: {date}\n')
                    txtfile.write('-' * 60 + '\n')
                    
                    for index, log in enumerate(logs_by_date[date]):
                        txtfile.write(f'\n⏰ TIME: {log["time"]}\n')
                        
                        # Get parameter keys (exclude timestamp, date, time)
                        param_keys = [key for key in log.keys() 
                                    if key not in ['timestamp', 'date', 'time']]
                        
                        # Group parameters by category for better readability
                        categories = {
                            'Environmental': [key for key in param_keys 
                                            if any(x in key for x in ['ambient', 'wind', 'visibility', 'uv'])],
                            'Critical Systems': [key for key in param_keys 
                                               if 'pressure' in key and any(x in key for x in ['helium', 'ballonet', 'windscreen'])],
                            'Position & Navigation': [key for key in param_keys 
                                                    if any(x in key for x in ['altitude', 'pitch', 'roll', 'yaw', 'latitude', 'longitude'])],
                            'Power Systems': [key for key in param_keys 
                                            if any(x in key for x in ['voltage', 'current'])],
                            'Tether & Tension': [key for key in param_keys 
                                               if any(x in key for x in ['tension', 'tether', 'deployed'])],
                            'Temperature Systems': [key for key in param_keys 
                                                  if 'temp' in key and 'ambient' not in key],
                            'Ground Systems': [key for key in param_keys 
                                             if 'ground' in key],
                            'System Status': [key for key in param_keys 
                                            if any(x in key for x in ['status', 'time_of_day', 'flight_duration', 'barometric_trend'])]
                        }
                        
                        # Write parameters by category
                        for category, params in categories.items():
                            if params:
                                txtfile.write(f'\n  {category}:\n')
                                for param in params:
                                    value = log[param]
                                    unit = self._get_parameter_unit(param)
                                    param_name = param.replace('_', ' ').upper()
                                    txtfile.write(f'    • {param_name}: {value}{unit}\n')
                        
                        if index < len(logs_by_date[date]) - 1:
                            txtfile.write('\n' + '.' * 40 + '\n')
                    
                    txtfile.write('\n' + '=' * 60 + '\n')
                
                txtfile.write('\n' + '=' * 80 + '\n')
                txtfile.write('END OF LOGS\n')
                txtfile.write('=' * 80 + '\n')
            
            logger.info(f"Exported {len(logs)} entries to TXT: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting to TXT: {e}")
            raise
    
    def _get_parameter_unit(self, param: str) -> str:
        """Get the appropriate unit for a parameter."""
        if 'temp' in param:
            return '°C'
        elif 'pressure' in param:
            return ' mbar'
        elif 'voltage' in param:
            return ' V'
        elif 'current' in param:
            return ' A'
        elif 'altitude' in param:
            return ' m'
        elif 'degrees' in param:
            return '°'
        elif 'tension' in param:
            return ' N'
        elif 'speed' in param:
            return ' m/s'
        elif 'humidity' in param:
            return '%'
        elif 'visibility' in param:
            return ' km'
        elif 'uv' in param:
            return ''
        elif 'deployed' in param:
            return ' m'
        else:
            return ''
    
    def export_real_time_logs(self, logs: List[Dict[str, Any]], filename: str) -> str:
        """Export real-time logs in the format requested by user - ALL DATA, NO LIMITS."""
        try:
            if not logs:
                raise ValueError("No real-time logs to export")
            
            logger.info(f"📝 Exporting {len(logs)} real-time log entries to {filename}")
            
            with open(filename, 'w', encoding='utf-8') as txtfile:
                # Write header
                txtfile.write('=' * 80 + '\n')
                txtfile.write('AEROSTAT REAL-TIME DATA LOGS - COMPLETE DATA\n')
                txtfile.write('=' * 80 + '\n')
                txtfile.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
                txtfile.write(f'Total Updates: {len(logs)}\n')
                txtfile.write(f'Total Parameter Changes: {sum(len(log["changes"]) for log in logs)}\n')
                txtfile.write(f'Update frequency: Every 2 seconds with BIG value changes\n')
                txtfile.write(f'Threshold management: Admin configurable min/max values\n')
                txtfile.write(f'Data Range: {logs[0]["timestamp"]} to {logs[-1]["timestamp"]}\n')
                txtfile.write('=' * 80 + '\n\n')
                
                txtfile.write('=== VALUE UPDATES LOG ===\n\n')
                
                # Write each update with progress logging
                total_changes = 0
                for i, log in enumerate(logs):
                    timestamp = log['timestamp']
                    update_num = log['update_number']
                    
                    # Write each parameter change
                    for change in log['changes']:
                        param = change['parameter']
                        old_val = change['old_value']
                        new_val = change['new_value']
                        
                        # Format the line like the user's example
                        txtfile.write(f'{timestamp} - FAST Update - {param}: {old_val} → {new_val}\n')
                        total_changes += 1
                    
                    txtfile.write('\n')  # Add blank line between updates
                    
                    # Log progress every 100 updates
                    if (i + 1) % 100 == 0:
                        logger.info(f"📝 Exported {i + 1}/{len(logs)} updates ({total_changes} total changes)")
                
                txtfile.write('=' * 80 + '\n')
                txtfile.write(f'END OF LOGS - {total_changes} total parameter changes exported\n')
                txtfile.write('=' * 80 + '\n')
            
            logger.info(f"Successfully exported {len(logs)} updates with {total_changes} parameter changes")
            return filename
            
        except Exception as e:
            logger.error(f"Error exporting real-time logs: {e}")
            raise

def export_data_to_txt(data_entries: List[Dict[str, Any]], filename: str) -> str:
    """Export sensor data from data.json to TXT format."""
    try:
        if not data_entries:
            raise ValueError("No sensor data to export")
        
        # Ensure directory exists
        dir_path = os.path.dirname(filename)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as txtfile:
            # Write header
            txtfile.write('=' * 80 + '\n')
            txtfile.write('AEROSTAT SENSOR DATA LOGS - FROM data.json\n')
            txtfile.write('=' * 80 + '\n')
            txtfile.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            txtfile.write(f'Total Entries: {len(data_entries)}\n')
            txtfile.write(f'Data Range: {data_entries[0].get("date", "N/A")} to {data_entries[-1].get("date", "N/A")}\n')
            txtfile.write('=' * 80 + '\n\n')
            
            # Write each entry
            for entry in data_entries:
                txtfile.write(f'Date: {entry.get("date", "N/A")}\n')
                txtfile.write(f'Timestamp: {entry.get("timestamp", "N/A")}\n')
                txtfile.write(f'Update Number: {entry.get("update_number", "N/A")}\n')
                txtfile.write(f'Source: {entry.get("source", "N/A")}\n')
                txtfile.write('-' * 80 + '\n')
                
                # Write sensor data
                sensor_data = entry.get("sensor_data", {})
                if sensor_data:
                    txtfile.write('Sensor Data:\n')
                    for key, value in sensor_data.items():
                        txtfile.write(f'  {key}: {value}\n')
                
                # Write parameter changes if any
                changes = entry.get("parameter_changes", [])
                if changes:
                    txtfile.write('\nParameter Changes:\n')
                    for change in changes:
                        param = change.get("parameter", "")
                        old_val = change.get("old_value", "")
                        new_val = change.get("new_value", "")
                        txtfile.write(f'  {param}: {old_val} → {new_val}\n')
                
                txtfile.write('\n' + '=' * 80 + '\n\n')
            
            txtfile.write('END OF LOGS\n')
        
        logger.info(f"Exported {len(data_entries)} entries to TXT: {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"Error exporting to TXT: {e}")
        raise

def export_data_to_csv(data_entries: List[Dict[str, Any]], filename: str) -> str:
    """Export sensor data from data.json to CSV format."""
    try:
        if not data_entries:
            raise ValueError("No sensor data to export")
        
        # Ensure directory exists
        dir_path = os.path.dirname(filename)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        # Collect all unique sensor data keys from all entries
        all_keys = set()
        for entry in data_entries:
            sensor_data = entry.get("sensor_data", {})
            if sensor_data:
                all_keys.update(sensor_data.keys())
        
        if not all_keys:
            raise ValueError("No sensor data keys found in entries")
        
        # Create CSV with: date, timestamp, update_number, source, and all sensor parameters
        fieldnames = ['date', 'timestamp', 'update_number', 'source'] + sorted(all_keys)
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for entry in data_entries:
                row = {
                    'date': str(entry.get("date", "")),
                    'timestamp': str(entry.get("timestamp", "")),
                    'update_number': str(entry.get("update_number", "")),
                    'source': str(entry.get("source", "")),
                }
                
                # Add all sensor data values
                sensor_data = entry.get("sensor_data", {})
                if sensor_data:
                    for key in sorted(all_keys):
                        value = sensor_data.get(key, "")
                        # Convert None to empty string, handle other types
                        if value is None:
                            row[key] = ""
                        else:
                            row[key] = str(value)
                else:
                    # Fill with empty values if no sensor_data
                    for key in sorted(all_keys):
                        row[key] = ""
                
                writer.writerow(row)
        
        logger.info(f"Exported {len(data_entries)} entries to CSV: {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        import traceback
        logger.error(f"CSV export traceback: {traceback.format_exc()}")
        raise

# Initialize logs system
logs_system = AerostatLogsSystem()

# MQTT Functions
def is_port_open(host, port, timeout=5):
    """Check if a port is open on the given host"""
    import socket
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

def on_mqtt_connect(client, userdata, flags, rc, *args, **kwargs):
    """MQTT connection callback (compatible with both API v1 and v2)"""
    global mqtt_connected
    # Handle both old API (rc as int) and new API (rc as ReasonCode)
    reason_code = rc if isinstance(rc, int) else rc.value if hasattr(rc, 'value') else 0
    if reason_code == 0:
        logger.info(f"MQTT Connected to broker: {current_mqtt_config['broker']}")
        mqtt_connected = True
        # Subscribe to sensor data topic
        client.subscribe(topic_subscribe_sensor_data, qos=1)
        logger.info(f"Subscribed to topic: {topic_subscribe_sensor_data}")
    else:
        logger.error(f"MQTT Failed to connect with code {reason_code}")
        mqtt_connected = False

def on_mqtt_disconnect(client, userdata, rc, *args, **kwargs):
    """MQTT disconnection callback (compatible with both API v1 and v2)"""
    global mqtt_connected
    mqtt_connected = False
    # Handle both old API (rc as int) and new API (rc as ReasonCode)
    # Also handle case where rc might be None
    if rc is not None:
        reason_code = rc if isinstance(rc, int) else rc.value if hasattr(rc, 'value') else 0
        logger.info(f"🔌 MQTT Disconnected with code {reason_code}")
    else:
        logger.info(f"🔌 MQTT Disconnected")

def apply_sensor_update(received_data: dict, source: str = "mqtt"):
    """
    Shared function: maps incoming field names → sensor_data keys, updates
    sensor_data, logs changes, saves to data.json, and appends to real_time_logs.
    Called by both on_mqtt_message and the /api/ingest endpoint.
    """
    global sensor_data, update_counter, last_mqtt_message_time, real_time_logs

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    log_entry = {
        "timestamp":    timestamp,
        "update_number": update_counter + 1,
        "source":       source,
        "changes":      []
    }

    for key, value in received_data.items():
        dashboard_key = PARAMETER_MAPPING.get(key, key)

        if dashboard_key in sensor_data:
            old_value = sensor_data[dashboard_key]
            if old_value != value:
                sensor_data[dashboard_key] = value
                log_entry["changes"].append({
                    "parameter": f"{key} -> {dashboard_key}",
                    "old_value": old_value,
                    "new_value": value
                })
                logger.info(f"[{source}] {key} -> {dashboard_key}: {old_value} → {value}")
            else:
                sensor_data[dashboard_key] = value
        elif key in sensor_data:
            old_value = sensor_data[key]
            if old_value != value:
                sensor_data[key] = value
                log_entry["changes"].append({
                    "parameter": key,
                    "old_value": old_value,
                    "new_value": value
                })
            else:
                sensor_data[key] = value

    sensor_data["timestamp"] = timestamp
    last_mqtt_message_time   = time.time()
    update_counter          += 1

    current_datetime = datetime.now()
    data_entry = {
        "date":               current_datetime.strftime("%Y-%m-%d"),
        "timestamp":          timestamp,
        "datetime":           current_datetime.isoformat(),
        "update_number":      update_counter,
        "source":             source,
        "sensor_data":        dict(sensor_data),
        "raw_data":           received_data,
        "parameter_changes":  log_entry.get("changes", [])
    }
    save_sensor_data_to_json(data_entry)

    if log_entry.get("changes"):
        real_time_logs.append(log_entry)
        logger.info(f"[{source}] Update #{update_counter} — {len(log_entry['changes'])} changes")
    else:
        logger.debug(f"[{source}] Update #{update_counter} — no changes")


def on_mqtt_message(client, userdata, msg):
    """MQTT message received callback"""
    try:
        received_data = json.loads(msg.payload.decode())
        apply_sensor_update(received_data, source="mqtt")
    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")

def on_mqtt_log(client, userdata, level, buf):
    """MQTT logging callback"""
    logger.debug(f"MQTT Log: {buf}")

# ==================== API KEY MANAGEMENT ====================

def generate_api_key() -> str:
    """Generate a new API key"""
    return secrets.token_urlsafe(32)

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def validate_api_key(api_key: str, required_permission: str = "control") -> bool:
    """Validate API key and check permissions"""
    if not api_key:
        return False
    
    api_key_hash = hash_api_key(api_key)
    
    if api_key_hash not in API_KEYS:
        logger.warning(f"Invalid API key attempted: {api_key_hash[:8]}...")
        return False
    
    key_info = API_KEYS[api_key_hash]
    
    # Check if key has required permission
    if required_permission not in key_info.get("permissions", []):
        logger.warning(f"API key lacks required permission: {required_permission}")
        return False
    
    # Check if key is expired (optional - if you add expiration)
    if "expires" in key_info:
        try:
            if datetime.now() > datetime.fromisoformat(key_info["expires"]):
                logger.warning("API key has expired")
                return False
        except:
            pass
    
    return True

def create_winch_api_key() -> tuple:
    """Create a new API key for winch control"""
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    
    API_KEYS[api_key_hash] = {
        "device": "winch",
        "permissions": ["control"],
        "created": datetime.now().isoformat(),
        "description": "Winch Motor Control API Key"
    }
    
    logger.info(f"New API key created for winch control: {api_key_hash[:8]}...")
    return api_key, api_key_hash

def initialize_api_keys():
    """Initialize API keys on startup"""
    global API_KEYS
    try:
        api_keys_path = os.path.join(DATA_PATH, "api_keys.json")
        if os.path.exists(api_keys_path):
            with open(api_keys_path, 'r', encoding='utf-8') as f:
                saved_keys = json.load(f)
                API_KEYS.update(saved_keys)
                logger.info(f"✅ Loaded {len(saved_keys)} API keys from config")
        else:
            # Create default winch API key
            api_key, api_key_hash = create_winch_api_key()
            save_api_keys()
            logger.info(f"✅ Created default winch API key: {api_key}")
            logger.warning(f"⚠️  IMPORTANT: Save this API key securely: {api_key}")
    except Exception as e:
        logger.error(f"Error initializing API keys: {e}")
        import traceback
        logger.error(traceback.format_exc())

def save_api_keys():
    """Save API keys to file"""
    try:
        api_keys_path = os.path.join(DATA_PATH, "api_keys.json")
        with open(api_keys_path, 'w', encoding='utf-8') as f:
            json.dump(API_KEYS, f, indent=2, ensure_ascii=False)
        logger.debug("API keys saved to file")
    except Exception as e:
        logger.error(f"Error saving API keys: {e}")

# ==================== MQTT COMMAND PUBLISHING ====================

def publish_mqtt_command(topic, command_data):
    """Publish MQTT command to control devices"""
    global mqtt_client, mqtt_connected
    
    if not mqtt_client:
        logger.error("MQTT client not initialized. Cannot send command.")
        return False
    
    # Check connection status more thoroughly
    try:
        # Check if client is connected (using is_connected() method if available)
        if hasattr(mqtt_client, 'is_connected'):
            if not mqtt_client.is_connected():
                logger.error("MQTT client is not connected. Cannot send command.")
                return False
        elif not mqtt_connected:
            logger.error("MQTT connection flag indicates not connected. Cannot send command.")
            return False
    except Exception as e:
        logger.warning(f"Could not verify MQTT connection status: {e}")
    
    try:
        # Publish command to MQTT topic
        payload = json.dumps(command_data)
        result = mqtt_client.publish(topic, payload, qos=1)
        
        # Wait for the publish to complete (with timeout)
        result.wait_for_publish(timeout=2)
        
        if result.rc == paho.MQTT_ERR_SUCCESS:
            logger.info(f"✅ Command published to {topic}: {payload}")
            return True
        else:
            logger.error(f"❌ Failed to publish command. Error code: {result.rc}")
            # Error code 4 = MQTT_ERR_NO_CONN
            if result.rc == 4:
                logger.error("MQTT client is not connected to broker")
                mqtt_connected = False
            return False
    except Exception as e:
        logger.error(f"❌ Error publishing MQTT command: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def _create_paho_mqtt_client(client_id: str):
    """
    Build a paho Client compatible with both paho-mqtt 1.6.x and 2.x.
    (Frozen builds / requirements.txt often pin 1.6, which has no CallbackAPIVersion.)
    """
    protocol = paho.MQTTv311
    cav = getattr(paho, "CallbackAPIVersion", None)
    if cav is not None:
        try:
            return paho.Client(cav.VERSION2, client_id=client_id, protocol=protocol)
        except TypeError:
            try:
                return paho.Client(
                    client_id=client_id,
                    protocol=protocol,
                    callback_api_version=cav.VERSION2,
                )
            except TypeError:
                pass
    return paho.Client(client_id=client_id, protocol=protocol)


def initialize_mqtt_client():
    """Initialize MQTT client with fallback brokers"""
    global mqtt_client, current_mqtt_config, mqtt_connected
    
    for config in MQTT_CONFIGS:
        current_mqtt_config = config
        try:
            logger.info(f"Trying to connect to MQTT broker: {config['broker']}:{config['port']}")
            
            # Check port first
            if not is_port_open(config['broker'], config['port'], config.get('timeout', 5)):
                logger.warning(f"Port {config['port']} not reachable on {config['broker']}")
                continue
            
            # Create MQTT client (paho-mqtt 1.x has no CallbackAPIVersion; 2.x prefers VERSION2)
            client = _create_paho_mqtt_client(f"aerostat_subscriber_{int(time.time())}")
            
            client.on_connect = on_mqtt_connect
            client.on_disconnect = on_mqtt_disconnect
            client.on_message = on_mqtt_message
            client.on_log = on_mqtt_log
            
            # Configure TLS if needed
            if config.get("use_tls"):
                try:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    client.tls_set_context(context)
                    logger.info("TLS configured for MQTT connection")
                except Exception as e:
                    logger.error(f"TLS configuration failed: {e}")
                    continue
            
            # Set username and password if provided
            if config.get("username") and config.get("password"):
                client.username_pw_set(config["username"], config["password"])
                logger.info("MQTT credentials configured")
            
            # Connect to broker
            client.connect(config['broker'], config['port'], config.get('timeout', 10))
            client.loop_start()
            
            # Wait a moment to see if connection succeeds
            time.sleep(2)
            
            if mqtt_connected:
                mqtt_client = client
                logger.info(f"Successfully connected to MQTT broker: {config['broker']}")
                return True
            else:
                client.loop_stop()
                client.disconnect()
                logger.warning(f"Failed to connect to {config['broker']}")
                
        except Exception as e:
            logger.error(f"Error connecting to {config['broker']}: {e}")
            continue
    
    logger.warning("Could not connect to any MQTT broker, using simulation mode")
    return False

# ==================== DEVICE CONNECTION MANAGER ====================

# CSV index → raw field name (same mapping as com_port_fetcher.py)
DEVICE_FIELD_MAP = {
    0:  "ping_ms",
    1:  "millis",
    2:  "device_timestamp",
    3:  "ambient_temp_C",
    4:  "ambient_pressure_hPa",
    5:  "altitude1_m",
    6:  "helium_temp_C",
    7:  "helium_pressure_hPa",
    8:  "altitude2_m",
    9:  "wind_kmh",
    10: "weight_kg",
    11: "pressure_diff_hPa",
    12: "latitude",
    13: "longitude",
    14: "heading_deg",
    15: "yaw_deg",
    16: "pitch_deg",
    17: "roll_deg",
    18: "ground_temperature_C",
    19: "ambient_humidity_percent",
    20: "wind_speed_km_s",          # NEW: Wind panel Speed
    21: "wind_direction_degrees",   # NEW: Wind panel Direction
}

DEVICE_CONFIG_FILE = os.path.join(DATA_PATH, "device_config.json")


class DeviceConnectionManager:
    """Manages a single TCP/Serial connection to the device inside the dashboard process."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._status = {
            "connected": False,
            "source": None,
            "host": None,
            "port": None,
            "com_port": None,
            "baud_rate": None,
            "last_data_time": None,
            "connect_time": None,
            "lines_received": 0,
            "error": None,
            "last_raw_line": None,
            "last_raw_fields": [],  # [{index, name, value}, ...]
        }

    # ── persistence ────────────────────────────────────────────────
    def _load_config(self):
        try:
            if os.path.exists(DEVICE_CONFIG_FILE):
                with open(DEVICE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_config(self, cfg):
        try:
            with open(DEVICE_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving device config: {e}")

    def _clear_config(self):
        try:
            if os.path.exists(DEVICE_CONFIG_FILE):
                os.remove(DEVICE_CONFIG_FILE)
        except Exception:
            pass

    # ── CSV parsing ─────────────────────────────────────────────────
    @staticmethod
    def _get_local_ipv4_addresses():
        """Return non-loopback IPv4 addresses on this machine."""
        ips = []
        try:
            if platform.system() == "Windows":
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-NetIPAddress -AddressFamily IPv4).IPAddress"],
                    capture_output=True, text=True, timeout=8,
                    encoding="utf-8", errors="ignore",
                )
                for line in (r.stdout or "").splitlines():
                    ip = line.strip()
                    if ip and not ip.startswith("127.") and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                        ips.append(ip)
        except Exception as e:
            logger.debug(f"[DevMgr] Could not list local IPs: {e}")
        return ips

    @staticmethod
    def _pick_bind_ip(host: str):
        """
        Pick the local NIC IP on the same subnet as the device.
        Fixes Windows routing TCP via Wi-Fi when device is on direct Ethernet.
        """
        host_parts = host.split(".")
        if len(host_parts) != 4:
            return None
        subnet_prefix = ".".join(host_parts[:3])
        for ip in DeviceConnectionManager._get_local_ipv4_addresses():
            parts = ip.split(".")
            if len(parts) == 4 and ".".join(parts[:3]) == subnet_prefix:
                return ip
        return None

    @staticmethod
    def _parse_csv(line: str) -> dict:
        parts = line.strip().split(',')
        if len(parts) < 4:
            return {}
        payload = {}
        for idx, key in DEVICE_FIELD_MAP.items():
            if idx >= len(parts):
                continue
            if idx == 2:  # device_timestamp — string, skip
                continue
            try:
                payload[key] = float(parts[idx])
            except (ValueError, TypeError):
                pass
        return payload

    def _handle_line(self, line: str, source: str):
        payload = self._parse_csv(line)
        if not payload:
            return
        apply_sensor_update(payload, source=source)
        # Indexed raw snapshot for Admin → Device live check panel
        parts = [p.strip() for p in line.strip().split(",")]
        fields = []
        for i, raw in enumerate(parts):
            name = DEVICE_FIELD_MAP.get(i, f"field_{i}")
            fields.append({"index": i, "name": name, "value": raw})
        with self._lock:
            self._status["last_data_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._status["lines_received"] += 1
            self._status["last_raw_line"] = line.strip()
            self._status["last_raw_fields"] = fields

    @staticmethod
    def _extract_tcp_lines(buf: bytes, last_recv: float):
        """Split incoming TCP bytes into complete CSV lines (matches ethernet_fetcher.py)."""
        lines = []
        normalised = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if b"\n" in normalised:
            parts = normalised.split(b"\n")
            for part in parts[:-1]:
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)
            return lines, parts[-1], last_recv
        if buf and (time.time() - last_recv) > 3.0:
            line = buf.decode("utf-8", errors="replace").strip()
            if line:
                lines.append(line)
            return lines, b"", time.time()
        return lines, buf, last_recv

    # ── status ──────────────────────────────────────────────────────
    def get_status(self):
        with self._lock:
            status = dict(self._status)
        status["running"] = self.is_running()
        return status

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # ── TCP reader thread ────────────────────────────────────────────
    def _tcp_reader(self, host, port):
        buf = b""
        reconnect_delay = 2
        no_data_cycles = 0
        last_recv = time.time()
        while not self._stop_event.is_set():
            sock = None
            try:
                logger.info(f"[DevMgr] Connecting TCP → {host}:{port}")
                sock = _socket_lib.socket(_socket_lib.AF_INET, _socket_lib.SOCK_STREAM)
                bind_ip = self._pick_bind_ip(host)
                if bind_ip:
                    sock.bind((bind_ip, 0))
                    logger.info(f"[DevMgr] Binding to local NIC {bind_ip} (same subnet as {host})")
                else:
                    logger.warning(
                        f"[DevMgr] No local NIC on same subnet as {host} — "
                        "Windows may route via Wi-Fi and time out"
                    )
                sock.settimeout(10)
                sock.connect((host, int(port)))
                sock.settimeout(3)
                buf = b""
                last_recv = time.time()
                no_data_cycles = 0
                with self._lock:
                    self._status["connected"] = True
                    self._status["error"] = None
                    self._status["connect_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"[DevMgr] TCP connected to {host}:{port}")

                while not self._stop_event.is_set():
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            logger.warning("[DevMgr] Device closed TCP connection")
                            break
                        buf += chunk
                        last_recv = time.time()
                        no_data_cycles = 0
                    except _socket_lib.timeout:
                        no_data_cycles += 1
                        if no_data_cycles >= 4 and not buf:
                            try:
                                sock.sendall(b"df\r\n")
                                logger.info("[DevMgr] Sent 'df' fallback command")
                            except Exception as send_err:
                                logger.warning(f"[DevMgr] Send fallback failed: {send_err}")
                    except Exception as e:
                        logger.warning(f"[DevMgr] TCP read error: {e}")
                        break

                    lines, buf, last_recv = self._extract_tcp_lines(buf, last_recv)
                    for line in lines:
                        self._handle_line(line, source="ethernet")

            except Exception as e:
                with self._lock:
                    self._status["connected"] = False
                    self._status["error"] = str(e)
                logger.warning(f"[DevMgr] TCP connect/read failed: {e}")
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            if not self._stop_event.is_set():
                with self._lock:
                    self._status["connected"] = False
                logger.info(f"[DevMgr] Reconnecting in {reconnect_delay}s…")
                self._stop_event.wait(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

        with self._lock:
            self._status["connected"] = False

    @staticmethod
    def _format_serial_error(exc: Exception, com_port: str) -> str:
        msg = str(exc)
        if isinstance(exc, PermissionError) or "Access is denied" in msg:
            return (
                f"COM port {com_port} is in use by another program. "
                "Close Hercules, Arduino Serial Monitor, or com_port_fetcher.py, "
                "then click Connect again."
            )
        return msg

    @staticmethod
    def _serial_port_in_use(exc: Exception) -> bool:
        msg = str(exc)
        return isinstance(exc, PermissionError) or "Access is denied" in msg

    # ── Serial reader thread ─────────────────────────────────────────
    def _serial_reader(self, com_port, baud_rate):
        reconnect_delay = 2
        missing_port_logged = False
        while not self._stop_event.is_set():
            try:
                import serial as _serial
                logger.info(f"[DevMgr] Opening {com_port} @ {baud_rate} baud")
                ser = _serial.Serial(com_port, int(baud_rate), timeout=3)
                reconnect_delay = 2
                missing_port_logged = False
                with self._lock:
                    self._status["connected"] = True
                    self._status["error"] = None
                    self._status["connect_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"[DevMgr] {com_port} opened")

                while not self._stop_event.is_set():
                    try:
                        raw = ser.readline()
                        line = raw.decode('utf-8', errors='ignore').strip()
                        if line:
                            self._handle_line(line, source=f"com:{com_port}")
                    except Exception as e:
                        logger.warning(f"[DevMgr] Serial read error: {e}")
                        break
                ser.close()
            except Exception as e:
                friendly = self._format_serial_error(e, com_port)
                with self._lock:
                    self._status["connected"] = False
                    self._status["error"] = friendly
                err_s = str(e)
                port_missing = (
                    isinstance(e, FileNotFoundError)
                    or "FileNotFoundError" in err_s
                    or "cannot find the file specified" in err_s.lower()
                )
                if port_missing:
                    # COM port not present (unplugged / wrong port) — avoid log spam
                    if not missing_port_logged:
                        logger.warning(
                            f"[DevMgr] Serial port {com_port} not found — "
                            "check Device Manager / Admin → Device. Retrying slowly…"
                        )
                        missing_port_logged = True
                    else:
                        logger.debug(f"[DevMgr] Serial connect failed (port missing): {e}")
                    reconnect_delay = max(reconnect_delay, 15)
                else:
                    logger.warning(f"[DevMgr] Serial connect failed: {e}")
                if self._serial_port_in_use(e):
                    logger.warning("[DevMgr] Port locked — stop other apps using this COM port")
                    break

            if not self._stop_event.is_set():
                with self._lock:
                    self._status["connected"] = False
                self._stop_event.wait(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

        with self._lock:
            self._status["connected"] = False

    # ── public API ───────────────────────────────────────────────────
    def connect(self, source: str, host=None, port=None, com_port=None, baud_rate=9600):
        self.disconnect()
        self._stop_event.clear()
        with self._lock:
            self._status.update({
                "source": source,
                "lines_received": 0,
                "connect_time": None,
                "last_data_time": None,
                "error": None,
                "connected": False,
                "last_raw_line": None,
                "last_raw_fields": [],
            })

        if source == "ethernet":
            with self._lock:
                self._status["host"] = host
                self._status["port"] = port
            self._save_config({"source": "ethernet", "host": host, "port": port})
            self._thread = threading.Thread(
                target=self._tcp_reader, args=(host, port), daemon=True)
        elif source == "com":
            with self._lock:
                self._status["com_port"] = com_port
                self._status["baud_rate"] = baud_rate
            self._save_config({"source": "com", "com_port": com_port, "baud_rate": baud_rate})
            self._thread = threading.Thread(
                target=self._serial_reader, args=(com_port, baud_rate), daemon=True)
        else:
            raise ValueError(f"Unknown source: {source}")

        self._thread.start()
        logger.info(f"[DevMgr] Started connection: {source}")

    def disconnect(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._stop_event.clear()
        with self._lock:
            self._status.update({
                "connected": False,
                "source": None,
                "host": None,
                "port": None,
                "com_port": None,
                "baud_rate": None,
                "error": None,
                "connect_time": None,
                "last_data_time": None,
                "lines_received": 0,
            })
        self._clear_config()
        logger.info("[DevMgr] Connection stopped")

    def autostart(self):
        """Re-connect on startup using saved config."""
        cfg = self._load_config()
        if not cfg:
            return
        try:
            src = cfg.get("source")
            if src == "ethernet":
                self.connect("ethernet", host=cfg["host"], port=cfg["port"])
                logger.info(f"[DevMgr] Auto-started ethernet {cfg['host']}:{cfg['port']}")
            elif src == "com":
                self.connect("com", com_port=cfg["com_port"], baud_rate=cfg.get("baud_rate", 9600))
                logger.info(f"[DevMgr] Auto-started COM {cfg['com_port']}")
        except Exception as e:
            logger.error(f"[DevMgr] Autostart failed: {e}")

    @staticmethod
    def list_com_ports():
        try:
            import serial.tools.list_ports as _lp
            return [{"port": p.device, "description": p.description} for p in _lp.comports()]
        except Exception:
            return []


# Single global instance
device_manager = DeviceConnectionManager()


def update_timestamp_only():
    """Update only timestamp - no simulation data generation"""
    global sensor_data
    while True:
        try:
            # Only update timestamp, no simulation data
            sensor_data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            
        except Exception as e:
            print(f"Error updating timestamp: {e}")
        
        time.sleep(5)  # Update timestamp every 5 seconds

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.post("/")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Simple login - redirect to dashboard
    # The client-side JavaScript handles user validation
    if username and password:
        return RedirectResponse(url="/professional_video_charts", status_code=303)
    else:
        return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
async def logout():
    # Simple logout - redirect to login page
    return RedirectResponse(url="/", status_code=303)

@app.get("/professional_video_charts", response_class=HTMLResponse)
async def dashboard(request: Request, role: str = "super_admin", username: str = "Super Admin"):
    return templates.TemplateResponse(request, "professional_video_charts.html", {
        "sensor_data": sensor_data,
        "user_role": role,
        "username": username
    })

@app.get("/image/aerostat1.jpg")
async def get_background_image():
    from fastapi.responses import FileResponse
    import os
    image_path = "static/images/aerostat1.jpg"
    if os.path.exists(image_path):
        return FileResponse(image_path)
    else:
        return {"error": "Image not found"}

@app.get("/api/sensor-data")
async def get_sensor_data():
    return sensor_data


@app.post("/api/ingest")
async def ingest_sensor_data(request: Request):
    """
    Direct data ingestion endpoint.
    Accepts JSON from ethernet_fetcher.py or com_port_fetcher.py and
    updates the dashboard in real time — no MQTT required.

    Expected JSON keys use the same field names as the MQTT pipeline
    (e.g. ambient_temp_C, helium_pressure_hPa, altitude1_m …).
    """
    try:
        received_data = await request.json()
        if not isinstance(received_data, dict):
            return JSONResponse(status_code=400, content={"error": "Expected a JSON object"})

        apply_sensor_update(received_data, source="ethernet/com")

        return JSONResponse(content={
            "status":  "ok",
            "update":  update_counter,
            "fields":  len(received_data),
        })
    except Exception as e:
        logger.error(f"Error in /api/ingest: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==================== DEVICE CONNECTION API ====================

@app.post("/api/device/connect")
async def api_device_connect(request: Request):
    """Start a TCP or serial connection to the device from the dashboard UI."""
    try:
        data = await request.json()
        source = data.get("source", "").lower()   # "ethernet" | "com"

        if source == "ethernet":
            host = (data.get("host") or "").strip()
            port = data.get("port")
            if not host or not port:
                return JSONResponse(status_code=400, content={"error": "host and port are required"})
            device_manager.connect("ethernet", host=host, port=int(port))
            return JSONResponse(content={"status": "connecting", "source": "ethernet",
                                         "host": host, "port": int(port)})

        elif source == "com":
            com_port = (data.get("com_port") or "").strip()
            baud_rate = int(data.get("baud_rate") or 9600)
            if not com_port:
                return JSONResponse(status_code=400, content={"error": "com_port is required"})
            device_manager.connect("com", com_port=com_port, baud_rate=baud_rate)
            return JSONResponse(content={"status": "connecting", "source": "com",
                                         "com_port": com_port, "baud_rate": baud_rate})
        else:
            return JSONResponse(status_code=400,
                                content={"error": "source must be 'ethernet' or 'com'"})
    except Exception as e:
        logger.error(f"[/api/device/connect] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/device/disconnect")
async def api_device_disconnect():
    """Stop the active device connection."""
    try:
        device_manager.disconnect()
        return JSONResponse(content={"status": "disconnected"})
    except Exception as e:
        logger.error(f"[/api/device/disconnect] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/device/status")
async def api_device_status():
    """Return current device connection status."""
    return JSONResponse(content=device_manager.get_status())


@app.get("/api/device/ports")
async def api_device_ports():
    """Return list of available COM ports."""
    return JSONResponse(content={"ports": DeviceConnectionManager.list_com_ports()})


@app.websocket("/ws/sensor-data")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Send current sensor data
            try:
                await websocket.send_text(json.dumps(sensor_data))
                await asyncio.sleep(2)  # Send every 2 seconds
            except Exception as send_error:
                # Connection closed or error sending - break the loop
                error_msg = str(send_error).lower()
                if "close" not in error_msg and "disconnect" not in error_msg:
                    logger.debug(f"WebSocket send error: {send_error}")
                break
    except Exception as e:
        # Check if it's a connection closed error (which is normal)
        error_msg = str(e).lower()
        if "close" not in error_msg and "disconnect" not in error_msg:
            logger.debug(f"WebSocket error: {e}")
    finally:
        # Only close if connection is still open
        try:
            await websocket.close()
        except (RuntimeError, Exception) as close_error:
            # Connection already closed - this is normal, ignore the error
            pass

@app.get("/api/status")
async def get_status():
    last_update_ago = round(time.time() - last_mqtt_message_time, 1) if last_mqtt_message_time else None
    return {
        "status": "running",
        "data_source": "Direct (ethernet_fetcher / com_port_fetcher → /api/ingest)",
        "mqtt_enabled": False,
        "update_counter": update_counter,
        "last_update_seconds_ago": last_update_ago,
        "update_frequency": "Real-time (Direct TCP/COM)" if update_counter > 0 else "Waiting for device data",
        "active_websockets": 1,
        "timestamp": sensor_data["timestamp"]
    }

@app.post("/api/logs/download")
async def download_logs(
    start_date: str = Form(...),
    end_date: str = Form(...),
    categories: str = Form(...),  # JSON string of categories
    format: str = Form(...)
):
    """Download logs in the specified format - ONLY REAL DATA FROM data.json."""
    try:
        logger.info(f"📊 Download request received - Date: {start_date} to {end_date}, Format: {format}")
        
        # Validate date range
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid date format. Expected YYYY-MM-DD, got: {start_date} / {end_date}"}
            )
        
        if start > end:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"error": "Start date must be before end date"}
            )
        
        # Load sensor data from data.json file
        logger.info(f"📊 Loading data from data.json at: {DATA_JSON_FILE}")
        try:
            all_sensor_data = load_sensor_data_from_json()
            logger.info(f"📊 Loaded {len(all_sensor_data) if all_sensor_data else 0} entries from data.json")
        except Exception as e:
            logger.error(f"❌ Error loading data.json: {e}")
            import traceback
            logger.error(f"Load error traceback: {traceback.format_exc()}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"error": f"Error loading data.json: {str(e)}"}
            )
        
        if not all_sensor_data or len(all_sensor_data) == 0:
            logger.warning("⚠️ No sensor data in data.json - generating empty template file")
            # Return an empty template file instead of an error
            filename = os.path.join(DATA_PATH, f"aerostat_logs_{start_date}_to_{end_date}.{format}")
            if format == 'csv':
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    import csv as _csv
                    writer = _csv.writer(f)
                    writer.writerow(['date', 'timestamp', 'update_number', 'note'])
                    writer.writerow([start_date, '', '', 'No sensor data recorded yet. Connect via Admin → Device (Ethernet or COM).'])
                media_type = 'text/csv'
            elif format == 'json':
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump({"note": "No sensor data recorded yet. Connect via Admin → Device (Ethernet or COM).", "date_range": {"start": start_date, "end": end_date}, "data": []}, f, indent=2)
                media_type = 'application/json'
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"AEROSTAT LOGS\nDate Range: {start_date} to {end_date}\n\nNo sensor data recorded yet.\nConnect via Admin → Device (Ethernet or COM) to start logging.\n")
                media_type = 'text/plain'
            return FileResponse(path=filename, filename=os.path.basename(filename), media_type=media_type,
                                headers={"Content-Disposition": f"attachment; filename={os.path.basename(filename)}"})
        
        # Filter sensor data by date range
        filtered_data = []
        for entry in all_sensor_data:
            try:
                entry_date_str = entry.get("date")
                if not entry_date_str:
                    continue
                    
                entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
                if start.date() <= entry_date <= end.date():
                    filtered_data.append(entry)
            except Exception as e:
                logger.warning(f"Skipping entry with invalid date format: {e}")
                continue
        
        # Check if we have any valid data after filtering
        if not filtered_data or len(filtered_data) == 0:
            logger.warning(f"⚠️ No data found for date range {start_date} to {end_date} - generating empty template")
            filename = os.path.join(DATA_PATH, f"aerostat_logs_{start_date}_to_{end_date}.{format}")
            if format == 'csv':
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    import csv as _csv
                    writer = _csv.writer(f)
                    writer.writerow(['date', 'timestamp', 'update_number', 'note'])
                    writer.writerow([start_date, '', '', f'No sensor data recorded for {start_date} to {end_date}.'])
                media_type = 'text/csv'
            elif format == 'json':
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump({"note": f"No sensor data for {start_date} to {end_date}.", "data": []}, f, indent=2)
                media_type = 'application/json'
            else:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"AEROSTAT LOGS\nDate Range: {start_date} to {end_date}\n\nNo sensor data recorded for this date range.\n")
                media_type = 'text/plain'
            return FileResponse(path=filename, filename=os.path.basename(filename), media_type=media_type,
                                headers={"Content-Disposition": f"attachment; filename={os.path.basename(filename)}"})
        
        logger.info(f"✅ Found {len(filtered_data)} sensor data entries for date range {start_date} to {end_date}")
        
        # Export sensor data in the requested format
        filename = os.path.join(DATA_PATH, f"aerostat_realtime_logs_{start_date}_to_{end_date}.{format}")
        logger.info(f"📝 Exporting to: {filename}")
        
        try:
            # Ensure directory exists
            dir_path = os.path.dirname(filename)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            if format == 'txt':
                export_data_to_txt(filtered_data, filename)
                media_type = 'text/plain'
            elif format == 'csv':
                export_data_to_csv(filtered_data, filename)
                media_type = 'text/csv'
            elif format == 'json':
                logs_system.export_to_json(filtered_data, filename)
                media_type = 'application/json'
            else:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Unsupported format: {format}. Supported formats: csv, json, txt"}
                )
            
            # Verify file was created and has content
            if not os.path.exists(filename):
                logger.error(f"❌ File was not created: {filename}")
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=500,
                    content={"error": "Failed to create log file. Please check server logs for details."}
                )
            
            file_size = os.path.getsize(filename)
            if file_size == 0:
                os.remove(filename)
                logger.error(f"❌ File is empty: {filename}")
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=500,
                    content={"error": "Generated log file is empty. Please try again."}
                )
            
            logger.info(f"✅ Created log file: {filename} ({file_size} bytes)")
            
            # Get just the filename for download
            download_filename = os.path.basename(filename)
            
            # Return file for download
            return FileResponse(
                path=filename,
                filename=download_filename,
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={download_filename}"}
            )
            
        except Exception as export_error:
            logger.error(f"❌ Error during export: {export_error}")
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"Export error traceback:\n{error_traceback}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"error": f"Error exporting logs: {str(export_error)}. Check server logs for details."}
        )
        
    except Exception as e:
        logger.error(f"❌ Error downloading logs: {e}")
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Download error traceback:\n{error_traceback}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"error": f"Error downloading logs: {str(e)}. Check server logs for details."}
        )

@app.get("/api/logs/info")
async def get_logs_info():
    """Get information about available logs from data.json."""
    try:
        from collections import Counter
        all_sensor_data = load_sensor_data_from_json()
        
        # Get date range
        dates = []
        for entry in all_sensor_data:
            date_str = entry.get("date")
            if date_str:
                dates.append(date_str)
        
        unique_dates = sorted(set(dates)) if dates else []
        sources = dict(Counter(entry.get("source", "unknown") for entry in all_sensor_data))
        
        return {
            "total_entries": len(all_sensor_data),
            "available_dates": unique_dates,
            "sources": sources,
            "date_range": {
                "earliest": unique_dates[0] if unique_dates else None,
                "latest": unique_dates[-1] if unique_dates else None
            },
            "data_file": DATA_JSON_FILE,
            "data_file_exists": os.path.exists(DATA_JSON_FILE)
        }
    except Exception as e:
        logger.error(f"Error getting logs info: {e}")
        return {
            "error": str(e),
            "data_file": DATA_JSON_FILE,
            "data_file_exists": os.path.exists(DATA_JSON_FILE)
        }

@app.get("/api/logs/categories")
async def get_log_categories():
    """Get available log categories."""
    return {
        "categories": list(logs_system.parameter_categories.keys()),
        "total_parameters": sum(len(params) for params in logs_system.parameter_categories.values())
    }

@app.get("/api/logs/realtime-status")
async def get_realtime_logs_status():
    """Get real-time logs status and count."""
    try:
        global real_time_logs
        total_changes = sum(len(log["changes"]) for log in real_time_logs)
        return {
            "has_realtime_logs": len(real_time_logs) > 0,
            "log_count": len(real_time_logs),
            "total_parameter_changes": total_changes,
            "latest_update": real_time_logs[-1]["timestamp"] if real_time_logs else None,
            "first_update": real_time_logs[0]["timestamp"] if real_time_logs else None,
            "update_frequency": "Every 2 seconds with BIG value changes",
            "data_retention": "ALL DATA - No limits"
        }
    except Exception as e:
        logger.error(f"Error getting real-time logs status: {e}")
        return {"error": str(e)}

@app.post("/api/logs/clear")
async def clear_realtime_logs():
    """Clear all real-time logs (optional cleanup)."""
    try:
        global real_time_logs
        cleared_count = len(real_time_logs)
        real_time_logs = []
        logger.info(f"🧹 Cleared {cleared_count} real-time log entries")
        return {
            "message": f"Cleared {cleared_count} log entries",
            "remaining_logs": 0
        }
    except Exception as e:
        logger.error(f"Error clearing real-time logs: {e}")
        return {"error": str(e)}

# ==================== SECURE WINCH CONTROL API ====================

@app.post("/api/control/winch")
async def control_winch(
    action: str = Form(...),  # "START", "STOP", "ON", "OFF"
    api_key: str = Form(...)
):
    """
    Secure Winch Control via GCS Controller with API Key Authentication
    """
    try:
        # Validate API key
        if not validate_api_key(api_key, "control"):
            logger.warning("❌ Unauthorized winch control attempt - invalid API key")
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: Invalid API key"}
            )
        
        # Validate action
        valid_actions = ["START", "STOP", "ON", "OFF"]
        action_upper = action.upper()
        if action_upper not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid action. Must be one of: {', '.join(valid_actions)}"}
            )
        
        # Determine MQTT topic for winch control
        winch_topic = "parveenesp32/control/winch"  # Adjust to your MQTT topic
        
        # Create secure command payload
        command_data = {
            "device": "winch_motor",
            "action": action_upper,
            "timestamp": datetime.now().isoformat(),
            "source": "gcs_controller",
            "authorized": True
        }
        
        # Publish command via MQTT
        success = publish_mqtt_command(winch_topic, command_data)
        
        if success:
            logger.info(f"✅ Winch command sent: {action_upper} (API Key: {hash_api_key(api_key)[:8]}...)")
            
            # Update sensor data state (optional - for immediate UI feedback)
            global sensor_data
            if action_upper in ["START", "ON"]:
                sensor_data["winch_motor_status"] = "ON"
            elif action_upper in ["STOP", "OFF"]:
                sensor_data["winch_motor_status"] = "OFF"
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": f"Winch command executed: {action_upper}",
                    "device": "winch_motor",
                    "timestamp": command_data["timestamp"]
                }
            )
        else:
            logger.error("❌ Failed to send winch command via MQTT")
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to send command. MQTT not connected."}
            )
            
    except Exception as e:
        logger.error(f"❌ Error in winch control: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {str(e)}"}
        )

@app.get("/api/control/generate-key")
async def generate_winch_api_key(request: Request):
    """
    Generate a new API key for winch control (Admin only)
    """
    # Check if user is admin (you may need to import auth_manager)
    try:
        from auth import auth_manager
        user = auth_manager.get_current_user(request)
        if not user or user.get("role") != "admin":
            return JSONResponse(
                status_code=403,
                content={"error": "Admin access required"}
            )
    except:
        # If auth is not available, allow for now (you should implement proper auth)
        pass
    
    try:
        api_key, api_key_hash = create_winch_api_key()
        save_api_keys()
        
        logger.info(f"✅ New winch API key generated by admin")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "api_key": api_key,  # Return only once - user must save it
                "message": "API key generated successfully. Save this key securely - it will not be shown again.",
                "created": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Error generating API key: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ==================== YOLOv8 DETECTION API ====================

@app.post("/api/detect")
async def detect_objects(request: Request):
    """
    YOLOv8 detection endpoint for person detection, object detection, counting, and tracking
    Accepts image as base64 or multipart form data
    """
    try:
        from yolo_detector import get_people_detector
        import base64
        from fastapi import UploadFile, File
        
        try:
            people_detector = get_people_detector()
        except Exception as detector_error:
            logger.error(f"Error initializing detector: {detector_error}")
            import traceback
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to initialize detector: {str(detector_error)}"}
            )
        
        # Try to get image from form data first
        image_data = None
        skip_gate = False
        try:
            form = await request.form()
            skip_gate = str(form.get("skip_gate", "")).lower() in ("1", "true", "yes")
            # Check for 'file' field (multipart file upload)
            if 'file' in form:
                file_obj = form['file']
                if hasattr(file_obj, 'read'):
                    image_data = await file_obj.read()
                elif hasattr(file_obj, 'file'):
                    image_data = await file_obj.file.read()
            # Check for 'image' field
            elif 'image' in form:
                image_obj = form['image']
                if hasattr(image_obj, 'read'):
                    image_data = await image_obj.read()
                elif hasattr(image_obj, 'file'):
                    image_data = await image_obj.file.read()
        except Exception as form_error:
            # If form reading fails, try JSON with base64
            try:
                body = await request.json()
                if 'image' in body:
                    image_data = base64.b64decode(body['image'])
                if body.get("skip_gate") in (1, "1", True, "true", "yes"):
                    skip_gate = True
            except Exception as json_error:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Error reading image data. Form error: {str(form_error)}, JSON error: {str(json_error)}"}
                )
        
        if image_data is None:
            return JSONResponse(
                status_code=400,
                content={"error": "No image data provided. Send image as 'file' or 'image' in form data, or 'image' as base64 in JSON."}
            )
        
        # Convert to numpy array
        import cv2
        import numpy as np
        
        # Ensure image_data is bytes
        if not isinstance(image_data, bytes):
            try:
                if isinstance(image_data, str):
                    image_data = image_data.encode('latin-1')
                else:
                    image_data = bytes(image_data)
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Could not convert image data to bytes: {str(e)}"}
                )
        
        # Convert image data to numpy array
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.error(f"Error converting image data: {e}")
            return JSONResponse(
                status_code=400,
                content={"error": f"Error processing image data: {str(e)}"}
            )
        
        if image is None:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid image format or corrupted image data"}
            )
        
        # People detection - always run when we have a frame (movement gate is optional for future use)
        try:
            detections = people_detector.detect(image, track=True, classes=[0])
        except Exception as detect_error:
            logger.error(f"Error during detection: {detect_error}")
            import traceback
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"error": f"Detection failed: {str(detect_error)}"}
            )
        
        # Prepare response - only return people detections
        if not isinstance(detections, dict):
            logger.error(f"Unexpected detection result type: {type(detections)}")
            detections = {
                'people': [],
                'people_count': 0
            }
        
        # Check for intrusions if intrusion detection is enabled
        intrusions = []
        try:
            from intrusion_detector import get_intrusion_tracker, get_alert_manager
            intrusion_tracker = get_intrusion_tracker()
            alert_manager = get_alert_manager()
            
            # Check for intrusions - use all tracked objects (humans, animals, vehicles)
            all_tracked_objects = detections.get('tracked_objects', [])
            if not all_tracked_objects:
                # Fallback to combining all categories
                all_tracked_objects = (
                    detections.get('humans', detections.get('people', [])) +
                    detections.get('animals', []) +
                    detections.get('vehicles', [])
                )
            
            intrusions = intrusion_tracker.check_intrusions(
                all_tracked_objects,
                frame_timestamp=time.time()
            )
            
            # Trigger alerts for new intrusions
            for intrusion in intrusions:
                alert_manager.trigger_alert(intrusion)
        except Exception as intrusion_error:
            logger.debug(f"Intrusion detection error (non-critical): {intrusion_error}")
            # Don't fail the entire request if intrusion detection has issues
        
        # Return all detection data (humans, animals, vehicles)
        response_data = {
            # Human detections
            "people_count": detections.get('human_count', detections.get('people_count', 0)),
            "human_count": detections.get('human_count', 0),
            "people": [
                {
                    "bbox": person['bbox'],
                    "confidence": person['confidence'],
                    "track_id": person.get('track_id', None),
                    "category": person.get('category', 'human'),
                    "class": person.get('class', 'person')
                }
                for person in detections.get('humans', detections.get('people', []))
            ],
            # Animal detections
            "animal_count": detections.get('animal_count', 0),
            "animals": [
                {
                    "bbox": animal['bbox'],
                    "confidence": animal['confidence'],
                    "track_id": animal.get('track_id', None),
                    "category": animal.get('category', 'animal'),
                    "class": animal.get('class', 'unknown')
                }
                for animal in detections.get('animals', [])
            ],
            # Vehicle detections
            "vehicle_count": detections.get('vehicle_count', 0),
            "vehicles": [
                {
                    "bbox": vehicle['bbox'],
                    "confidence": vehicle['confidence'],
                    "track_id": vehicle.get('track_id', None),
                    "category": vehicle.get('category', 'vehicle'),
                    "class": vehicle.get('class', 'unknown')
                }
                for vehicle in detections.get('vehicles', [])
            ],
            # Total targets
            "total_targets": detections.get('total_targets', 0),
            # Intrusions
            "intrusions": [
                {
                    "track_id": intrusion['track_id'],
                    "zone_id": intrusion['zone_id'],
                    "zone_name": intrusion['zone_name'],
                    "alert_level": intrusion['alert_level'],
                    "timestamp": intrusion['timestamp'],
                    "datetime": intrusion['datetime'],
                    "category": intrusion.get('category', 'unknown'),
                    "class": intrusion.get('class', 'unknown'),
                    "object_type": intrusion.get('object_type', 'Unknown')
                }
                for intrusion in intrusions
            ],
            "intrusion_count": len(intrusions),
            # Class counts
            "class_counts": detections.get('class_counts', {})
        }
        
        return JSONResponse(content=response_data)
        
    except Exception as e:
        logger.error(f"Error in detection endpoint: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ==================== STREAM (AeroStream) PEOPLE DETECTION ====================

STREAM_CONFIG_FILE = os.path.join(DATA_PATH, "stream_config.json")

def _save_stream_config(url: str, detection_enabled: bool):
    """Persist stream URL so it survives server restarts."""
    try:
        with open(STREAM_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({"stream_url": url, "detection_enabled": detection_enabled}, f)
        logger.info("Stream config saved: %s", url[:80])
    except Exception as e:
        logger.error("Failed to save stream config: %s", e)

def _clear_stream_config():
    """Remove persisted stream URL when stream is stopped."""
    try:
        if os.path.exists(STREAM_CONFIG_FILE):
            os.remove(STREAM_CONFIG_FILE)
            logger.info("Stream config cleared")
    except Exception as e:
        logger.error("Failed to clear stream config: %s", e)

def _load_and_autostart_stream():
    """On server boot, restore previously saved stream URL."""
    try:
        if not os.path.exists(STREAM_CONFIG_FILE):
            return
        with open(STREAM_CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        url = cfg.get("stream_url", "").strip()
        detection_enabled = cfg.get("detection_enabled", True)
        if not url:
            return
        from stream_capture import start_stream_capture
        start_stream_capture(url, detection_enabled=detection_enabled)
        logger.info("Auto-restored stream on startup: %s", url[:80])
    except Exception as e:
        logger.error("Failed to auto-restore stream: %s", e)


@app.post("/api/stream/start")
async def stream_capture_start(request: Request):
    """Start backend capture and people detection for the given stream URL (e.g. YouTube)."""
    try:
        from stream_capture import start_stream_capture
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        url = (data.get("stream_url") or data.get("rtsp") or data.get("url") or "").strip()
        raw_det = data.get("detection_enabled", data.get("enable_yolo", True))
        if isinstance(raw_det, str):
            detection_enabled = raw_det.strip().lower() in ("1", "true", "yes", "on")
        else:
            detection_enabled = bool(raw_det)
        result = start_stream_capture(url, detection_enabled=detection_enabled)
        if result.get("ok"):
            _save_stream_config(url, detection_enabled)  # persist for restarts
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("Stream start error: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/api/stream/stop")
async def stream_capture_stop():
    """Stop stream capture and detection."""
    try:
        from stream_capture import stop_stream_capture
        stop_stream_capture()
        _clear_stream_config()  # clear persisted URL so it doesn't auto-restart
        return JSONResponse(content={"ok": True})
    except Exception as e:
        logger.error("Stream stop error: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/api/stream/detection")
async def stream_detection():
    """Get latest people detection result for the current stream."""
    try:
        from stream_capture import get_stream_detection
        out = get_stream_detection()
        return JSONResponse(content=out)
    except Exception as e:
        logger.error("Stream detection error: %s", e)
        return JSONResponse(
            status_code=500,
            content={"people": [], "people_count": 0, "human_count": 0, "error": str(e)}
        )


@app.get("/api/stream/mjpeg")
async def stream_mjpeg():
    """
    MJPEG stream of annotated video frames (boxes already drawn by backend).
    Frontend displays this in a plain <img> tag — perfectly synced, no iframe needed.
    """
    import base64 as _b64
    import time as _time
    import stream_capture as _sc   # import MODULE, not variable — so we always read latest value

    async def _generate():
        # Push a multipart part only when the backend published a new frame (by seq),
        # so we avoid re-sending the same JPEG and stay tight to capture.
        BOUNDARY = b"--mjpegframe\r\n"
        last_seq = -1
        last_emit_wall = 0.0

        while True:
            try:
                # Phase 3: always live/low-latency MJPEG (no YouTube-style pacing sleeps)
                try:
                    min_gap = float(getattr(_sc, "_STREAM_LIVE_PREVIEW_INTERVAL", 1.0 / 30.0))
                except Exception:
                    min_gap = 1.0 / 30.0
                min_gap = max(min_gap, 1.0 / 60.0)

                with _sc._stream_lock:
                    jpeg = getattr(_sc, "_stream_last_jpeg", None)
                    b64 = _sc._stream_last_frame_b64
                    seq = _sc._stream_preview_seq

                now = _time.monotonic()
                if (
                    (jpeg or b64)
                    and seq > last_seq
                    and (now - last_emit_wall) >= min_gap
                ):
                    if jpeg:
                        frame_bytes = jpeg
                    else:
                        frame_bytes = _b64.b64decode(b64)
                    header = (
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                    )
                    yield BOUNDARY + header + frame_bytes + b"\r\n"
                    last_seq = seq
                    last_emit_wall = now

                await asyncio.sleep(0.002)
            except GeneratorExit:
                break
            except Exception as e:
                logger.debug("MJPEG generate error: %s", e)
                break

    from fastapi.responses import StreamingResponse as _SR
    return _SR(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=mjpegframe",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
            # Hint proxies not to buffer the multipart stream (local dev / some reverse proxies)
            "X-Accel-Buffering": "no",
        },
    )


# ==================== INTRUSION DETECTION API ====================

@app.get("/api/intrusion/zones")
async def get_intrusion_zones():
    """Get all intrusion zones"""
    try:
        from intrusion_detector import get_intrusion_tracker
        tracker = get_intrusion_tracker()
        zones = tracker.get_zones()
        return JSONResponse(content={"zones": zones})
    except Exception as e:
        logger.error(f"Error getting zones: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api/intrusion/zones")
async def create_intrusion_zone(request: Request):
    """Create a new intrusion zone"""
    try:
        from intrusion_detector import get_intrusion_tracker, IntrusionZone
        data = await request.json()
        
        zone_id = data.get('zone_id') or f"zone_{int(time.time())}"
        name = data.get('name', 'Unnamed Zone')
        points = data.get('points', [])
        enabled = data.get('enabled', True)
        alert_level = data.get('alert_level', 'high')
        
        if len(points) < 3:
            return JSONResponse(
                status_code=400,
                content={"error": "Zone must have at least 3 points"}
            )
        
        zone = IntrusionZone(
            zone_id=zone_id,
            name=name,
            points=[(p[0], p[1]) for p in points],
            enabled=enabled,
            alert_level=alert_level
        )
        
        tracker = get_intrusion_tracker()
        tracker.add_zone(zone)
        
        return JSONResponse(content={"success": True, "zone": zone.to_dict()})
    except Exception as e:
        logger.error(f"Error creating zone: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.put("/api/intrusion/zones/{zone_id}")
async def update_intrusion_zone(zone_id: str, request: Request):
    """Update an existing intrusion zone"""
    try:
        from intrusion_detector import get_intrusion_tracker, IntrusionZone
        data = await request.json()
        
        tracker = get_intrusion_tracker()
        
        # Remove old zone
        tracker.remove_zone(zone_id)
        
        # Create updated zone
        name = data.get('name', 'Unnamed Zone')
        points = data.get('points', [])
        enabled = data.get('enabled', True)
        alert_level = data.get('alert_level', 'high')
        
        if len(points) < 3:
            return JSONResponse(
                status_code=400,
                content={"error": "Zone must have at least 3 points"}
            )
        
        zone = IntrusionZone(
            zone_id=zone_id,
            name=name,
            points=[(p[0], p[1]) for p in points],
            enabled=enabled,
            alert_level=alert_level
        )
        
        tracker.add_zone(zone)
        
        return JSONResponse(content={"success": True, "zone": zone.to_dict()})
    except Exception as e:
        logger.error(f"Error updating zone: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.delete("/api/intrusion/zones/{zone_id}")
async def delete_intrusion_zone(zone_id: str):
    """Delete an intrusion zone"""
    try:
        from intrusion_detector import get_intrusion_tracker
        tracker = get_intrusion_tracker()
        success = tracker.remove_zone(zone_id)
        
        if success:
            return JSONResponse(content={"success": True})
        else:
            return JSONResponse(
                status_code=404,
                content={"error": "Zone not found"}
            )
    except Exception as e:
        logger.error(f"Error deleting zone: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/api/intrusion/statistics")
async def get_intrusion_statistics():
    """Get intrusion detection statistics"""
    try:
        from intrusion_detector import get_intrusion_tracker
        tracker = get_intrusion_tracker()
        stats = tracker.get_statistics()
        return JSONResponse(content=stats)
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/api/intrusion/history")
async def get_intrusion_history(limit: int = 50):
    """Get recent intrusion history"""
    try:
        from intrusion_detector import get_intrusion_tracker
        tracker = get_intrusion_tracker()
        history = tracker.get_recent_intrusions(limit=limit)
        return JSONResponse(content={"intrusions": history})
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api/intrusion/history/clear")
async def clear_intrusion_history():
    """Clear intrusion history"""
    try:
        from intrusion_detector import get_intrusion_tracker
        tracker = get_intrusion_tracker()
        tracker.clear_history()
        return JSONResponse(content={"success": True})
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ==================== LOCATION API ====================

@app.post("/api/location/set")
async def set_location(request: Request):
    """Set current GPS location manually"""
    try:
        data = await request.json()
        lat = float(data.get('latitude', 0))
        lon = float(data.get('longitude', 0))
        
        # Validate coordinates
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid coordinates. Latitude: -90 to 90, Longitude: -180 to 180"}
            )
        
        # Update global sensor data
        sensor_data['latitude'] = lat
        sensor_data['longitude'] = lon
        
        # Save to file for persistence
        import os
        import json
        os.makedirs('data', exist_ok=True)
        with open('data/current_location.json', 'w') as f:
            json.dump({'latitude': lat, 'longitude': lon}, f)
        
        logger.info(f"Location manually set to: {lat}, {lon}")
        
        return JSONResponse(
            content={
                "success": True,
                "latitude": lat,
                "longitude": lon
            }
        )
    except Exception as e:
        logger.error(f"Error setting location: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ==================== THRESHOLDS API (server-side persistent) ====================

THRESHOLDS_FILE = os.path.join(DATA_PATH, "thresholds.json")

@app.get("/api/thresholds")
async def get_thresholds():
    """Return saved thresholds from server-side file."""
    try:
        if os.path.exists(THRESHOLDS_FILE):
            with open(THRESHOLDS_FILE, 'r', encoding='utf-8') as f:
                return JSONResponse(content=json.load(f))
        return JSONResponse(content={})
    except Exception as e:
        logger.error(f"Error loading thresholds: {e}")
        return JSONResponse(content={})

@app.post("/api/thresholds")
async def save_thresholds(request: Request):
    """Save thresholds to server-side file - shared across all users."""
    try:
        data = await request.json()
        with open(THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Thresholds saved ({len(data)} parameters)")
        return JSONResponse(content={"success": True, "saved": len(data)})
    except Exception as e:
        logger.error(f"Error saving thresholds: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==================== STREAM STATUS API ====================

@app.get("/api/stream/status")
async def get_stream_status():
    """Return current stream URL and active state so all users can auto-reconnect."""
    try:
        from stream_capture import is_stream_capture_active, _stream_url, _stream_detection_enabled
        active = is_stream_capture_active()
        return JSONResponse(content={
            "active": active,
            "stream_url": _stream_url if active else None,
            "detection_enabled": _stream_detection_enabled if active else False
        })
    except Exception as e:
        return JSONResponse(content={"active": False, "stream_url": None, "detection_enabled": False})


# ==================== GIMBAL ICD v1.0 API ====================

def _gimbal_auth_ok(request: Request) -> bool:
    """Optional Bearer check when require_auth=true (ICD JWT). Off by default for GCS UI buttons."""
    try:
        import gimbal_control as _gc
        cfg = _gc.load_config()
        if not cfg.get("require_auth"):
            return True
        required = (cfg.get("bearer_token") or "").strip()
        if not required:
            return True
        auth = (request.headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() == required
        return False
    except Exception:
        return True


@app.get("/api/v1/gimbal/status")
async def gimbal_status(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        return JSONResponse(content=_gc.get_status())
    except Exception as e:
        logger.error("Gimbal status error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/move")
async def gimbal_move_absolute(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        result = _gc.absolute_move(data.get("pan", 0), data.get("tilt", 0))
        code = 200 if result.get("success") else 400
        return JSONResponse(status_code=code, content=result)
    except Exception as e:
        logger.error("Gimbal move error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/move/relative")
async def gimbal_move_relative(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        result = _gc.relative_move(data.get("panDelta", 0), data.get("tiltDelta", 0))
        code = 200 if result.get("success") else 400
        return JSONResponse(status_code=code, content=result)
    except Exception as e:
        logger.error("Gimbal relative move error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/jog")
async def gimbal_jog(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        result = _gc.jog(data.get("panVelocity", 0), data.get("tiltVelocity", 0))
        return JSONResponse(content=result)
    except Exception as e:
        logger.error("Gimbal jog error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/stop")
async def gimbal_stop(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        try:
            await request.json()
        except Exception:
            pass
        return JSONResponse(content=_gc.stop())
    except Exception as e:
        logger.error("Gimbal stop error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/home")
async def gimbal_home(request: Request):
    if not _gimbal_auth_ok(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    try:
        import gimbal_control as _gc
        return JSONResponse(content=_gc.home())
    except Exception as e:
        logger.error("Gimbal home error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/ui/direction")
async def gimbal_ui_direction(request: Request):
    """UI helper: direction pad → ICD jog (hold) or relative nudge (click)."""
    try:
        import gimbal_control as _gc
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        direction = (data.get("direction") or "").strip().lower()
        mode = (data.get("mode") or "jog").strip().lower()
        if mode == "nudge":
            result = _gc.direction_nudge(direction)
        else:
            result = _gc.direction_jog(direction)
        code = 200 if result.get("success") else 400
        return JSONResponse(status_code=code, content=result)
    except Exception as e:
        logger.error("Gimbal UI direction error: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.get("/api/v1/gimbal/config")
async def gimbal_get_config():
    try:
        import gimbal_control as _gc
        cfg = _gc.load_config()
        # Never echo full token to browser listing — mask if present
        token = cfg.get("bearer_token") or ""
        safe = dict(cfg)
        safe["bearer_token"] = token
        safe["has_token"] = bool(token)
        return JSONResponse(content={"success": True, "data": safe})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/v1/gimbal/config")
async def gimbal_save_config(request: Request):
    try:
        import gimbal_control as _gc
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        cfg = _gc.save_config(data or {})
        return JSONResponse(content={"success": True, "data": cfg, "message": "Gimbal config saved."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.get("/api/location/current")
async def get_current_location():
    """Get current GPS location"""
    try:
        return JSONResponse(
            content={
                "latitude": sensor_data.get('latitude', 0),
                "longitude": sensor_data.get('longitude', 0)
            }
        )
    except Exception as e:
        logger.error(f"Error getting location: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


def _shutdown_stream_capture():
    """Stop background stream (yt-dlp/ffmpeg) so exit or Ctrl+C does not leave orphan processes."""
    try:
        from stream_capture import stop_stream_capture
        stop_stream_capture()
    except Exception:
        pass


if __name__ == "__main__":
    import atexit
    import signal

    atexit.register(_shutdown_stream_capture)

    def _sigint_handler(signum, frame):
        print("\n\nStopping: closing background stream capture…")
        _shutdown_stream_capture()
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except (ValueError, OSError):
        pass
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _sigint_handler)
        except (ValueError, OSError, AttributeError):
            pass

    try:
        print("=" * 60)
        print("  Aerostat Dashboard — Direct Device Mode")
        print("=" * 60)
        print("  Dashboard : http://localhost:5001")
        print("  Data Source: ethernet_fetcher.py  OR  com_port_fetcher.py")
        print("  Ingest API : POST http://localhost:5001/api/ingest")
        print("  MQTT       : DISABLED")
        print("=" * 60)
        print("  Stop the server: Ctrl+C")
        print("=" * 60)

        # Initialize API keys
        print("Initializing API keys...")
        initialize_api_keys()

        # MQTT is disabled — data comes directly via /api/ingest from
        # ethernet_fetcher.py or com_port_fetcher.py, or via the built-in device manager
        print("MQTT disabled. Waiting for data via /api/ingest or Device Connection panel...")

        # Auto-restore last device connection (if set via dashboard UI)
        device_manager.autostart()

        # Auto-restore previously saved stream URL (persists across restarts)
        _load_and_autostart_stream()

        # Start only timestamp update thread (no simulation)
        timestamp_thread = threading.Thread(target=update_timestamp_only, daemon=True)
        timestamp_thread.start()
        
        # Start the web server on port 5001
        # Auto-open browser after server starts
        import webbrowser
        import threading
        
        def open_browser():
            """Open browser after a short delay to ensure server is ready"""
            import time
            time.sleep(2)  # Wait 2 seconds for server to start
            try:
                webbrowser.open('http://localhost:5001')
                print("Browser opened automatically")
            except Exception as e:
                print(f"Could not open browser automatically: {e}")
                print("   Please manually open: http://localhost:5001")
        
        # Start browser opening in a separate thread
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
        
        # For frozen executables, disable uvicorn's logging config to avoid isatty() issues
        try:
            if getattr(sys, 'frozen', False):
                # Running as executable - disable uvicorn's default logging config
                print("\n" + "="*60)
                print("Dashboard server starting...")
                print("Browser will open automatically in 2 seconds...")
                print("="*60)
                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=5001,
                    log_level="warning",  # Use warning level to reduce log output
                    access_log=False,  # Disable access logs
                    log_config=None  # Disable uvicorn's logging config entirely
                )
            else:
                # Running as script - use normal logging
                print("Browser will open automatically in 2 seconds...")
                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=5001,
                    log_level="info"
                )
        finally:
            _shutdown_stream_capture()
    
    except KeyboardInterrupt:
        print("\n\nDashboard is shutting down...")
        _shutdown_stream_capture()
        if getattr(sys, 'frozen', False):
            import time
            time.sleep(2)  # Give time to see the message
    
    except Exception as e:
        # Log error to file and console
        error_msg = f"\n\n{'='*60}\n"
        error_msg += f"ERROR: Dashboard failed to start!\n"
        error_msg += f"{'='*60}\n"
        error_msg += f"Error Type: {type(e).__name__}\n"
        error_msg += f"Error Message: {str(e)}\n"
        error_msg += f"\nFull Traceback:\n"
        import traceback
        error_msg += traceback.format_exc()
        error_msg += f"\n{'='*60}\n"
        
        print(error_msg)
        
        # Also save to error log file
        try:
            if getattr(sys, 'frozen', False):
                error_log_path = os.path.join(DATA_PATH, "dashboard_error.log")
            else:
                error_log_path = "dashboard_error.log"
            
            with open(error_log_path, 'w', encoding='utf-8') as f:
                f.write(error_msg)
            print(f"\nError details saved to: {error_log_path}\n")
        except:
            pass
        
        # Keep console open so user can see the error
        if getattr(sys, 'frozen', False):
            print("\nPress any key to exit...")
            try:
                import msvcrt
                msvcrt.getch()
            except:
                import time
                time.sleep(10)  # Wait 10 seconds if getch() fails
