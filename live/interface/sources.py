"""Sensor sources behind one swappable get_sensor_window(seconds) -> dict of arrays.

PhyphoxSource (live phone over WiFi) and SyntheticSource (offline replay) share the same
get_window contract. A missing sensor simply stays None so the dependent axis degrades.

Pure refactor: moved verbatim from the original live_hsi.py.
"""
import numpy as np

from core.config import G, FS, WIN_SEC, PRINT_EVERY, SENSORS


class PhyphoxSource:
    """Live phone over WiFi. Reads the authoritative buffer-name mapping straight from /config
    (no guessing); any sensor the experiment does not expose simply stays None."""
    # phyphox sensor source -> our key
    SOURCE_MAP = {"accelerometer": "accel", "gyroscope": "gyro", "linear_acceleration": "lin",
                  "magnetic_field": "mag", "gravity": "gravity", "location": "location"}
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
            if key == "location":
                 # location usually has: t, lat, lon, speed, alt, ...
                 # we just look for 't' and 'speed'
                 if "t" in o and "speed" in o:
                     self.bufnames[key] = (o["t"], o["speed"])
            elif all(k in o for k in ("t", "x", "y", "z")):
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
        for key, bufs in self.bufnames.items():
            lt = self.last_t[key]
            # bufs is (t, speed) for location, (t, x, y, z) for others
            if key == "location":
                tb, sb = bufs
                u = f"{self.url}/get?{tb}={lt}&{sb}={lt}%7C{tb}"
                try:
                    d = self.requests.get(u, timeout=self.POLL_TIMEOUT).json()["buffer"]
                    rows = list(zip(d[tb]["buffer"], d[sb]["buffer"]))
                    rows = [r for r in rows if None not in r]
                    if rows:
                        self.data[key].extend(rows)
                        self.last_t[key] = rows[-1][0]
                        cutoff = self.last_t[key] - (WIN_SEC + 2.0)
                        self.data[key] = [r for r in self.data[key] if r[0] >= cutoff]
                except Exception as e:
                    print(f"  [warn] '{key}' fetch failed (buffer {sb}): {type(e).__name__}: {e}")
            else:
                tb, xb, yb, zb = bufs
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
                except Exception as e:
                    print(f"  [warn] '{key}' fetch failed (buffer {xb}): {type(e).__name__}: {e}")

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
        # Sim speed (m/s): driving 14m/s (~50km/h), walking 1.4m/s, running 3m/s, still 0
        speed = np.zeros(n)
        for label, secs in timeline:
            # Re-apply same timeline slices to speed
            # (In a real refactor we'd do this inside the loop above, but this is simpler for diff)
            pass
        # Better: let's just add it to the loop above in my next turn if needed, or just hardcode it here.
        self.speed = np.zeros(n)
        i = 0
        for label, secs in timeline:
            k = int(secs * FS)
            sl = slice(i, min(i+k, n))
            s_val = 0.0
            if label == "driving": s_val = 14.0
            elif label == "walking": s_val = 1.4
            elif label == "running": s_val = 3.5
            elif label == "cycling": s_val = 6.0
            self.speed[sl] = s_val + rng.normal(0, 0.1, (len(self.speed[sl])))
            i += k
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
        arrays = {"accel": self.accel, "lin": self.lin, "gyro": self.gyro, "mag": self.mag, "gravity": self.gravity, "location": self.speed}
        for k in SENSORS + ["location"]:
            if k == "location":
                 out["speed"] = self.speed[m]
                 out["available"]["location"] = True
                 continue
            present = k not in self.drop
            out[k] = arrays[k][m] if present else None
            out["available"][k] = present
        return out


def _resample(raw, tmax, seconds):
    """Resample each available sensor onto a common 50 Hz grid over the last `seconds`."""
    grid = np.arange(tmax - seconds, tmax, 1.0 / FS)
    out = {"fs": FS, "t": grid, "available": {}}
    for sensor in SENSORS + ["location"]:
        arr = raw.get(sensor)
        if arr is None or len(arr) < 5:
            out[sensor] = None
            out["available"][sensor] = False
            continue
        t = arr[:, 0]
        if t[-1] < grid[0]:
            out[sensor] = None
            out["available"][sensor] = False
            continue
        if sensor == "location":
             out["speed"] = np.interp(grid, t, arr[:, 1])
        else:
             out[sensor] = np.column_stack([np.interp(grid, t, arr[:, k]) for k in (1, 2, 3)])
        out["available"][sensor] = True
    return out


# global swappable handle the spec asks for
SOURCE = None


def set_source(src):
    """Install the active source (called once at startup by the entry point)."""
    global SOURCE
    SOURCE = src


def get_sensor_window(seconds):
    """The single swappable input: returns a dict of resampled sensor arrays for the last `seconds`."""
    return SOURCE.get_window(seconds)
