#!/usr/bin/env python3
import serial
import sys
import json
import os
import time
import subprocess
import tempfile
import socket


SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 2400
COMMAND = b"Q1\r"
CACHE_FILE = "/tmp/ups_cache.json"
CACHE_TTL = 120  # seconds

ZABBIX_SERVER = "192.168.1.200"         # Replace with your Zabbix server IP
ZABBIX_HOSTNAME = "UPSMonitor"        # Replace with your actual Zabbix host name

# based on UPS Data. for 16*12v battery this is the number
BATTERY_HIGH = 208.00
BATTERY_LOW = 166.40

STATUS_FLAGS = {
    "utility_fail":       7,
    "battery_low":        6,
    "boost_buck_active":  5,
    "ups_failed":         4,
    "ups_type_standby":   3,
    "test_in_progress":   2,
    "shutdown_active":    1,
    "beeper_on":          0
}

def parse_status_bits(bits):
    if len(bits) != 8 or not all(c in '01' for c in bits):
        return {}
    return {name: int(bits[7 - pos]) for name, pos in STATUS_FLAGS.items()}

def parse_ups_response(response):
    if not response.startswith("("):
        return None
    try:
        parts = response.strip("()\r\n").split()
        if len(parts) != 8:
            return None

        input_voltage     = float(parts[0])
        input_fault       = float(parts[1])
        output_voltage    = float(parts[2])
        output_current    = int(parts[3])
        input_freq        = float(parts[4])
        battery_voltage   = float(parts[5])
        temperature       = float(parts[6])
        status_raw        = parts[7]
        status_flags      = parse_status_bits(status_raw)

        battery_total_voltage = battery_voltage * 96.90265487
        battery_percent = int(max(0, min(100, ((battery_total_voltage - BATTERY_LOW) / (BATTERY_HIGH - BATTERY_LOW)) * 100)))

        return {
            "input_voltage": input_voltage,
            "input_fault_voltage": input_fault,
            "output_voltage": output_voltage,
            "output_current_percent": output_current,
            "input_frequency": input_freq,
            "battery_voltage": battery_voltage,
            "battery_voltage_all": round(battery_voltage * 96.90265487, 2),
            "temperature": temperature,
            "battery_charge": battery_percent,
            **status_flags
        }
    except Exception:
        return None

def read_from_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data["timestamp"] < CACHE_TTL:
            return data["values"]
    except:
        pass
    return None

def write_to_cache(values):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "timestamp": time.time(),
                "values": values
            }, f)
    except:
        pass

def query_ups():
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=3) as ser:
            ser.write(COMMAND)
            line = ser.readline().decode(errors="ignore").strip()
            return parse_ups_response(line)
    except:
        return None

def get_ups_data():
    cached = read_from_cache()
    if cached:
        return cached

    fresh = query_ups()
    if fresh:
        write_to_cache(fresh)
        return fresh

    return None

def send_all_to_zabbix(data, hostname=None, zabbix_server="127.0.0.1"):
    if not hostname:
       hostname = socket.gethostname()
       print("Hostname Incorrect")

    try:
        with tempfile.NamedTemporaryFile("w", delete=False) as temp_file:
            for key, value in data.items():
                if isinstance(value, (int, float, str)):
                    temp_file.write(f"{hostname} {key} {value}\n")
            temp_file_path = temp_file.name

        proc = subprocess.run(
            ["zabbix_sender", "-z", zabbix_server, "-i", temp_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        print(proc.stdout.decode())
        if proc.returncode != 0:
            print(proc.stderr.decode())

    except Exception as e:
        print(f"Error sending to Zabbix: {e}")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def main():
    if len(sys.argv) != 2:
        print("Usage: ups_cache.py <key>")
        sys.exit(1)

    key = sys.argv[1]
    print(key)
    # Cache Update
    if key == "update_cache":
        fresh = query_ups()
        if fresh:
            write_to_cache(fresh)
            print("OK")
        else:
            print("FAILED")
        sys.exit(0)

    #Zabbix Trapper
    if key == "send_to_zabbix":
        data = get_ups_data()
        if data:
            send_all_to_zabbix(data, hostname=ZABBIX_HOSTNAME, zabbix_server=ZABBIX_SERVER)
        else:
            print("No UPS data to send.")
        sys.exit(0)

    data = get_ups_data()
    if data and key in data:
        print(data[key])
    else:
        print("Error getting Data")

if __name__ == "__main__":
    main()
