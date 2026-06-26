#!/usr/bin/env python3
"""
live_hsi.py - the five kinematic readings, live, from ONE phone sensor stream.

Integrates all five kinematic axes into one deterministic pipeline reading one stream:
  activity_state       categorical : sedentary / walking / running / cycling   (vigorous unmodeled)
  movement_regularity  continuous  : score in [0,1], higher = more regular
  postural_state       categorical : standing / sitting / in_motion / lying / device_resting  (thigh/pocket rework)
  locomotion_state     categorical : stationary / on_foot / in_vehicle         (self-calibrated magnetometer)
  overall_state        combined    : the four concatenated -> situation + exertion + heart-rate note

All axis logic is FROZEN and pulled from the prior work, NOT the original chest notebooks:
  - activity_state         : g-unit thresholds + gyro cycling branch (activity_state.ipynb)
  - movement_regularity    : pocket-normalized (floor in g, argmax dominant period) (convergence_test FIX 1/2)
  - postural_state         : thigh tilt model (MOVE_T in g, SIT_STAND_T) (convergence_test thigh rework)
  - locomotion_state       : gravity-only magnetometer with a self-calibrated baseline (locomotion_improved loop 2)
  - overall_state          : situation / exertion / heart-note mapping (overall_state.ipynb)
Nothing is retrained. Every threshold lives in the CONFIG block below so it is easy to tweak
when reality disagrees. Thresholds carried from one placement/dataset are flagged PROVISIONAL.

The input is a single swappable function get_sensor_window(seconds) -> dict of arrays, so the
SOURCE (live phone now, recorded CSV later) can change without touching the axes. A missing
sensor degrades or skips its axis with a printed note instead of crashing the loop.

Sensors used (phyphox over WiFi; enable 'Allow remote access'):
  accelerometer WITH g (raw)         -> postural gravity direction, locomotion gravity vector
  linear acceleration (gravity-free) -> activity, regularity, locomotion movement/rhythm
  gyroscope                          -> activity cycling branch
  magnetometer                       -> locomotion stationary-vs-vehicle

Run live:     .venv/bin/python live/live_hsi.py http://192.168.x.x:8080
Run offline:  .venv/bin/python live/live_hsi.py --synthetic        (no phone; replays canned states)
"""
import sys
import time
import json
import threading
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from scipy.signal import find_peaks, butter, filtfilt
except Exception:                                   # scipy is required for regularity peaks / gravity fallback
    find_peaks = butter = filtfilt = None

# ============================================================================
# CONFIG  -- every threshold for all five axes, grouped by axis.
# ============================================================================
G  = 9.81                       # m/s^2 per g
FS = 50                         # shared pipeline rate (Hz); everything resampled to this

ACT_SEC  = 2.56                 # activity_state window (s) -> 128 samples
WIN_SEC  = 5.0                  # regularity / postural / locomotion window (s) -> 250 samples
ACT_WIN  = int(ACT_SEC * FS)
LONG_WIN = int(WIN_SEC * FS)
PRINT_EVERY = 1.0               # seconds between readings (live)
CALIB_SEC   = 5.0               # stationary baseline collected at startup
WEB_PORT    = 8090              # human-facing web view (terminal dashboard is unchanged)

# ---- activity_state (FROZEN; magnitude features in g; derived on MotionSense) ----
T_STILL = 0.10                  # std of |body accel| (g) below this -> sedentary
T_RUN   = 1.00                  # mean of |body accel| (g) above this while moving -> running
BAND_LO = 0.77                  # walk/run energy overlap band, lower edge (g)
BAND_HI = 1.07                  # walk/run energy overlap band, upper edge (g)
CAD_RUN = 1.20                  # PROVISIONAL: cadence (Hz) splitting walk/run inside the band
T_GYRO  = 0.18                  # PROVISIONAL: gyro energy (rad/s) in the still region -> cycling
AS_LAG  = (10, 64)              # cadence autocorr lag band at 50 Hz

