"""activity_state axis (FROZEN): g-unit energy/cadence rule + gyro cycling branch.

classify(window) -> reading dict. Logic identical to the original live_hsi.py.
"""
import numpy as np

from core.config import FS, AS_LAG, T_STILL, T_RUN, BAND_LO, BAND_HI, CAD_RUN, T_GYRO
from core.features import body_accel, mag_g


def as_cadence(body_mag_g):
    """Cadence (Hz) = argmax of the autocorrelation over the lag band (frozen)."""
    m = body_mag_g - body_mag_g.mean()
    ac = np.correlate(m, m, mode="full")[len(m) - 1:]
    if ac[0] == 0:
        return np.nan
    ac = ac / ac[0]
    lo, hi = AS_LAG
    return FS / (lo + int(np.argmax(ac[lo:hi])))


def activity_confidence(movement, energy, cad, gyro_energy, label):
    """Deterministic margin proxy in [0.5,1.0] (distance to the deciding threshold).
    NOTE: a proxy, not the trained ECE-calibrated confidence from the notebook."""
    in_band = BAND_LO <= energy <= BAND_HI and movement >= T_STILL
    if label == "cycling":
        m = (gyro_energy - T_GYRO) / T_GYRO
    elif label == "sedentary":
        m = (T_STILL - movement) / T_STILL
    elif in_band:
        m = abs(cad - CAD_RUN) / CAD_RUN
    elif label == "running":
        m = (energy - T_RUN) / T_RUN
    else:                                            # walking
        m = (T_RUN - energy) / T_RUN
    return round(0.5 + 0.5 * float(np.clip(m, 0.0, 1.0)), 2)


def classify(w):
    body = body_accel(w)
    if body is None:
        return {"label": None, "note": "no accel/linear stream"}
    bm = mag_g(body)
    movement = float(bm.std())
    energy = float(bm.mean())
    cad = as_cadence(bm)
    gyro = w.get("gyro")
    gyro_energy = float(np.sqrt((gyro ** 2).sum(axis=1)).mean()) if gyro is not None else np.nan

    # accel rule: energy split with a cadence tiebreaker inside the walk/run band
    if movement < T_STILL:
        label = "sedentary"
    elif BAND_LO <= energy <= BAND_HI:
        label = "running" if cad >= CAD_RUN else "walking"
    else:
        label = "running" if energy >= T_RUN else "walking"
    # gyro cycling branch fires only in the still region
    cyc = (not np.isnan(gyro_energy)) and movement < T_STILL and gyro_energy > T_GYRO
    if cyc:
        label = "cycling"

    conf = activity_confidence(movement, energy, cad, gyro_energy, label)
    feats = f"move={movement:.2f}g energy={energy:.2f}g cad={cad:.2f}Hz"
    if not np.isnan(gyro_energy):
        feats += f" gyro={gyro_energy:.2f}rad/s"
    else:
        feats += " gyro=- (no gyro: cycling off)"
    return {"label": label, "conf": conf, "move": movement, "energy": energy, "gyro": gyro_energy, "note": feats}
