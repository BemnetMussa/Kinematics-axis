"""All thresholds and constants for the five kinematic axes, in one place.

Pure refactor of the original single-file live_hsi.py CONFIG block: every value here is
IDENTICAL to before. Thresholds carried from one placement/dataset are flagged PROVISIONAL.
"""
G  = 9.81                       # m/s^2 per g
FS = 50                         # shared pipeline rate (Hz); everything resampled to this

ACT_SEC  = 2.56                 # activity_state window (s) -> 128 samples
WIN_SEC  = 5.0                  # regularity / postural / locomotion window (s) -> 250 samples
ACT_WIN  = int(ACT_SEC * FS)
LONG_WIN = int(WIN_SEC * FS)
PRINT_EVERY = 1.0               # seconds between readings (live)
CALIB_SEC   = 5.0               # stationary baseline collected at startup
GET_READY_SEC = 5.0             # PROVISIONAL: live-only grace period to get into the standing/pocket
                                # position before the calibration capture window (postural 'up' reference)
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

# overall_state exertion lookup (load level per activity label)
LOAD = {"sedentary": 0, "standing": 0, "walking": 2, "running": 3, "cycling": 2, "vigorous": 3}

# Sensor stream keys. Native ingest units (NOT converted on ingest): accel/lin/gravity = m/s^2,
# gyro = rad/s, mag = uT. The g-conversion (/9.81) lives inside the axes (mag_g, postural total/G),
# applied exactly once. gravity is ingested for completeness; the axes derive their gravity vector
# from the raw accelerometer, so the gravity stream stays unused.
SENSORS = ("accel", "lin", "gyro", "mag", "gravity")