# ---- movement_regularity (FROZEN, pocket-normalized from convergence_test) ----
LAG_MIN, LAG_MAX = 10, 100      # autocorr lag search band
PEAK_PROMINENCE  = 0.05
MOVEMENT_FLOOR_G = 0.5 / G      # FIX 1: chest 0.5 m/s^2 expressed in g (~0.051)
MIN_CYCLES_STRIDE = 3.5         # FIX 2: stride-period adequacy (was 7 step-periods on chest)
PROM_FULL = 1.5                 # prominence at which the confidence prominence term saturates
ACC_MAX   = 16 * G              # saturation guard (kept from frozen rule)
MAX_BAD_FRAC = 0.5

# ---- postural_state thigh/pocket rework (FROZEN from convergence_test) ----
MOVE_T_G    = 1.0 / G           # CHANGE 1: chest MOVE_T m/s^2 -> g (~0.102); above -> in_motion
SIT_STAND_T = 25.0             # CHANGE 2 (validated): thigh tilt (deg) splitting standing(<) / sitting(>)
FLAT_T      = 85.0             # CHANGE 3 (UNTESTED): tilt (deg) at/above which the thigh is "flat"
MICRO_FLOOR_G = 0.002         # CHANGE 3 (UNTESTED): movement (g) below which flat = device_resting, not lying

# ---- locomotion_state (FROZEN from locomotion_improved loop 2; gravity-only, self-cal baseline) ----
MAG_DEV_T   = 14.0            # PROVISIONAL: |field magnitude - baseline| (uT) -> distorted field
INC_DEV_T   = 25.0            # PROVISIONAL: |inclination - baseline| (deg) -> distorted field
LOCO_STEP_T = 0.30           # autocorr peak above this -> rhythmic stepping
LOCO_MOVE_FLOOR_G = 0.30 / G  # body-motion floor for on_foot (loop 0.30 m/s^2 -> g)
LOCO_LAG = (10, 100)         # cadence autocorr lag band at 50 Hz
# field variance and the engine-idle FFT are DISABLED here (loop 2: motion-confounded / parked-only),
# but still computed and printed as secondary diagnostics.

ACTIVITY_CATEGORIES = ["sedentary", "standing", "walking", "running", "cycling", "vigorous"]
POSTURE_CATEGORIES  = ["standing", "sitting", "in_motion", "lying", "device_resting"]
LOCO_CATEGORIES     = ["stationary", "on_foot", "in_vehicle"]


# ============================================================================
# SHARED MATH HELPERS
# ============================================================================
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


# ============================================================================
# AXIS 1 -- activity_state (frozen g-unit rule + gyro cycling branch)
# ============================================================================
def as_cadence(body_mag_g):
    """Cadence (Hz) = argmax of the autocorrelation over the lag band (frozen)."""
    m = body_mag_g - body_mag_g.mean()
    ac = np.correlate(m, m, mode="full")[len(m) - 1:]
    if ac[0] == 0:
        return np.nan
    ac = ac / ac[0]
    lo, hi = AS_LAG
    return FS / (lo + int(np.argmax(ac[lo:hi])))

def activity_state(w):
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
    return {"label": label, "conf": conf, "note": feats}

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


# ============================================================================
# AXIS 2 -- movement_regularity (frozen pocket-normalized rulepack)
# ============================================================================
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

def movement_regularity(w):
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


# ============================================================================
# AXIS 3 -- postural_state (frozen thigh/pocket rework)
# ============================================================================
def thigh_posture(movement_g, tilt):
    if movement_g > MOVE_T_G:
        return "in_motion"
    if tilt < SIT_STAND_T:
        return "standing"
    if tilt < FLAT_T:
        return "sitting"
    return "device_resting" if movement_g < MICRO_FLOOR_G else "lying"   # CHANGE 3: UNTESTED

def postural_state(w, calib):
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


# ============================================================================
# AXIS 4 -- locomotion_state (frozen loop-2 rule; gravity-only, self-cal baseline)
# ============================================================================
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

def locomotion_state(w, calib):
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


# ============================================================================
# AXIS 5 -- overall_state (concatenate the four -> situation + exertion + heart note)
# ============================================================================
LOAD = {"sedentary": 0, "standing": 0, "walking": 2, "running": 3, "cycling": 2, "vigorous": 3}

