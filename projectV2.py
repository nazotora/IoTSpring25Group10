############################################################
# IoT Project: Home Information System
# projectV2.py
# Group 10
# Drew Schultz, Robby Modica, Alex Viner, Tiger Slowinski
############################################################

# Need virtual environment before running program

import os
import time
import threading
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sense_hat import SenseHat
import RTIMU

import requests
import schedule
import paho.mqtt.client as mqtt
from influxdb_client_3 import InfluxDBClient3, Point
import secrets

# ─── CONFIG ──────────────────────────────────────────────────────────────────
#
# "secret information, wifi, IP's, Database keys...
#

OFFSET_TEMP   = 20  #Offset temp for indoor temp sensor degrees F

LAT = "null"
LONG = "null"


warning_active = False
warning_lock   = threading.Lock()
sense = SenseHat()
sense.clear()

def lookup_zip(ZIP_CODE):
    r = requests.get(f"http://api.zippopotam.us/us/{ZIP_CODE}", timeout=5)
    r.raise_for_status()
    place = r.json()["places"][0]
    return float(place["latitude"]), float(place["longitude"])

LAT, LONG = lookup_zip(ZIP_CODE)

lookup_zip(ZIP_CODE)

# ─── SETUP INFLUXDB CLIENT ────────────────────────────────────────────────

influx = InfluxDBClient3(
    host=INFLUX_URL,
    database=INFLUX_BUCKET,
    token=INFLUX_TOKEN
)

# ─── MQTT CALLBACK FOR CURRENT SENSORS ─────────────────────────────────────

def on_message(client, userdata, msg):
    device = msg.topic.split('/')[-1]
    try:
        amps = float(msg.payload)
    except ValueError:
        print(f"Invalid payload on {msg.topic}: {msg.payload}")
        return

    # Use local time for MQTT points too
    ts = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0)
    point = (
        Point("ct_current")
        .tag("device", device)
        .field("amps_rms", amps)
        .time(ts)
    )
    influx.write(record=point, write_precision="s")
    print(f"{ts.isoformat()} {device}: {amps:.3f}A → InfluxDB")

    #Trigger warning idicator
    if amps >= 13.5:
        activate_warning()

# ─── WEATHER TEMPERATURE ─────────────────────────────────────────────────

async def get_current_temp():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LONG}"
        "&current_weather=true"
        "&temperature_unit=fahrenheit"
        "&timezone=America/Chicago"
    )
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    data   = resp.json()
    temp_f = data["current_weather"]["temperature"]
    ts     = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0)

    # build & write the InfluxDB point
    point = (
        Point("weather")
        .tag("zip", ZIP_CODE)
        .field("temperature_f", float(temp_f))
        .time(ts)
    )
    influx.write(record=point, write_precision="s")
    print(f"{ts.isoformat()} → Weather: {temp_f}°F")

def job_weather():
    asyncio.run(get_current_temp())

# ─── SENSE HAT INDOOR-TEMP  ───────────────────────────────────────────────────

async def fetch_and_write_indoor():
    temp_c = sense.get_temperature()
    temp_f = temp_c * 9.0/5.0 + 32.0 - OFFSET_TEMP
    # Use local time stamped to minute
    ts = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0)

    point = (
        Point("indoor_temp")
        .tag("location", "indoor")
        .field("temperature_f", float(temp_f))
        .time(ts)
    )
    influx.write(record=point, write_precision="s")
    print(f"{ts.isoformat()} → Indoor: {temp_f:.2f}°F")

def job_indoor():
    # run the async function in its own loop
    asyncio.run(fetch_and_write_indoor())

# ─── BACKGROUND SCHEDULER THREAD ─────────────────────────────────────────────

# schedule weather data every 15 minutes, on the :00 mark
schedule.every(1).hour.do(job_weather)

# Schedule indoor every minute
schedule.every(1).minutes.do(job_indoor)

# Also do one immediately at startup
job_weather()
job_indoor()

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

threading.Thread(target=run_scheduler, daemon=True).start()

# ─── Notification Display ─────────────────────────────────────────────────

def warning_indication():
    #Show the "!" on the Sense HAT.
    R = [255,   0,   0]     #Color Red
    W = [255, 255, 255]     #Color White
    pixels = [
        R,R,R,R,R,R,R,R,
        R,R,R,W,W,R,R,R,
        R,R,R,W,W,R,R,R,
        R,R,R,W,W,R,R,R,
        R,R,R,W,W,R,R,R,
        R,R,R,R,R,R,R,R,
        R,R,R,W,W,R,R,R,
        R,R,R,R,R,R,R,R,
    ]
    sense.low_light = True
    sense.set_pixels(pixels)

# ─── OVERCURRENT WARNING ACTIVATION ───────────────────────────────────────

def activate_warning():
    #Show warning, schedule auto‐clear in 18 hours, and flip the flag.
    global warning_active
    with warning_lock:
        if warning_active:
            return
        warning_active = True

    print(f"[{time.strftime('%X')}] WARNING: current ≥6 A, lighting display")
    warning_indication()

    # schedule auto‐clear in 18 hours (18*3600 seconds)
    t = threading.Timer(18*3600, clear_warning)
    t.daemon = True
    t.start()

# ─── JOYSTICK LISTENER ────────────────────────────────────────────────────

def joystick_watcher():
    while True:
        for evt in sense.stick.get_events():
            if evt.action=='pressed' and evt.direction=='middle':
                clear_warning()
        time.sleep(0.1)

threading.Thread(target=joystick_watcher, daemon=True).start()

# ─── WARNING CLEARING ────────────────────────────────────────────────────

def clear_warning():
    #Clear the warning display and reset state.
    global warning_active
    with warning_lock:
        if not warning_active:
            return
        warning_active = False
    sense.clear()


# ─── LAUNCH GRAFANA ──────────────────────────────────────────────────────────

os.system(
   'chromium-browser --noerrdialogs --disable-session-crashed-bubble '
   'https://drewschultz.grafana.net/ &'
)

# ─── MAIN: CONNECT MQTT & LOOP ───────────────────────────────────────────────

def main():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(MQTT_TOPICS)
    print("Subscribed to:", [t for t, _ in MQTT_TOPICS])
    client.loop_forever()

if __name__ == "__main__":
    main()
