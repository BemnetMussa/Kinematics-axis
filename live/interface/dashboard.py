"""Terminal technical view: startup calibration and the per-window readings printout.

Pure refactor: calibrate() and run_once() are moved verbatim from the original live_hsi.py;
only the axis calls now go through the per-axis classify() functions (same logic).
"""
import time
import numpy as np

from core.config import G, SENSORS, ACT_SEC, WIN_SEC, CALIB_SEC, GET_READY_SEC, MAG_DEV_T, INC_DEV_T
from core.features import magnetic_features
from interface.sources import get_sensor_window, PhyphoxSource
from interface.web import _publish

from axes.activity_state import classify as classify_activity
from axes.movement_regularity import classify as classify_regularity
from axes.postural_state import classify as classify_postural
from axes.locomotion_state import classify as classify_locomotion
from axes.overall_state import classify as classify_overall


def calibrate(source):
    # The postural 'up' reference MUST be the gravity direction while the user is actually STANDING
    # with the phone in its deployment position (pocket) -- not whatever orientation it happens to be
    # in at startup. Otherwise a phone left flat reads tilt~0 from a flat reference and looks "standing".
    live = isinstance(source, PhyphoxSource)
    print("\nCalibration -- capturing your STANDING posture reference.")
    if live:
        print("  Put the phone in its deployment position (e.g. front trouser pocket),")
        print("  then STAND UP straight and hold still.")
    # Give the user time to get into position (live only), then capture the most recent CALIB_SEC.
    # Synthetic: ready = 0, so the capture window is unchanged from before.
    ready = GET_READY_SEC if live else 0.0
    t0 = source.now()
    announced = set()
    while source.now() - t0 < ready + CALIB_SEC:
        source.update()
        if live:
            left = ready + CALIB_SEC - (source.now() - t0)
            if left > CALIB_SEC:                          # still in the get-into-position phase
                sec = int(np.ceil(left - CALIB_SEC))
                if sec not in announced:
                    print(f"  stand with phone in pocket... capturing in {sec}s")
                    announced.add(sec)
            time.sleep(0.1)
    w = source.get_window(CALIB_SEC)                      # the most recent CALIB_SEC = the standing window
    calib = {"up": None, "base_mag": None, "base_inc": None}
    if w.get("accel") is not None:
        calib["up"] = w["accel"].mean(axis=0)             # gravity direction while standing (the reference)
        up_g = calib["up"] / G
        print(f"  standing 'up' reference: {np.round(up_g, 2)} g  (|.|={np.linalg.norm(up_g):.2f} g)")
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


def _magnetometer_diag(w, calib):
    if w.get("mag") is None or w.get("accel") is None:
        return None
    if calib.get("base_mag") is None or calib.get("base_inc") is None:
        return None
    mf = magnetic_features(w["mag"], w["accel"].mean(axis=0))
    dmag = abs(mf["field_mag"] - calib["base_mag"])
    dinc = abs(mf["inclination"] - calib["base_inc"])
    vehicle = dmag > MAG_DEV_T or dinc > INC_DEV_T
    return {
        "field_mag": mf["field_mag"],
        "field_var": mf["field_var"],
        "inclination": mf["inclination"],
        "base_mag": calib["base_mag"],
        "base_inc": calib["base_inc"],
        "dmag": dmag,
        "dinc": dinc,
        "vehicle": vehicle,
    }


def run_once(source, calib):
    w_act = get_sensor_window(ACT_SEC)
    w_long = get_sensor_window(WIN_SEC)
    avail = w_long.get("available", {})
    sensors_to_check = SENSORS + ["location"]
    flag = " ".join(f"{s}:{'ok' if avail.get(s) else '--'}" for s in sensors_to_check)
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

    # Speed diagnostics
    speed_raw = w_long.get("speed")
    speed_ms = np.mean(speed_raw) if speed_raw is not None else 0.0
    speed_kmh = speed_ms * 3.6

    av = act.get("label")
    print(f"  activity   : {str(av):12s}" + (f"(conf {act['conf']})" if av else "") + f" | {act['note']}")
    if speed_raw is not None:
        print(f"  gps/speed  : {speed_kmh:5.1f} km/h")
    rs = reg.get("score")
    print(f"  regularity : {(f'{rs:.2f}' if rs is not None else 'null'):12s}"
          + (f"(conf {reg['conf']})" if reg.get('conf') is not None else "") + f" | {reg['note']}")
    print(f"  postural   : {str(pos.get('label')):12s} | {pos['note']}")
    print(f"  locomotion : {str(loco.get('label')):12s} | {loco['note']}")

    mag = _magnetometer_diag(w_long, calib)
    if mag is None:
        print("  magnetometer: (unavailable or not calibrated)")
    else:
        verdict = "vehicle" if mag["vehicle"] else "baseline"
        print(
            "  magnetometer: "
            f"field={mag['field_mag']:.1f}uT base={mag['base_mag']:.1f} d={mag['dmag']:.1f} | "
            f"inc={mag['inclination']:.0f}deg base={mag['base_inc']:.0f} d={mag['dinc']:.0f} | "
            f"var={mag['field_var']:.1f} -> {verdict}"
        )

    # overall needs the three categorical axes; null regularity is treated as "calm", not a blocker
    if all(x.get("label") is not None for x in (act, pos, loco)):
        ov = classify_overall(act, reg, pos, loco)
        print(f"  overall    : {ov['situation']:12s} | exertion={ov['exertion']} | HR: {ov['note']}")
    else:
        ov = None
        missing = [n for n, x in (("activity", act), ("postural", pos), ("locomotion", loco)) if x.get("label") is None]
        print(f"  overall    : (skipped: {', '.join(missing)} unavailable)")
    print()
    _publish(source, act, reg, pos, loco, ov, mag)        # mirror to the web view (presentation only)