def overall_state(act, reg, pos, loco):
    a = act.get("label"); p = pos.get("label"); l = loco.get("label")
    # regularity bucket for the "restless" cue
    if reg.get("reason") == "low_movement" or reg.get("score") is None:
        r = "calm"
    else:
        r = "rhythmic" if reg["score"] >= 0.5 else "erratic"

    if p == "lying":               situation = "resting (lying)"
    elif l == "on_foot":           situation = "running" if a == "running" else "walking"
    elif l == "in_vehicle":        situation = "in vehicle"
    elif a == "cycling":           situation = "cycling"
    elif r == "erratic":           situation = "restless"
    else:                          situation = "still"

    exertion = 0 if l == "in_vehicle" else LOAD.get(a, 0)
    if exertion >= 2:    note = "HR rise = physical exertion (expected)"
    elif r == "erratic": note = "still but restless -> HR rise may be stress"
    else:                note = "calm baseline"
    return {"situation": situation, "exertion": exertion, "note": note}


# ============================================================================
# SENSOR SOURCES  -- swappable behind get_window(seconds) -> dict of arrays
# ============================================================================
# Native ingest units (NOT converted here): accel/lin/gravity = m/s^2, gyro = rad/s, mag = uT.
# The g-unit conversion (/9.81) lives INSIDE the axes (mag_g, postural total/G), applied exactly
# once -- do not also divide on ingest or the g-thresholds would see half-scale data.
SENSORS = ("accel", "lin", "gyro", "mag", "gravity")   # gravity is ingested for completeness;
#          the axes derive their gravity vector from the raw accelerometer, so gravity stays unused.

class PhyphoxSource:
    """Live phone over WiFi. Reads the authoritative buffer-name mapping straight from /config
    (no guessing); any sensor the experiment does not expose simply stays None."""
    # phyphox sensor source -> our key
    SOURCE_MAP = {"accelerometer": "accel", "gyroscope": "gyro", "linear_acceleration": "lin",
                  "magnetic_field": "mag", "gravity": "gravity"}
    CONNECT_TIMEOUT = 5.0     # phone / wifi can be slow on first contact
    POLL_TIMEOUT = 3.0

    def __init__(self, url):
        import requests
        self.requests = requests
        self.url = url.rstrip("/")
        try:
            cfg = self.requests.get(f"{self.url}/config", timeout=self.CONNECT_TIMEOUT).json()
        except Exception as e:
            raise SystemExit(
                f"\nCould not reach phyphox at {self.url}  ({type(e).__name__}).\n"
                "  - phone and laptop on the same WiFi?\n"
                "  - experiment open, 'Allow remote access' on, and the play button pressed (recording)?\n"
                "  - address still correct? (check the phyphox remote-access screen)")
        self.bufnames = {}        # our_key -> (t, x, y, z) buffer names, read from the experiment
        for inp in cfg.get("inputs", []):
            key = self.SOURCE_MAP.get(inp.get("source"))
            if not key:
                continue
            o = {}
            for d in inp.get("outputs", []):
                o.update(d)                                   # outputs are [{"x":"accX"},{"t":"acc_time"},...]
            if all(k in o for k in ("t", "x", "y", "z")):
                self.bufnames[key] = (o["t"], o["x"], o["y"], o["z"])
        try:
            self.requests.get(f"{self.url}/control?cmd=start", timeout=self.CONNECT_TIMEOUT)
        except Exception as e:
            print(f"  [warn] could not send start command: {e}")
        self.data = {k: [] for k in self.bufnames}
        self.last_t = {k: 0.0 for k in self.bufnames}
        self._reported_empty = set()
        print(f"phyphox '{cfg.get('title', '?')}' buffer mapping (from /config):")
        for key in SENSORS:
            if key in self.bufnames:
                tb, xb, yb, zb = self.bufnames[key]
                print(f"  {key:8s} <- {xb},{yb},{zb}  (t={tb})")
            else:
                print(f"  {key:8s} <- NOT EXPOSED by this experiment")
        print("  units: accel/lin/gravity m/s^2 (axes convert to g), gyro rad/s, mag uT")

    def update(self):
        for key, (tb, xb, yb, zb) in self.bufnames.items():
            lt = self.last_t[key]
            u = (f"{self.url}/get?{tb}={lt}&{xb}={lt}%7C{tb}&{yb}={lt}%7C{tb}&{zb}={lt}%7C{tb}")
            try:
                d = self.requests.get(u, timeout=self.POLL_TIMEOUT).json()["buffer"]
                rows = list(zip(d[tb]["buffer"], d[xb]["buffer"], d[yb]["buffer"], d[zb]["buffer"]))
                rows = [r for r in rows if None not in r]
                if rows:
                    self.data[key].extend(rows)
                    self.last_t[key] = rows[-1][0]
                    cutoff = self.last_t[key] - (WIN_SEC + 2.0)
                    self.data[key] = [r for r in self.data[key] if r[0] >= cutoff]
                elif self.last_t[key] == 0.0 and key not in self._reported_empty:
                    print(f"  [empty] sensor '{key}' buffer {xb}/{tb} returned no samples "
                          f"(is the experiment recording? is the buffer name right?)")
                    self._reported_empty.add(key)
            except Exception as e:
                print(f"  [warn] '{key}' fetch failed (buffer {xb}/{tb}): {type(e).__name__}: {e}")

    def now(self):
        return max((self.last_t[k] for k in self.bufnames), default=0.0)

    def get_window(self, seconds):
        return _resample({k: np.array(self.data[k]) for k in self.bufnames}, self.now(), seconds)


