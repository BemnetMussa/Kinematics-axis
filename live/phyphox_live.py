"""
Live Activity State from a phone, over WiFi, using OUR maths.

No trained model needed - our Activity State is a deterministic rule on the
acceleration magnitude |a| = sqrt(x^2+y^2+z^2), which does not change when the
phone is rotated. So the demo shows two things at once:
  - the live verdict (still / walking / running) follows what you actually do
  - the per-axis numbers swing when you rotate the phone, but |a| and the
    verdict stay put  ->  the maths is orientation-proof, live.

Setup (phone):
  1. Phone and laptop on the SAME WiFi.
  2. Open phyphox -> experiment "Acceleration with g" (best for the rotation demo).
  3. Menu -> "Allow remote access". Copy the address it shows, e.g. http://192.168.0.42:8080
  4. Press play (the triangle) so it starts recording.

Run (laptop):
  .venv/bin/python phyphox_live.py http://192.168.0.42:8080
"""
import sys, time, requests
import numpy as np
from collections import deque

WINDOW_SECONDS = 2.0      # sliding window length
POLL_INTERVAL  = 0.10     # how often we ask the phone for new samples
STILL_TH = 0.7            # movement (std of |a|, m/s^2) below this = still
WALK_TH  = 4.0            # between STILL_TH and this = walking, above = running/vigorous


def detect_buffers(url):
    """phyphox names its sensor buffers differently per experiment. Probe a few
    known name sets and keep the one that actually returns data."""
    candidates = [
        ("acc_time", "accX", "accY", "accZ"),
        ("lin_time", "linX", "linY", "linZ"),
        ("accT",     "accX", "accY", "accZ"),
        ("t",        "x",    "y",    "z"),
    ]
    for tb, xb, yb, zb in candidates:
        try:
            r = requests.get(f"{url}/get?{xb}&{yb}&{zb}&{tb}", timeout=2.0)
            d = r.json().get("buffer", {})
            if all(k in d for k in (tb, xb, yb, zb)) and len(d[xb]["buffer"]) > 0:
                return tb, xb, yb, zb
        except Exception:
            continue
    return None


def fetch_new(url, tb, xb, yb, zb, last_t):
    """Ask only for samples newer than last_t (timestamp-threshold query)."""
    u = (f"{url}/get?{tb}={last_t}"
         f"&{xb}={last_t}%7C{tb}&{yb}={last_t}%7C{tb}&{zb}={last_t}%7C{tb}")
    d = requests.get(u, timeout=1.0).json()["buffer"]
    t = d[tb]["buffer"]; x = d[xb]["buffer"]; y = d[yb]["buffer"]; z = d[zb]["buffer"]
    return list(zip(t, x, y, z))


def verdict(window):
    """OUR deterministic maths, all from the magnitude |a| (orientation-proof)."""
    acc = window[:, 1:4]
    mag = np.linalg.norm(acc, axis=1)          # |a|  -> unchanged by rotation
    movement = mag.std()                       # how much motion
    # rhythm (regularity): peak of autocorrelation of the magnitude
    m = mag - mag.mean()
    ac = np.correlate(m, m, "full")[len(m)-1:]
    regularity = float((ac[3:] / (ac[0] + 1e-9)).max()) if ac[0] > 0 else 0.0

    if movement < STILL_TH:      activity = "STILL"
    elif movement < WALK_TH:     activity = "WALKING"
    else:                        activity = "RUNNING/VIGOROUS"

    if   movement < STILL_TH:    rhythm = "calm"
    elif regularity > 0.40:      rhythm = "rhythmic"
    else:                        rhythm = "erratic"
    return movement, mag.mean(), acc.mean(0), activity, rhythm


def main():
    url = (sys.argv[1] if len(sys.argv) > 1 else
           input("phyphox remote URL (e.g. http://192.168.0.42:8080): ")).rstrip("/")

    requests.get(f"{url}/control?cmd=start", timeout=2.0)   # make sure it's recording
    print("Connecting to", url, "...")
    names = detect_buffers(url)
    if not names:
        print("Could not find the sensor buffers. Open", f"{url}/config",
              "in a browser and tell me the buffer names (look for x/y/z + time).")
        return
    tb, xb, yb, zb = names
    print(f"Using buffers: time={tb}  x={xb}  y={yb}  z={zb}\n")
    print("axis = per-axis mean (orientation-DEPENDENT: swings when you rotate)")
    print("|a| & movement = orientation-PROOF (stay put under rotation)\n")
    print("Move around, then hold still and ROTATE the phone - watch axis change but the verdict not.\n")

    buf = deque(); last_t = 0.0; smooth = deque(maxlen=5); last_print = 0.0
    while True:
        try:
            for s in fetch_new(url, tb, xb, yb, zb, last_t):
                buf.append(s)
            if buf:
                last_t = buf[-1][0]
                while buf and buf[-1][0] - buf[0][0] > WINDOW_SECONDS:
                    buf.popleft()
            w = np.array(buf)
            if len(w) > 10 and time.time() - last_print > 0.4:
                mv, mag_mean, axis, act, rhy = verdict(w)
                smooth.append(act)
                act_s = max(set(smooth), key=smooth.count)   # majority-vote smoothing
                print(f"movement={mv:5.2f}  |a|={mag_mean:5.2f}  "
                      f"axis=({axis[0]:6.2f},{axis[1]:6.2f},{axis[2]:6.2f})  ->  {act_s:16s} ({rhy})")
                last_print = time.time()
            time.sleep(POLL_INTERVAL)
        except requests.exceptions.RequestException as e:
            print("connection error:", e, "- retrying"); time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nstopped."); break


if __name__ == "__main__":
    main()
