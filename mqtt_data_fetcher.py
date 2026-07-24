#!/usr/bin/env python3
"""
MQTT Data Fetcher - Fetches and displays all data published on MQTT server
This script will show you exactly what data is being published to your broker
"""

import time
import paho.mqtt.client as paho
import json
import socket
import logging
import ssl
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MQTT Configuration - Only HiveMQ Cloud broker
MQTT_CONFIG = {
    "broker": "3ec254ca2f5d4fc38600fa7277517ea0.s1.eu.hivemq.cloud",
    "port": 8883,
    "username": "Parveenespcode",
    "password": "Galaxy21",
    "use_tls": True,
    "timeout": 10
}

# Topics to monitor
TOPICS_TO_MONITOR = [
    "parveenesp32/sensor_data",  # Your main sensor data topic
    "parveenesp32/#",            # All topics under parveenesp32
    "#"                          # All topics (be careful with this in production)
]

connected = False
message_count = 0
received_data = {}

def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT connection callback"""
    global connected
    if rc == 0:
        logger.info(f"✅ Connected to MQTT broker: {MQTT_CONFIG['broker']}")
        connected = True
        
        # Subscribe to all monitoring topics
        for topic in TOPICS_TO_MONITOR:
            client.subscribe(topic, qos=1)
            logger.info(f"📡 Subscribed to topic: {topic}")
    else:
        logger.error(f"❌ Failed to connect with code {rc}")
        connected = False

def on_disconnect(client, userdata, rc):
    """MQTT disconnection callback"""
    global connected
    connected = False
    logger.info(f"📡 Disconnected with code {rc}")

def on_message(client, userdata, msg):
    """Handle incoming messages from the broker"""
    global message_count, received_data
    
    try:
        message_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Try to parse as JSON
        try:
            data = json.loads(msg.payload.decode())
            logger.info(f"📥 Message #{message_count} from {msg.topic} at {timestamp}")
            logger.info(f"📊 JSON Data: {json.dumps(data, indent=2)}")
            
            # Store the data
            received_data[msg.topic] = {
                'timestamp': timestamp,
                'data': data,
                'message_count': message_count
            }
            
        except json.JSONDecodeError:
            # Not JSON, display as text
            logger.info(f"📥 Message #{message_count} from {msg.topic} at {timestamp}")
            logger.info(f"📝 Text Data: {msg.payload.decode()}")
            
            # Store the data
            received_data[msg.topic] = {
                'timestamp': timestamp,
                'data': msg.payload.decode(),
                'message_count': message_count
            }
        
        # Display summary of all received data
        display_data_summary()
        
    except Exception as e:
        logger.error(f"❌ Error processing message: {e}")

def on_log(client, userdata, level, buf):
    """MQTT logging callback"""
    logger.debug(f"📝 MQTT Log: {buf}")

def display_data_summary():
    """Display a summary of all received data"""
    print("\n" + "="*80)
    print("📊 MQTT DATA SUMMARY")
    print("="*80)
    print(f"📈 Total Messages Received: {message_count}")
    print(f"📡 Connected: {'✅ Yes' if connected else '❌ No'}")
    print(f"🕐 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*80)
    
    if received_data:
        for topic, info in received_data.items():
            print(f"📋 Topic: {topic}")
            print(f"   🕐 Last Update: {info['timestamp']}")
            print(f"   📊 Message Count: {info['message_count']}")
            
            if isinstance(info['data'], dict):
                print(f"   📝 Parameters: {len(info['data'])}")
                for key, value in info['data'].items():
                    print(f"      • {key}: {value}")
            else:
                print(f"   📝 Data: {info['data']}")
            print("-"*40)
    else:
        print("❌ No data received yet...")
    
    print("="*80)
    print("💡 Waiting for more data... (Press Ctrl+C to stop)")
    print("="*80)

def is_port_open(host, port, timeout=3):
    """Check if a port is open on a host"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def initialize_mqtt_client():
    """Initialize MQTT client"""
    global connected
    
    try:
        logger.info(f"🔄 Connecting to: {MQTT_CONFIG['broker']}:{MQTT_CONFIG['port']}")
        
        # Check port first
        if not is_port_open(MQTT_CONFIG['broker'], MQTT_CONFIG['port'], MQTT_CONFIG.get('timeout', 5)):
            logger.warning(f"⚠️ Port {MQTT_CONFIG['port']} not reachable on {MQTT_CONFIG['broker']}")
            return None
        
        # Create client for fetching data
        client = paho.Client(
            client_id=f"mqtt_fetcher_{int(time.time())}",
            protocol=paho.MQTTv311
        )
        
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.on_log = on_log
        
        # Configure TLS for secure connection
        if MQTT_CONFIG.get("use_tls"):
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                client.tls_set_context(context)
                logger.info("🔐 TLS configured for secure connection")
            except Exception as tls_error:
                logger.error(f"❌ TLS configuration failed: {tls_error}")
                return None
        
        # Set credentials
        if MQTT_CONFIG.get("username") and MQTT_CONFIG.get("password"):
            client.username_pw_set(MQTT_CONFIG["username"], MQTT_CONFIG["password"])
            logger.info("🔑 Authentication credentials set")
        
        client._connect_timeout = MQTT_CONFIG.get('timeout', 15)
        
        # Connect to broker
        try:
            client.connect(MQTT_CONFIG["broker"], MQTT_CONFIG["port"], keepalive=60)
            client.loop_start()
            
            # Wait for connection
            wait_time = 0
            max_wait = MQTT_CONFIG.get('timeout', 15)
            while not connected and wait_time < max_wait:
                time.sleep(0.2)
                wait_time += 0.2
            
            if connected:
                logger.info(f"✅ Successfully connected to {MQTT_CONFIG['broker']}")
                return client
            else:
                client.loop_stop()
                client.disconnect()
                logger.warning(f"⚠️ Failed to connect to {MQTT_CONFIG['broker']} within timeout")
                return None
                
        except Exception as connect_error:
            logger.error(f"❌ Connection error: {connect_error}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error connecting to {MQTT_CONFIG['broker']}: {e}")
        return None

def save_data_to_file():
    """Save received data to a JSON file"""
    try:
        import os
        
        # Create data directory if it doesn't exist
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        
        # Save to JSON file
        file_path = os.path.join(data_dir, "mqtt_fetched_data.json")
        with open(file_path, 'w') as f:
            json.dump(received_data, f, indent=2)
        
        logger.info(f"💾 Data saved to {file_path}")
        
    except Exception as e:
        logger.error(f"❌ Error saving data to file: {e}")

def main():
    """Main function"""
    logger.info("🚀 Starting MQTT Data Fetcher...")
    logger.info("📡 This script will show you ALL data being published on your MQTT broker")
    
    client = initialize_mqtt_client()
    if not client:
        logger.error("❌ Failed to initialize MQTT client")
        return
    
    try:
        # Display initial summary
        display_data_summary()
        
        # Keep running and display updates
        while True:
            time.sleep(5)  # Update every 5 seconds
            
            # Save data periodically
            if message_count > 0 and message_count % 10 == 0:
                save_data_to_file()
            
    except KeyboardInterrupt:
        logger.info("🛑 Stopping MQTT Data Fetcher...")
        
        # Save final data
        if received_data:
            save_data_to_file()
            logger.info(f"💾 Final data saved with {message_count} messages")
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
    finally:
        if client:
            client.loop_stop()
            client.disconnect()
            logger.info("✅ MQTT Data Fetcher stopped cleanly")

if __name__ == "__main__":
    main()