class SyntheticSource:
    """Offline replay: a scripted timeline of states so the whole pipeline can run without a phone.
    Same get_window contract as PhyphoxSource. Used for verification and demos."""
    def __init__(self, total_sec=80.0, drop=()):
        self.fs = FS
        self.cursor = WIN_SEC + 0.5          # start past one full window
        self.drop = set(drop)                # sensors to simulate as missing (degradation test)
        self._build(total_sec)

    def _build(self, total_sec):
        rng = np.random.default_rng(0)
        n = int(total_sec * FS)
        t = np.arange(n) / FS
        accel = np.zeros((n, 3)); lin = np.zeros((n, 3)); gyro = np.zeros((n, 3))
        mag = np.zeros((n, 3)); gravity = np.zeros((n, 3))

        def Rx(deg):                                          # device rotation about x (posture tilt)
            a = np.radians(deg); c, s = np.cos(a), np.sin(a)
            return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        R_up, R_sit = np.eye(3), Rx(74)                       # upright vs thigh flexed ~74 deg
        world_up = np.array([0.0, 0.0, 1.0])                  # gravity reaction "up" in world frame
        world_field = np.array([20.0, 5.0, 40.0])             # ~45 uT geomagnetic field (world frame)
        world_field_veh = np.array([8.0, 3.0, 12.0])          # distorted field inside a vehicle (world frame)
        # Both gravity and the field are world-fixed; the device rotation R maps them into device
        # coordinates together, so the magnetic dip stays orientation-invariant (as on a real phone).
        # timeline: (label, seconds). Starts with still-upright for calibration.
        timeline = [("still", 10.0), ("walking", 12.0), ("sitting", 8.0),
                    ("driving", 12.0), ("running", 8.0), ("still", 30.0)]
        i = 0
        for label, secs in timeline:
            k = int(secs * FS)
            sl = slice(i, min(i + k, n)); tt = t[sl]; m = tt.shape[0]
            R = R_sit if label in ("sitting", "driving") else R_up
            fld = world_field_veh if label == "driving" else world_field
            grav = R @ world_up                               # gravity direction in device frame
            gravity[sl] = grav * G + rng.normal(0, 0.02, (m, 3))   # gravity sensor stream (m/s^2)
            mag[sl] = (R @ fld) + rng.normal(0, 2.5 if label == "driving" else 0.5, (m, 3))
            if label in ("still", "sitting"):
                accel[sl] = grav * G + rng.normal(0, 0.05, (m, 3))
            elif label == "driving":
                lin[sl] = rng.normal(0, 0.30, (m, 3))         # broadband road vibration, low amplitude
                accel[sl] = grav * G + lin[sl]                # seated (thigh flexed) in the car
            elif label == "walking":
                env = 1.0 + 0.6 * np.sin(2 * np.pi * 0.9 * tt)    # L/R asymmetry -> stride dominates step
                osc = np.sin(2 * np.pi * 1.8 * tt) * env
                lin[sl] = np.c_[3.0 * osc, 1.5 * np.sin(2 * np.pi * 1.8 * tt + 1.0), 4.0 * osc] + rng.normal(0, 0.4, (m, 3))
                accel[sl] = grav * G + lin[sl]; gyro[sl] = np.c_[1.2 * osc, 0.6 * osc, 0.3 * osc]
            elif label == "running":
                env = 1.0 + 0.6 * np.sin(2 * np.pi * 1.3 * tt)    # stride asymmetry
                osc = np.sin(2 * np.pi * 2.6 * tt) * env
                lin[sl] = np.c_[9.0 * osc, 5.0 * np.sin(2 * np.pi * 2.6 * tt + 1.0), 11.0 * osc] + rng.normal(0, 1.0, (m, 3))
                accel[sl] = grav * G + lin[sl]; gyro[sl] = np.c_[3.0 * osc, 1.5 * osc, 1.0 * osc]
            i += k
            if i >= n:
                break
        self.t, self.accel, self.lin, self.gyro, self.mag, self.gravity = t, accel, lin, gyro, mag, gravity
        self.tmax = t[-1]

    def update(self):
        self.cursor = min(self.cursor + PRINT_EVERY, self.tmax)

    def now(self):
        return self.cursor

    def get_window(self, seconds):
        end = self.cursor; start = end - seconds
        m = (self.t >= start) & (self.t <= end)
        if m.sum() < 5:
            return {"fs": FS, "available": {}}
        out = {"fs": FS, "t": self.t[m], "available": {}}
        arrays = {"accel": self.accel, "lin": self.lin, "gyro": self.gyro, "mag": self.mag, "gravity": self.gravity}
        for k in SENSORS:
            present = k not in self.drop
            out[k] = arrays[k][m] if present else None
            out["available"][k] = present
        return out


