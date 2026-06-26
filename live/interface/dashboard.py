"""Terminal technical view: startup calibration and the per-window readings printout.

Pure refactor: calibrate() and run_once() are moved verbatim from the original live_hsi.py;
only the axis calls now go through the per-axis classify() functions (same logic).
"""
import time
import numpy as np

from core.config import G, SENSORS, ACT_SEC, WIN_SEC, CALIB_SEC
from core.features import magnetic_features
from interface.sources import get_sensor_window, PhyphoxSource
from interface.web import _publish

from axes.activity_state import classify as classify_activity
from axes.movement_regularity import classify as classify_regularity
from axes.postural_state import classify as classify_postural
from axes.locomotion_state import classify as classify_locomotion
from axes.overall_state import classify as classify_overall


def calibrate(source):
    print(f"\nCalibration: hold the phone still and stand upright for ~{CALIB_SEC:.0f}s ...")
    # warm up the buffer, then read one stationary window
    t0 = source.now()
    while source.now() - t0 < CALIB_SEC:
        source.update()
        if isinstance(source, PhyphoxSource):
            time.sleep(0.1)
    w = source.get_window(CALIB_SEC)
    calib = {"up": None, "base_mag": None, "base_inc": None}
    if w.get("accel") is not None:
        calib["up"] = w["accel"].mean(axis=0)             # gravity direction while standing
        print(f"  postural 'up' reference set: {np.round(calib['up'] / G, 2)} g")
    else:
        print("  [skip] no raw accel -> postural cannot calibrate 'up'")
    if w.get("mag") is not None and w.get("accel") is not None:
        mf = magnetic_features(w["mag"], w["accel"].mean(axis=0))
        calib["base_mag"] = mf["field_mag"]; calib["base_inc"] = mf["inclination"]
        print(f"  locomotion magnetometer baseline: field_mag={mf['field_mag']:.1f}uT inc={mf['inclination']:.0f}deg")
    else:
        print("  [skip] no magnetometer -> locomotion stationary/vehicle baseline unavailable")
    print("Calibration done.\n")
    return calib


def run_once(source, calib):
    w_act = get_sensor_window(ACT_SEC)
    w_long = get_sensor_window(WIN_SEC)
    avail = w_long.get("available", {})
    flag = " ".join(f"{s}:{'ok' if avail.get(s) else '--'}" for s in SENSORS)
    print(f"[t={source.now():5.1f}s]  sensors: {flag}")

    def safe(name, fn):
        try:
            return fn()
        except Exception as e:                            # one axis breaking must not kill the loop
            print(f"  {name:11s}: [ERROR] {type(e).__name__}: {e}")
            return {"label": None, "score": None, "note": "error"}

    act = safe("activity",   lambda: classify_activity(w_act))
    reg = safe("regularity", lambda: classify_regularity(w_long))
    pos = safe("postural",   lambda: classify_postural(w_long, calib))
    loco = safe("locomotion", lambda: classify_locomotion(w_long, calib))

    av = act.get("label")
    print(f"  activity   : {str(av):12s}" + (f"(conf {act['conf']})" if av else "") + f" | {act['note']}")
    rs = reg.get("score")
    print(f"  regularity : {(f'{rs:.2f}' if rs is not None else 'null'):12s}"
          + (f"(conf {reg['conf']})" if reg.get('conf') is not None else "") + f" | {reg['note']}")
    print(f"  postural   : {str(pos.get('label')):12s} | {pos['note']}")
    print(f"  locomotion : {str(loco.get('label')):12s} | {loco['note']}")

    # overall needs the three categorical axes; null regularity is treated as "calm", not a blocker
    if all(x.get("label") is not None for x in (act, pos, loco)):
        ov = classify_overall(act, reg, pos, loco)
        print(f"  overall    : {ov['situation']:12s} | exertion={ov['exertion']} | HR: {ov['note']}")
    else:
        ov = None
        missing = [n for n, x in (("activity", act), ("postural", pos), ("locomotion", loco)) if x.get("label") is None]
        print(f"  overall    : (skipped: {', '.join(missing)} unavailable)")
    print()
    _publish(source, act, reg, pos, loco, ov)        # mirror to the web view (presentation only)
