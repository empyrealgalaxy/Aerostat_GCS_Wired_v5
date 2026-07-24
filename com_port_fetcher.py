#!/usr/bin/env python3
"""
COM Port Data Fetcher - Aerostat Dashboard
Reads CSV sensor data from Serial/COM port (USB-SERIAL CH340 on COM3),
maps fields, and POSTs directly to the dashboard at http://localhost:5001/api/ingest.

No MQTT required. Data flows:
  Device (COM Port) → this script → HTTP POST → Dashboard → Browser (live)

NOTE: Close Hercules or any other app using COM3 before running this script.

CSV Sequence from device:
  [0]  Count      → ping_ms
  [1]  Millis     → millis
  [2]  Timestamp  → device_timestamp
  [3]  Temp1      → ambient_temp_C        (Ambient Temperature °C)
  [4]  Press1     → ambient_pressure_hPa  (Ambient Pressure mbar)
  [5]  Alt1       → altitude1_m           (Altitude AMSL m)
  [6]  Temp2      → helium_temp_C         (Helium Temperature °C)
  [7]  Press2     → helium_pressure_hPa   (Helium Pressure mbar)
  [8]  Alt2       → altitude2_m           (Altitude AGL m)
  [9]  Wind       → wind_kmh              (Wind Speed km/h)
  [10] Load       → weight_kg             (C.P. Tension kg)
  [11] PressDiff  → pressure_diff_hPa     (Pressure Diff ΔP mbar)
  [12] Lat        → latitude              (°)
  [13] Lon        → longitude             (°)
  [14] Heading    → heading_deg           (Compass °)
  [15] Yaw        → yaw_deg               (Heading/Yaw °)
  [16] Pitch      → pitch_deg             (Pitch °)
  [17] Roll       → roll_deg              (Roll °)
  [18] DHT_Temp   → ground_temperature_C  (DHT Temperature °C)
  [19] DHT_Hum    → ambient_humidity_percent (Humidity %)
  [20] WindSpeed  → wind_speed_km_s       (Wind Speed km/h)   [NEW]
  [21] WindDir    → wind_direction_degrees (Wind Direction °) [NEW]
"""

import serial
import serial.tools.list_ports
import json
import os
import time
import logging
import urllib.request
import urllib.error
from datetime import datetime

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ─── COM Port Configuration ───────────────────────────────────────────────────
COM_CONFIG = {
    "port":     "COM3",              # USB-SERIAL CH340 detected on COM3
    "baudrate": 9600,
    "bytesize": serial.EIGHTBITS,
    "parity":   serial.PARITY_NONE,
    "stopbits": serial.STOPBITS_ONE,
    "timeout":  2,
}

# ─── Dashboard Configuration ──────────────────────────────────────────────────
DASHBOARD_URL = "http://localhost:5001/api/ingest"

# ─── Output File ──────────────────────────────────────────────────────────────
OUTPUT_DIR  = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "com_port_mapped_data.json")

# ─── CSV Field Map ────────────────────────────────────────────────────────────
FIELD_MAP = {
    0:  ("ping_ms",                  "Ping",                  ""),
    1:  ("millis",                   "Millis",                "ms"),
    2:  ("device_timestamp",         "Device Timestamp",      ""),
    3:  ("ambient_temp_C",           "Ambient Temperature",   "°C"),
    4:  ("ambient_pressure_hPa",     "Ambient Pressure",      "mbar"),
    5:  ("altitude1_m",              "Altitude AMSL",         "m"),
    6:  ("helium_temp_C",            "Helium Temperature",    "°C"),
    7:  ("helium_pressure_hPa",      "Helium Pressure",       "mbar"),
    8:  ("altitude2_m",              "Altitude AGL",          "m"),
    9:  ("wind_kmh",                 "Wind Speed",            "km/h"),
    10: ("weight_kg",                "C.P. Tension",          "kg"),
    11: ("pressure_diff_hPa",        "Pressure Diff (ΔP)",    "mbar"),
    12: ("latitude",                 "Lat",                   "°"),
    13: ("longitude",                "Lon",                   "°"),
    14: ("heading_deg",              "Compass",               "°"),
    15: ("yaw_deg",                  "Heading (Yaw)",         "°"),
    16: ("pitch_deg",                "Pitch",                 "°"),
    17: ("roll_deg",                 "Roll",                  "°"),
    18: ("ground_temperature_C",     "DHT Temperature",       "°C"),
    19: ("ambient_humidity_percent", "Humidity",              "%"),
    20: ("wind_speed_km_s",          "Wind Speed",            "km/h"),
    21: ("wind_direction_degrees",   "Wind Direction",        "°"),
}

STRING_FIELDS = {2}
SKIP_POST     = {1, 2}


# ─── CSV Parser ───────────────────────────────────────────────────────────────