def _resample(raw, tmax, seconds):
    """Resample each available sensor onto a common 50 Hz grid over the last `seconds`."""
    grid = np.arange(tmax - seconds, tmax, 1.0 / FS)
    out = {"fs": FS, "t": grid, "available": {}}
    for sensor in SENSORS:
        arr = raw.get(sensor)
        if arr is None or len(arr) < 5:
            out[sensor] = None
            out["available"][sensor] = False
            continue
        t = arr[:, 0]
        if t[-1] < grid[0]:                              # sensor stalled (no recent samples)
            out[sensor] = None
            out["available"][sensor] = False
            continue
        out[sensor] = np.column_stack([np.interp(grid, t, arr[:, k]) for k in (1, 2, 3)])
        out["available"][sensor] = True
    return out


# global swappable handle the spec asks for
SOURCE = None
def get_sensor_window(seconds):
    """The single swappable input: returns a dict of resampled sensor arrays for the last `seconds`."""
    return SOURCE.get_window(seconds)


# ============================================================================
# USER-FACING WEB VIEW  -- PRESENTATION ONLY. Reflects the readings the pipeline
# already produced; no new classification, no new scores. A tiny HTTP server in a
# background thread serves the page and a /state JSON the page polls every ~1s.
# ============================================================================
_LATEST = {"ready": False}                          # latest reading set, shared with the web thread
_LATEST_LOCK = threading.Lock()

def _set_latest(snap):
    with _LATEST_LOCK:
        _LATEST.clear(); _LATEST.update(snap)

def _get_latest():
    with _LATEST_LOCK:
        return dict(_LATEST)

def _secondary(act, reg, pos, loco):
    """The small for-the-curious line: the individual verdicts, verbatim."""
    rs = reg.get("score")
    return "  ·  ".join([
        f"activity {act.get('label') or '—'}",
        f"regularity {rs:.2f}" if rs is not None else "regularity —",
        f"posture {(pos.get('label') or '—').replace('_', ' ')}",
        f"locomotion {(loco.get('label') or '—').replace('_', ' ')}",
    ])

