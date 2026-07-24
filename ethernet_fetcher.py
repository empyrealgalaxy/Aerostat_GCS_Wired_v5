#!/usr/bin/env python3
"""
Ethernet / TCP Data Fetcher - Aerostat Dashboard
Connects to device TCP server (169.254.11.100:5000), reads CSV sensor data,
maps fields, and POSTs directly to the dashboard at http://localhost:5001/api/ingest.

No MQTT required. Data flows:
  Device (TCP) → this script → HTTP POST → Dashboard → Browser (live)

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

import socket
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

# ─── TCP Device Configuration ─────────────────────────────────────────────────
TCP_CONFIG = {
    "host":            "169.254.11.100",
    "port":            5000,
    "connect_timeout": 10,
    "recv_timeout":    3,
    "recv_buffer":     4096,
    "reconnect_delay": 5,
    "send_command":    "",   # empty = stream mode (device pushes data on its own)
}

# ─── Dashboard Configuration ──────────────────────────────────────────────────
DASHBOARD_URL = "http://localhost:5001/api/ingest"

# ─── Output File ──────────────────────────────────────────────────────────────
OUTPUT_DIR  = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "ethernet_mapped_data.json")

# ─── CSV Field Map ────────────────────────────────────────────────────────────
# index → (field_name_for_dashboard, display_name, unit)
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

STRING_FIELDS = {2}        # keep device_timestamp as string
SKIP_POST     = {1, 2}     # millis and device_timestamp not needed by dashboard


# ─── CSV Parser ───────────────────────────────────────────────────────────────

def parse_csv_line(line: str):
    """
    Returns (post_payload, full_record) or (None, None).
    post_payload  → sent to dashboard /api/ingest
    full_record   → saved to local JSON file
    """
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
    """POST mapped data to the dashboard's /api/ingest endpoint."""
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


# ─── TCP Receiver ─────────────────────────────────────────────────────────────

class TCPReceiver:

    def __init__(self):
        self.sock        = None
        self.byte_buffer = b""
        self.last_recv   = time.time()

    def connect(self) -> bool:
        host = TCP_CONFIG["host"]
        port = TCP_CONFIG["port"]
        try:
            logger.info(f"Connecting to device {host}:{port} ...")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(TCP_CONFIG["connect_timeout"])
            self.sock.connect((host, port))
            self.sock.settimeout(TCP_CONFIG["recv_timeout"])
            self.byte_buffer = b""
            self.last_recv   = time.time()
            logger.info(f"✅ TCP connected to {host}:{port}")
            return True
        except Exception as e:
            logger.error(f"❌ TCP connect failed: {e}")
            self.sock = None
            return False

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            logger.info("TCP disconnected")

    def send_command(self, cmd: str):
        if not self.sock or not cmd:
            return
        try:
            self.sock.sendall(cmd.encode("utf-8"))
            logger.info(f"Sent: {repr(cmd)}")
        except Exception as e:
            logger.error(f"Send error: {e}")

    def read_lines(self) -> list:
        lines = []
        if not self.sock:
            return lines
        try:
            chunk = self.sock.recv(TCP_CONFIG["recv_buffer"])
            if not chunk:
                logger.warning("Device closed connection")
                self.disconnect()
                return lines
            self.byte_buffer += chunk
            self.last_recv    = time.time()
        except socket.timeout:
            pass
        except ConnectionResetError:
            logger.warning("Connection reset by device")
            self.disconnect()
            return lines
        except Exception as e:
            logger.error(f"Receive error: {e}")
            self.disconnect()
            return lines

        normalised = self.byte_buffer.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if b"\n" in normalised:
            parts = normalised.split(b"\n")
            for part in parts[:-1]:
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)
            self.byte_buffer = parts[-1]
        elif time.time() - self.last_recv > 3.0 and self.byte_buffer:
            line = self.byte_buffer.decode("utf-8", errors="replace").strip()
            logger.warning(f"No newline — flushing buffer: {repr(line[:80])}")
            if line:
                lines.append(line)
            self.byte_buffer = b""

        return lines

    @property
    def is_connected(self) -> bool:
        return self.sock is not None


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    logger.info("Ethernet/TCP Data Fetcher starting...")
    logger.info(f"  Device    : {TCP_CONFIG['host']}:{TCP_CONFIG['port']}")
    logger.info(f"  Dashboard : {DASHBOARD_URL}")
    logger.info(f"  Output    : {OUTPUT_FILE}")

    receiver    = TCPReceiver()
    records     = []
    msg_count   = 0
    no_data_cnt = 0

    print(f"\n{'='*65}")
    print("  ETHERNET / TCP  →  DASHBOARD (Direct)")
    print(f"  Device    : {TCP_CONFIG['host']}:{TCP_CONFIG['port']}")
    print(f"  Dashboard : {DASHBOARD_URL}")
    print(f"  Output    : {OUTPUT_FILE}")
    print("  Press Ctrl+C to stop")
    print(f"{'='*65}\n")

    try:
        while True:
            if not receiver.is_connected:
                if not receiver.connect():
                    logger.info(f"Retry in {TCP_CONFIG['reconnect_delay']} s...")
                    time.sleep(TCP_CONFIG["reconnect_delay"])
                    continue
                cmd = TCP_CONFIG.get("send_command", "")
                if cmd:
                    receiver.send_command(cmd)

            lines = receiver.read_lines()

            if not lines:
                no_data_cnt += 1
                if no_data_cnt % 10 == 0:
                    elapsed = no_data_cnt * TCP_CONFIG["recv_timeout"]
                    logger.warning(
                        f"No data for ~{elapsed:.0f}s | buffer={len(receiver.byte_buffer)}B"
                    )
                    if receiver.byte_buffer:
                        logger.warning(f"  Buffer hex : {receiver.byte_buffer[:60].hex(' ')}")
                        logger.warning(f"  Buffer text: {repr(receiver.byte_buffer[:60])}")
                    else:
                        logger.info("  Trying 'df' command as fallback...")
                        receiver.send_command("df\r\n")
                continue

            no_data_cnt = 0

            for line in lines:
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

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        receiver.disconnect()
        if records:
            save_to_file(records)
            print(f"\n✅ Saved {len(records)} records → {OUTPUT_FILE}")
        logger.info(f"Done. Total records: {msg_count}")


if __name__ == "__main__":
    run()
