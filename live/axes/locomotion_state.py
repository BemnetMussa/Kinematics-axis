"""locomotion_state axis (FROZEN loop-2 rule): gravity-only magnetometer with a
self-calibrated baseline; on_foot via rhythm, else stationary vs in_vehicle.

classify(window, calib) -> reading dict. Logic identical to the original live_hsi.py.
(calib carries the per-startup magnetometer baseline.)
"""
import numpy as np

from core.config import MAG_DEV_T, INC_DEV_T, LOCO_STEP_T, LOCO_MOVE_FLOOR_G, LOCO_LAG
from core.features import body_accel, mag_g, autocorr_peak, magnetic_features


def classify(w, calib):
    body = body_accel(w)
    if body is None:
        return {"label": None, "note": "no accel/linear stream"}
    bm = mag_g(body)
    movement = float(bm.std())
    rhythm = autocorr_peak(bm, *LOCO_LAG)
    if rhythm > LOCO_STEP_T and movement > LOCO_MOVE_FLOOR_G:
        return {"label": "on_foot", "note": f"rhythm={rhythm:.2f} move={movement:.3f}g"}

    # low / non-rhythmic body motion -> stationary vs in_vehicle by the magnetometer
    if w.get("mag") is None or w.get("accel") is None:
        return {"label": None, "note": "stationary/vehicle needs magnetometer + raw accel"}
    if calib.get("base_mag") is None:
        return {"label": None, "note": "magnetometer baseline not calibrated"}
    mf = magnetic_features(w["mag"], w["accel"].mean(axis=0))
    dmag = abs(mf["field_mag"] - calib["base_mag"])
    dinc = abs(mf["inclination"] - calib["base_inc"])
    vehicle = dmag > MAG_DEV_T or dinc > INC_DEV_T
    label = "in_vehicle" if vehicle else "stationary"
    note = (f"field_mag={mf['field_mag']:.1f}uT base={calib['base_mag']:.1f} d={dmag:.1f} | "
            f"inc={mf['inclination']:.0f}deg base={calib['base_inc']:.0f} d={dinc:.0f} (gravity-only, no quat)")
    return {"label": label, "note": note}
