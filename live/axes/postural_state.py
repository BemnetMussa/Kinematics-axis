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
        return {"label": None, "note": "no raw-accel stream"}
    if calib.get("up") is None:
        return {"label": None, "note": "not calibrated (no 'up' reference)"}
    total = w["accel"] / G                            # raw accel in g (gravity retained)
    movement_g = float(np.sqrt((total ** 2).sum(axis=1)).std())
    tilt = ang_between(total.mean(axis=0), calib["up"])
    label = thigh_posture(movement_g, tilt)
    flag = " UNTESTED" if label in ("lying", "device_resting") else ""
    return {"label": label, "tilt": tilt,
            "note": f"tilt={tilt:.0f}deg (thigh) move={movement_g:.3f}g{flag}"}
