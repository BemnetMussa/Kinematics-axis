"""Presentation scoring -- shared by BOTH views (terminal dashboard + web page) so they always
show the SAME numbers. No new classification here: it only reads what the frozen axes already
decided and turns it into one consistent confidence scale.

Confidence model (grounded in how a calibrated binary classifier behaves -- see scikit-learn's
calibration docs): each axis reports a probability-like percentage where **50% = right at the
decision boundary** (maximum uncertainty for a yes/no call) and **100% = far from the boundary**
(certain). That is why the per-axis numbers live in 50-100%: a deterministic threshold rule sitting
exactly on its threshold genuinely is a coin flip.

The OVERALL confidence is the MINIMUM over the axes that actually drive the chosen situation -- the
combined read is "only as strong as its weakest ingredient" (overall_state.ipynb).
"""
import numpy as np

from core.config import LOCO_LAG, LOCO_STEP_T, MAG_DEV_T, INC_DEV_T
from core.features import body_accel, mag_g, autocorr_peak, magnetic_features


POSTURE_PCT = {"high": 90, "low": 50}      # posture exposes only high/low -> a representative %

# which axes actually drive each overall situation (mirrors overall_state.classify); the overall
# confidence is the min over these -- "only as strong as its weakest ingredient" (overall_state.ipynb).
CONTRIB = {
    "resting (lying)": ("posture",),
    "running":         ("locomotion", "activity"),
    "walking":         ("locomotion", "activity"),
    "in vehicle":      ("locomotion",),
    "cycling":         ("activity",),
    "restless":        ("regularity",),
    "still":           ("activity", "posture"),
}


def loco_pct(loco, w, calib):
    """Locomotion exposes no confidence, so derive one by measuring how far the deciding quantity
    sits past the SAME threshold the axis used (so it can never disagree with the chosen label),
    mapped to 50-100% like the other axes. Presentation only -- never changes a label."""
    label = loco.get("label")
    body = body_accel(w)
    if label is None or body is None:
        return None
    if label == "on_foot":
        margin = (autocorr_peak(mag_g(body), *LOCO_LAG) - LOCO_STEP_T) / LOCO_STEP_T
    elif w.get("mag") is not None and w.get("accel") is not None and calib.get("base_mag") is not None:
        mf = magnetic_features(w["mag"], w["accel"].mean(axis=0))
        ratio = max(abs(mf["field_mag"] - calib["base_mag"]) / MAG_DEV_T,
                    abs(mf["inclination"] - calib["base_inc"]) / INC_DEV_T)
        margin = (ratio - 1.0) if label == "in_vehicle" else (1.0 - ratio)   # vehicle: past; still: under
    else:
        return None
    return int(round(100 * (0.5 + 0.5 * float(np.clip(margin, 0.0, 1.0)))))


def confidence_pct(act, reg, pos, loco, w, calib):
    """One consistent 0-100% per axis, read from each axis's own certainty signal (None if it has none)."""
    return {
        "activity":   None if act.get("conf") is None else int(round(100 * act["conf"])),
        "regularity": None if reg.get("conf") is None else int(round(100 * reg["conf"])),
        "posture":    POSTURE_PCT.get(pos.get("confidence")),
        "locomotion": loco_pct(loco, w, calib),
    }


def overall_confidence(situation, pct):
    """The single headline confidence: the weakest axis that drives this situation. Returns
    (percent, limiting_axis_name), or (None, None) if no contributing axis reported a number."""
    contrib = CONTRIB.get(situation, ("activity", "posture", "locomotion"))
    pairs = [(name, pct[name]) for name in contrib if pct.get(name) is not None]
    if not pairs:
        return None, None
    limiter, value = min(pairs, key=lambda kv: kv[1])
    return value, limiter
