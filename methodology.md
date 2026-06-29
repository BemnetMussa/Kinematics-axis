# Kinematics-axis Methodology

This document details the mathematical and physical foundations of each human state axis.

## 1. Activity State (`activity_state`)
**Goal**: Classify hard locomotor activity (Sedentary, Walking, Running, Cycling).
- **Physical Quantity**: Acceleration Energy and Cadence.
- **Independence**: Orientation-invariant through the use of body-acceleration magnitude $|a|$.
- **Logic**:
    - **Still**: `std(|a|) < STILL_THRESHOLD` (approx. 0.7 $g$).
    - **Walk/Run Band**: Resolved by **cadence** from the peak of the autocorrelation lag. If cadence > `RUN_CADENCE`, it's Running.
    - **Cycling**: Specifically caught by **gyroscope energy** in regions where linear motion is low (still/sedentary region).
- **Validation**: 97.1% accuracy on MotionSense.

## 2. Movement Regularity (`movement_regularity`)
**Goal**: Measure smoothness and rhythm of movement in range $[0, 1]$.
- **Physical Quantity**: Short-time autocorrelation of acceleration magnitude.
- **Method**: Based on the **Moe-Nilssen trunk-accelerometry method** (2004).
- **Logic**: Measures the height of the first dominant peak in the autocorrelation of $|a|$ at the step/stride lag.
- **Interpretation**: 0.9 = rhythmic gait; 0.1 = erratic or static.

## 3. Postural State (`postural_state`)
**Goal**: Determine body posture (Standing, Sitting, Lying, In Motion).
- **Physical Quantity**: Thigh-tilt relative to gravity.
- **Reference**: Calibrated "up" vector recorded while the user is standing still.
- **Logic**: 
    - Angle $\theta$ between current mean gravity and calibrated "up".
    - $\theta < 25^\circ$: Standing.
    - $25^\circ < \theta < 85^\circ$: Sitting (thigh flexed).
    - $\theta \approx 90^\circ$: Lying or flat device.
- **Note**: The distinction between "Lying" and "Device Resting" is currently experimental.

## 4. Locomotion State (`locomotion_state`)
**Goal**: Determine if the wearer is moving through space (Stationary, On Foot, In Vehicle).
- **Physical Quantities**: Gait rhythm (accelerometer) + Magnetic Field distortion (magnetometer).
- **Logic**:
    - **Stage 1**: Detects "On Foot" travel using autocorrelation peaks of body acceleration.
    - **Stage 2**: If no gait is detected, compares magnetic field magnitude $|\vec{B}|$ and inclination $\iota$ to the startup baseline. Significant drift indicates a **Vehicle** (steel mass and motors distort the local field).
- **Validation**: Demonstrated on single-car PAMAP2 data; needs multi-vehicle evaluation (SHL dataset).

## 5. Overall State (`overall_state`)
**Goal**: Synthesize axes into a single human situation.
- **Logic**: A priority-based cascade:
    1. If Lying -> `resting (lying)`
    2. If On Foot -> `walking` / `running`
    3. If In Vehicle -> `in vehicle`
    4. If Cycling -> `cycling`
    5. If Erratic Regularity -> `restless`
    6. Otherwise -> `still`
- **Exertion**: A lookup table based on activity (Running=3, Walking=2, Still=0).
- **Heart-Rate Context**: Provides notes like "HR rise expected" or "stress context" based on regularity.