# Low-confidence phrasings for the activity-driven situations (where a numeric margin exists).
_LOW_PHRASE = {"walking": "Possibly walking…", "running": "Possibly running…", "cycling": "Possibly cycling…"}

def humanize(act, reg, pos, loco, ov):
    """Pure lookup: turn the existing verdicts into one plain sentence + an honest confidence word
    + an icon key. No thresholds, no scoring -- it only reads what the axes already decided."""
    if ov is None:                                  # a core axis is null/unavailable
        return {"sentence": "Not sure yet.", "confidence_word": "uncertain",
                "icon": "unknown", "secondary": _secondary(act, reg, pos, loco)}
    sit = ov["situation"]
    steady = reg.get("score") is not None and reg["score"] >= 0.5
    if sit == "in vehicle":
        sentence, icon = "You're in a vehicle.", "vehicle"
    elif sit == "resting (lying)":
        sentence, icon = "Lying down.", "lying"
    elif sit == "running":
        sentence, icon = "You're running.", "running"
    elif sit == "walking":
        sentence, icon = ("You're walking — calm, steady pace." if steady else "You're walking."), "walking"
    elif sit == "cycling":
        sentence, icon = "You're cycling.", "cycling"
    elif sit == "restless":
        sentence, icon = "Still, but a little restless.", "restless"
    else:                                           # "still"
        p = pos.get("label")
        sentence, icon = ({"sitting": ("Sitting still.", "sitting"),
                           "standing": ("Standing still.", "standing")}).get(p, ("Still.", "still"))
    # Confidence, stated honestly: hedge only the activity-driven calls, where a margin proxy exists.
    word = "high"
    conf = act.get("conf")
    if sit in _LOW_PHRASE and conf is not None and conf < 0.65:
        word, sentence = "low", _LOW_PHRASE[sit]
    return {"sentence": sentence, "confidence_word": word, "icon": icon,
            "secondary": _secondary(act, reg, pos, loco)}

def _publish(source, act, reg, pos, loco, ov):
    """Snapshot the current readings for the web view. Called after the terminal print; changes nothing there."""
    _set_latest({
        "ready": True,
        "t": round(source.now(), 1),
        "readings": {
            "activity":   {"label": act.get("label"), "conf": act.get("conf")},
            "regularity": {"score": reg.get("score"), "reason": reg.get("reason")},
            "postural":   {"label": pos.get("label")},
            "locomotion": {"label": loco.get("label")},
            "overall":    ({"situation": ov["situation"], "exertion": ov["exertion"]} if ov else None),
        },
        "human": humanize(act, reg, pos, loco, ov),
    })

