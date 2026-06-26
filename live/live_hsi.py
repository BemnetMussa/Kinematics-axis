#!/usr/bin/env python3
"""
live_hsi.py - the five kinematic readings, live, from ONE phone sensor stream.

Thin entry point. Wires: a swappable SOURCE -> shared 50 Hz buffer -> the five frozen axes
-> two views (terminal technical dashboard + human-facing web page). All logic lives in the
modules; nothing here classifies.

  axes/         activity_state, movement_regularity, postural_state, locomotion_state, overall_state
  core/         config (all thresholds/constants), features (shared math)
  interface/    sources (phyphox + synthetic), dashboard (terminal view), web (HTML human view)

The five readings (all FROZEN, pulled from the prior work, NOT the original chest notebooks):
  activity_state       categorical : sedentary / walking / running / cycling   (vigorous unmodeled)
  movement_regularity  continuous  : score in [0,1], higher = more regular
  postural_state       categorical : standing / sitting / in_motion / lying / device_resting
  locomotion_state     categorical : stationary / on_foot / in_vehicle  (self-calibrated magnetometer)
  overall_state        combined    : the four concatenated -> situation + exertion + heart-rate note

Sensors (phyphox over WiFi; enable 'Allow remote access'):
  accelerometer (raw, with g), linear acceleration, gyroscope, magnetometer, gravity.
A missing sensor degrades/skips its axis with a printed note instead of crashing the loop.

Run live:     .venv/bin/python live/live_hsi.py http://192.168.x.x:8080
Run offline:  .venv/bin/python live/live_hsi.py --synthetic        (no phone; replays canned states)
"""
import sys
import time

from core.config import WEB_PORT, PRINT_EVERY
from interface.sources import PhyphoxSource, SyntheticSource, set_source
from interface.web import start_web
from interface.dashboard import calibrate, run_once


def main():
    args = sys.argv[1:]
    synthetic = "--synthetic" in args or "--demo" in args
    steps = None
    if "--steps" in args:
        steps = int(args[args.index("--steps") + 1])

    if synthetic:
        drop = set()
        if "--drop" in args:
            drop = set(args[args.index("--drop") + 1].split(","))    # e.g. --drop mag,gyro
        print(f"SOURCE: synthetic replay (no phone)." + (f" dropping: {sorted(drop)}" if drop else ""))
        source = SyntheticSource(drop=drop)
        steps = steps or 60
    else:
        url = next((a for a in args if a.startswith("http")), None) or \
              input("phyphox remote URL (e.g. http://192.168.0.42:8080): ").strip()
        print(f"SOURCE: phyphox {url}")
        source = PhyphoxSource(url)

    set_source(source)

    try:
        start_web(WEB_PORT)
        print(f"\nHuman view: open  http://localhost:{WEB_PORT}   (this terminal keeps the technical view)")
    except Exception as e:
        print(f"  [warn] web view could not start on port {WEB_PORT}: {e}")

    calib = calibrate(source)

    print("Streaming five kinematic readings (Ctrl-C to stop):\n")
    n = 0
    try:
        while steps is None or n < steps:
            source.update()
            run_once(source, calib)
            n += 1
            if not synthetic:
                time.sleep(PRINT_EVERY)
            if synthetic and source.now() >= source.tmax:
                break
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