def parse_csv_line(line: str):
    line = line.strip()
    if not line:
        return None, None

    parts = line.split(",")
    if len(parts) < 4:
        return None, None

    post_payload = {}
    all_params   = {}

    for idx, (field_name, display_name, unit) in FIELD_MAP.items():
        if idx >= len(parts):
            continue
        raw = parts[idx].strip()
        if idx in STRING_FIELDS:
            val = raw
        else:
            try:
                val = float(raw)
            except ValueError:
                val = raw

        all_params[field_name] = val
        if idx not in SKIP_POST and isinstance(val, float):
            post_payload[field_name] = val

    if not post_payload:
        return None, None

    full_record = {
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_line":    line,
        "parameters":  all_params,
    }
    return post_payload, full_record


# ─── Dashboard POST ───────────────────────────────────────────────────────────

def post_to_dashboard(payload: dict) -> bool:
    try:
        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            DASHBOARD_URL,
            data    = body,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read().decode())
            return result.get("status") == "ok"
    except urllib.error.URLError as e:
        logger.error(f"❌ Dashboard not reachable: {e.reason} — is run_dashboard.py running?")
        return False
    except Exception as e:
        logger.error(f"❌ POST error: {e}")
        return False


# ─── Console Printer ──────────────────────────────────────────────────────────

def print_record(record: dict, count: int, post_ok: bool):
    params = record["parameters"]
    ts     = record["received_at"]
    raw    = record["raw_line"]
    status = "→ Dashboard ✅" if post_ok else "→ Dashboard ❌"

    print(f"\n{'='*65}")
    print(f"  Record #{count}  |  {ts}  |  {status}")
    print(f"{'='*65}")
    print(f"  Raw: {raw[:80]}{'...' if len(raw) > 80 else ''}")
    print(f"{'-'*65}")
    print(f"  {'PARAMETER':<32} {'VALUE':>12}  UNIT")
    print(f"{'-'*65}")
    for idx in sorted(FIELD_MAP.keys()):
        fname, dname, unit = FIELD_MAP[idx]
        value = params.get(fname, "N/A")
        val_str = f"{value:>12.4f}" if isinstance(value, float) else f"{str(value):>12}"
        print(f"  [{idx:02d}] {dname:<28} {val_str}  {unit}")
    print(f"{'='*65}")


# ─── File Saver ───────────────────────────────────────────────────────────────

def save_to_file(records: list):
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save error: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    logger.info("COM Port Data Fetcher starting...")

    # List available ports
    ports = serial.tools.list_ports.comports()
    print(f"\n{'='*65}")
    print("  AVAILABLE COM PORTS")
    print(f"{'='*65}")
    if ports:
        for p in ports:
            print(f"  {p.device:10s}  {p.description}")
    else:
        print("  No COM ports found. Is the device plugged in?")
    print(f"{'='*65}\n")

    logger.info(f"  Port      : {COM_CONFIG['port']} @ {COM_CONFIG['baudrate']} baud")
    logger.info(f"  Dashboard : {DASHBOARD_URL}")
    logger.info(f"  Output    : {OUTPUT_FILE}")
    logger.info("  NOTE: Close Hercules or any other app using this port first!")

    try:
        ser = serial.Serial(
            port     = COM_CONFIG["port"],
            baudrate = COM_CONFIG["baudrate"],
            bytesize = COM_CONFIG["bytesize"],
            parity   = COM_CONFIG["parity"],
            stopbits = COM_CONFIG["stopbits"],
            timeout  = COM_CONFIG["timeout"],
        )
        logger.info(f"✅ Serial port opened: {ser.name}")
    except serial.SerialException as e:
        logger.error(f"❌ Cannot open serial port: {e}")
        logger.info("  → Close any app using this port (e.g. Hercules)")
        logger.info(f"  → Or change COM_CONFIG['port'] to the correct port")
        return

    records   = []
    msg_count = 0

    print(f"\n{'='*65}")
    print("  COM PORT  →  DASHBOARD (Direct)")
    print(f"  Port      : {COM_CONFIG['port']} @ {COM_CONFIG['baudrate']} baud")
    print(f"  Dashboard : {DASHBOARD_URL}")
    print(f"  Output    : {OUTPUT_FILE}")
    print("  Press Ctrl+C to stop")
    print(f"{'='*65}\n")

    try:
        while True:
            try:
                raw = ser.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                post_payload, full_record = parse_csv_line(line)
                if not post_payload:
                    logger.debug(f"Skipped: {line[:60]}")
                    continue

                msg_count += 1
                full_record["record_number"] = msg_count
                records.append(full_record)

                # ── Send to dashboard ──
                ok = post_to_dashboard(post_payload)

                # ── Print to console ──
                print_record(full_record, msg_count, ok)

                # ── Auto-save every 10 records ──
                if msg_count % 10 == 0:
                    save_to_file(records)
                    logger.info(f"Auto-saved {msg_count} records → {OUTPUT_FILE}")

            except serial.SerialException as e:
                logger.error(f"Serial read error: {e}")
                time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        ser.close()
        if records:
            save_to_file(records)
            print(f"\n✅ Saved {len(records)} records → {OUTPUT_FILE}")
        logger.info(f"Done. Total records: {msg_count}")


if __name__ == "__main__":
    run()
