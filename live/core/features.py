"""Shared feature extraction reused across axes: body acceleration, magnitude (g),
autocorrelation peak, vector angle, and magnetometer de-rotation.

Pure refactor: each function is moved verbatim from the original live_hsi.py.
"""
import numpy as np

try:
    from scipy.signal import butter, filtfilt
except Exception:                                   # scipy is required for the gravity-removal fallback
    butter = filtfilt = None

from core.config import G, FS


def body_accel(w):
    """Body acceleration (m/s^2, gravity removed). Prefer the linear-accel sensor; else low-pass the raw accel."""
    if w.get("lin") is not None:
        return w["lin"]
    if w.get("accel") is not None and filtfilt is not None:
        b, a = butter(3, 0.3 / (FS / 2), btype="low")
        return w["accel"] - filtfilt(b, a, w["accel"], axis=0)
    if w.get("accel") is not None:
        return w["accel"] - w["accel"].mean(axis=0)      # crude DC removal if scipy is unavailable
    return None


def mag_g(body):
    """Magnitude of body acceleration, in g."""
    return np.sqrt((body ** 2).sum(axis=1)) / G


def autocorr_peak(x, lo, hi):
    """Biased-autocorrelation peak of a 1-D signal over a lag band (used for on_foot rhythm)."""
    m = x - x.mean()
    ac = np.correlate(m, m, mode="full")[len(m) - 1:]
    return 0.0 if ac[0] == 0 else float((ac / ac[0])[lo:hi].max())


def ang_between(u, v):
    """Angle (deg) between two vectors."""
    u = u / (np.linalg.norm(u) + 1e-9)
    v = v / (np.linalg.norm(v) + 1e-9)
    return float(np.degrees(np.arccos(np.clip(u @ v, -1.0, 1.0))))


def magnetic_features(mag, gravity):
    """Field magnitude/variance always; gravity-only inclination (declination NaN: no quaternion)."""
    m = np.sqrt((mag ** 2).sum(axis=1))
    out = {"field_mag": float(m.mean()), "field_var": float(m.std()), "inclination": np.nan}
    down = -gravity / (np.linalg.norm(gravity) + 1e-9)              # accel reads "up"; down = -up
    Bm = mag.mean(axis=0)
    b_vert = Bm @ down
    b_horiz = np.linalg.norm(Bm - b_vert * down)
    out["inclination"] = float(np.degrees(np.arctan2(b_vert, b_horiz)))
    return out
