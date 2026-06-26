"""movement_regularity axis (FROZEN, pocket-normalized): unbiased autocorrelation,
argmax dominant period (FIX 2), movement floor in g (FIX 1).

classify(window) -> reading dict. Logic identical to the original live_hsi.py.
"""
import numpy as np

try:
    from scipy.signal import find_peaks
except Exception:                                   # scipy is required for the prominence term
    find_peaks = None

from core.config import (LAG_MIN, LAG_MAX, LONG_WIN, PEAK_PROMINENCE, MOVEMENT_FLOOR_G,
                         MIN_CYCLES_STRIDE, PROM_FULL, ACC_MAX, MAX_BAD_FRAC)
from core.features import body_accel, mag_g


def _fill_gaps(mag, bad):
    mag = mag.copy()
    for i in range(1, len(mag)):
        if bad[i]:
            mag[i] = mag[i - 1]
    return mag


def reg_confidence(prom, ncyc):
    cyc = np.clip((ncyc - MIN_CYCLES_STRIDE) / (5.0 - MIN_CYCLES_STRIDE), 0.0, 1.0)
    prm = np.clip(prom / PROM_FULL, 0.0, 1.0)
    return round(float(np.sqrt(cyc * prm)), 3)


def classify(w):
    body = body_accel(w)
    if body is None:
        return {"score": None, "note": "no accel/linear stream"}
    window = mag_g(body)
    bad = np.isnan(window) | (window > ACC_MAX)
    if bad.mean() > MAX_BAD_FRAC or bad[0]:
        return {"score": None, "reason": "window_unreliable", "note": "window_unreliable"}
    mag = _fill_gaps(window, bad)
    movement = float(mag.std())
    x = mag - mag.mean()
    n = len(x)
    ac = np.correlate(x, x, mode="full")[n - 1:n + LAG_MAX] / (n - np.arange(LAG_MAX + 1))   # unbiased
    if ac[0] <= 0:
        return {"score": None, "reason": "window_unreliable", "note": "flat window"}
    ac = ac / ac[0]
    lag = LAG_MIN + int(np.argmax(ac[LAG_MIN:LAG_MAX + 1]))           # FIX 2: argmax dominant period
    score = float(np.clip(ac[lag], 0.0, 1.0))
    prom = 0.0
    if find_peaks is not None:
        peaks, props = find_peaks(ac, prominence=PEAK_PROMINENCE)
        if lag in list(peaks):
            prom = float(props["prominences"][list(peaks).index(lag)])
    ncyc = LONG_WIN / lag
    if movement < MOVEMENT_FLOOR_G:
        reason = "low_movement"
    elif ncyc < MIN_CYCLES_STRIDE:
        reason = "insufficient_cycles"
    else:
        reason = "valid"
    valid = reason == "valid"
    conf = reg_confidence(prom, ncyc) if valid else None
    note = f"autocorr_peak={score:.2f} lag={lag} cycles={ncyc:.1f}" if valid else f"null:{reason} (move={movement:.3f}g)"
    return {"score": round(score, 3) if valid else None, "reason": reason, "conf": conf, "note": note}
