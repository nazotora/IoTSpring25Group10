"""
Reads CT burden‐resistor voltage differentially, computes Vrms and primary current.
Automatically sets the max data rate, aligns sample count, and retries on I²C errors.
"""

import time, math
import board, busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# ─── USER CONFIG ────────────────────────────────────────────────────────────

AC_FREQUENCY      = 60.0      # mains frequency (Hz)
BURDEN_OHMS       = 20.0      # ohms
CT_RATIO          = 2000.0    # primary : secondary turns
PGA               = 1         # gain (±4.096 V)
# ─────────────────────────────────────────────────────────────────────────────

# Set up I²C + ADS1115
i2c   = busio.I2C(board.SCL, board.SDA)
ads   = ADS.ADS1115(i2c, address=0x48)
ads.gain      = PGA
ads.data_rate = 860

# differential channel A0 (+) / A1 (–)
diff_chan = AnalogIn(ads, ADS.P0, ADS.P1)

# figure out how many samples we can actually get per cycle
SAMPLES_PER_CYCLE = max(1, int(ads.data_rate / AC_FREQUENCY))

def measure_v_rms(samples):
    sum_sq = 0.0
    valid  = 0
    for _ in range(samples):
        try:
            v = diff_chan.voltage
        except OSError as e:
            print("I2C read error, retrying…", e)
            time.sleep(0.005)
            continue
        sum_sq += v * v
        valid  += 1
    return math.sqrt(sum_sq / valid) if valid else 0.0

def main():
    period = 1.0  # seconds per measurement
    print(f"→ Sampling at {ads.data_rate} SPS → {SAMPLES_PER_CYCLE} samples/cycle")
    try:
        while True:
            t0 = time.monotonic()
            vrms   = measure_v_rms(SAMPLES_PER_CYCLE)
            i_sec  = vrms / BURDEN_OHMS
            i_prim = i_sec * CT_RATIO
            if i_prim > .05:
                print(f"Current: {i_prim:6.3f} A")
            else: 
                print(f"Current: {0} A")
                
            # sleep the remainder of the 1-second period
            elapsed = time.monotonic() - t0
            to_sleep = period - elapsed
            if to_sleep > 0:
                time.sleep(to_sleep)
    except KeyboardInterrupt:
        print("\nDone.")

if __name__ == "__main__":
    main()
