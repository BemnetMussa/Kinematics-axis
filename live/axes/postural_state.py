"""postural_state axis (FROZEN thigh/pocket rework): MOVE_T in g + thigh tilt model.

classify(window, calib) -> reading dict. Logic identical to the original live_hsi.py.
(calib carries the per-startup standing 'up' reference.)
"""
import numpy as np

from core.config import G, MOVE_T_G, SIT_STAND_T, FLAT_T, MICRO_FLOOR_G
from core.features import ang_between


def thigh_posture(movement_g, tilt):
    if movement_g > MOVE_T_G:
        return "in_motion"
    if tilt < SIT_STAND_T:
        return "standing"
    if tilt < FLAT_T:
        return "sitting"
    return "device_resting" if movement_g < MICRO_FLOOR_G else "lying"   # CHANGE 3: UNTESTED


def classify(w, calib):
    if w.get("accel") is None:
        return {"label": None, "confidence": None, "note": "no raw-accel stream"}
    if calib.get("up") is None:
        return {"label": None, "confidence": None, "note": "not calibrated (no 'up' reference)"}
    total = w["accel"] / G                            # raw accel in g (gravity retained)
    movement_g = float(np.sqrt((total ** 2).sum(axis=1)).std())
    # tilt = angle from the calibrated STANDING reference: ~0 standing, ~25-85 sitting (thigh flexed),
    # ~90 flat (lying / phone on a surface). A correct 'up' makes a flat phone large-tilt, not "standing".
    tilt = ang_between(total.mean(axis=0), calib["up"])
    label = thigh_posture(movement_g, tilt)
    # The flat branch (lying vs device_resting) is UNTESTED on real data and the two overlap in tilt,
    # so report low confidence rather than asserting it; the validated classes stay high-confidence.
    if label in ("lying", "device_resting"):
        confidence = "low"
        note = (f"tilt={tilt:.0f}deg (thigh) move={movement_g:.3f}g  "
                f"UNTESTED (flat: lying vs device_resting), low confidence")
    else:
        confidence = "high"
        note = f"tilt={tilt:.0f}deg (thigh) move={movement_g:.3f}g"
    return {"label": label, "tilt": tilt, "confidence": confidence, "note": note}