HTML_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SynHeart — kinematic state</title>
<style>
  :root { --bg:#0e0e0f; --fg:#f2f2f0; --muted:#7a7a7a; --line:#222; }
  html,body { height:100%; margin:0; }
  body { background:var(--bg); color:var(--fg); display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  .card { text-align:center; padding:2rem; max-width:660px; width:100%; }
  .icon { font-size:5rem; line-height:1; filter:grayscale(1); opacity:.92; }
  .sentence { font-size:2.3rem; font-weight:300; letter-spacing:.2px; margin:1.4rem 0 .5rem;
              transition:opacity .25s; min-height:1.3em; }
  .conf { font-size:.95rem; color:var(--muted); min-height:1.2em; }
  .secondary { margin-top:2.2rem; padding-top:1rem; border-top:1px solid var(--line);
               font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.8rem; color:var(--muted); }
  .dim { opacity:.4; }
</style></head>
<body><div class="card">
  <div id="icon" class="icon">…</div>
  <div id="sentence" class="sentence dim">Connecting…</div>
  <div id="conf" class="conf"></div>
  <div id="secondary" class="secondary"></div>
</div>
<script>
  const ICON = {walking:"🚶",running:"🏃",cycling:"🚴",vehicle:"🚗",lying:"🛌",
                sitting:"🪑",standing:"🧍",restless:"🤚",still:"⏸",unknown:"…"};
  async function tick(){
    const sEl=document.getElementById('sentence'), iEl=document.getElementById('icon'),
          cEl=document.getElementById('conf'), secEl=document.getElementById('secondary');
    try{
      const s = await (await fetch('/state',{cache:'no-store'})).json();
      if(!s.ready){ iEl.textContent='…'; sEl.textContent='Calibrating — hold still…';
        sEl.className='sentence dim'; cEl.textContent=''; secEl.textContent='waiting for sensors'; return; }
      const h=s.human;
      iEl.textContent=ICON[h.icon]||'…';
      sEl.textContent=h.sentence; sEl.className='sentence';
      cEl.textContent = h.confidence_word==='low' ? 'low confidence — still settling'
                      : h.confidence_word==='uncertain' ? 'uncertain' : '';
      secEl.textContent=h.secondary;
    }catch(e){ sEl.textContent='Disconnected…'; sEl.className='sentence dim'; cEl.textContent=''; }
  }
  setInterval(tick,1000); tick();
</script></body></html>"""

class _ViewHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):                      # silence access logs -> keep the terminal clean
        pass
    def _send(self, body, ctype):
        b = body.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try:
            self.wfile.write(b)
        except BrokenPipeError:
            pass
    def do_GET(self):
        if self.path.startswith("/state"):
            self._send(json.dumps(_get_latest()), "application/json")
        else:
            self._send(HTML_PAGE, "text/html; charset=utf-8")

def start_web(port=WEB_PORT):
    """Start the view server in a daemon thread so it never blocks the sensor loop."""
    srv = ThreadingHTTPServer(("0.0.0.0", port), _ViewHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ============================================================================
# CALIBRATION  -- collect a stationary baseline at startup
# ============================================================================
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


# ============================================================================
# MAIN LOOP
# ============================================================================
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

    act = safe("activity",   lambda: activity_state(w_act))
    reg = safe("regularity", lambda: movement_regularity(w_long))
    pos = safe("postural",   lambda: postural_state(w_long, calib))
    loco = safe("locomotion", lambda: locomotion_state(w_long, calib))

    av = act.get("label")
    print(f"  activity   : {str(av):12s}" + (f"(conf {act['conf']})" if av else "") + f" | {act['note']}")
    rs = reg.get("score")
    print(f"  regularity : {(f'{rs:.2f}' if rs is not None else 'null'):12s}"
          + (f"(conf {reg['conf']})" if reg.get('conf') is not None else "") + f" | {reg['note']}")
    print(f"  postural   : {str(pos.get('label')):12s} | {pos['note']}")
    print(f"  locomotion : {str(loco.get('label')):12s} | {loco['note']}")

    # overall needs the three categorical axes; null regularity is treated as "calm", not a blocker
    if all(x.get("label") is not None for x in (act, pos, loco)):
        ov = overall_state(act, reg, pos, loco)
        print(f"  overall    : {ov['situation']:12s} | exertion={ov['exertion']} | HR: {ov['note']}")
    else:
        ov = None
        missing = [n for n, x in (("activity", act), ("postural", pos), ("locomotion", loco)) if x.get("label") is None]
        print(f"  overall    : (skipped: {', '.join(missing)} unavailable)")
    print()
    _publish(source, act, reg, pos, loco, ov)        # mirror to the web view (presentation only)


def main():
    global SOURCE
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
        SOURCE = SyntheticSource(drop=drop)
        steps = steps or 60
    else:
        url = next((a for a in args if a.startswith("http")), None) or \
              input("phyphox remote URL (e.g. http://192.168.0.42:8080): ").strip()
        print(f"SOURCE: phyphox {url}")
        SOURCE = PhyphoxSource(url)

    try:
        start_web(WEB_PORT)
        print(f"\nHuman view: open  http://localhost:{WEB_PORT}   (this terminal keeps the technical view)")
    except Exception as e:
        print(f"  [warn] web view could not start on port {WEB_PORT}: {e}")

    calib = calibrate(SOURCE)

    print("Streaming five kinematic readings (Ctrl-C to stop):\n")
    n = 0
    try:
        while steps is None or n < steps:
            SOURCE.update()
            run_once(SOURCE, calib)
            n += 1
            if not synthetic:
                time.sleep(PRINT_EVERY)
            if synthetic and SOURCE.now() >= SOURCE.tmax:
                break
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
