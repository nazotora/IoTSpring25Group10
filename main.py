########################################################################
# IoT Project: Home Information System
# main.py
# Group 10
# Drew Schultz, Robby Modica, Alex Viner, Tiger Slowinski
# Current sensor information collection and transmission program
# 3 Current sensors and an ESP32 for hardware talking to a Raspberry Pi
########################################################################

import time
import math
from machine import I2C, Pin
import network
from umqtt.simple import MQTTClient
import ads1x15
import secrets #WiFi and MQTT configurations

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
I2C_SDA       = 21      #GPIO21
I2C_SCL       = 22      #GPIO22
BURDEN_OHMS   = 20.0    #Burden resistor value in ohms between sensor leads
CT_RATIO      = 2000.0  #1:2000 transformer
AC_FREQUENCY  = 60.0    #Hz
DATA_RATE     = 860     #Samples per second
CALIBRATION   = 1.57    #6.25A device read 4.0A, real world variation correction

# ─── SETUP Wi‑Fi ────────────────────────────────────────────────────────────
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(secrets.ssid, secrets.password) #Pull from secrets file
while not wlan.isconnected():
    time.sleep(0.5)
print('Wi‑Fi connected, IP:', wlan.ifconfig())

# ─── SETUP MQTT ─────────────────────────────────────────────────────────────
client = MQTTClient(secrets.client_id, secrets.mqtt_broker, secrets.mqtt_port)
client.connect()

# ─── SETUP I²C & ADS1115 ────────────────────────────────────────────────────
i2c = I2C(1, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))

# Create ADC instances with simple names
ads_1 = ads1x15.ADS1115(i2c, address=0x48)  # First ADS1115
ads_2 = ads1x15.ADS1115(i2c, address=0x49)  # Second ADS1115

# List of (adc, differential_channel) pairs
channels = [
    (ads_1, 0),  # ADS1115 #1, AIN0-AIN1
    (ads_1, 1),  # ADS1115 #1, AIN2-AIN3
    (ads_2, 0)   # ADS1115 #2, AIN0-AIN1
]

# SAMPLES per AC cycle
SAMPLES_PER_CYCLE = max(1, int(DATA_RATE / AC_FREQUENCY))

# ─── RMS MEASUREMENT ─────────────────────────────────────────────────────────
#Differential voltage reading
def measure_v_rms(adc, diff_channel, samples):
    sum_sq = 0.0
    valid = 0
    for _ in range(samples):
        try:
            raw = adc.read_diff(diff_channel)  # Proper diff read
            voltage = raw * 4.096 / 32768
            sum_sq += voltage * voltage
            valid += 1
        except OSError:
            time.sleep(0.005)
    return math.sqrt(sum_sq / valid) if valid else 0.0

# ─── MAIN LOOP: SAMPLE & PUBLISH ─────────────────────────────────────────────
while True:
    start_ms = time.ticks_ms()
    for idx, (adc, diff_ch) in enumerate(channels, start=1):
        vrms = measure_v_rms(adc, diff_ch, SAMPLES_PER_CYCLE) #Voltage differential at ADC
        i_sec  = vrms / BURDEN_OHMS                           #Current calculation at ADC
        i_prim = i_sec * CT_RATIO * CALIBRATION               #Current calculation at current sensor
        topic  = b"home/ct/device%d" % idx
        payload = b"%.3f" % i_prim
        client.publish(topic, payload)
    elapsed = time.ticks_diff(time.ticks_ms(), start_ms)
    #One second intervals of sending sensor data
    if elapsed < 1000:
        time.sleep_ms(1000 - elapsed)