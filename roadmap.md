# Kinematics-axis Roadmap

This document tracks the remaining tasks and future directions for the project, as identified in the internal progress reports.

## High Priority: Systematic Testing
- [ ] **On-device Scenario Testing**: Move beyond recorded data; systematically test each activity, posture, and locomotion mode on a physical phone.
- [ ] **Provisional Thresholds**: Re-tune thresholds (currently derived from Chest datasets) for deployment in the **front pocket**.
- [ ] **Transition Characterization**: Study and mitigate errors in windows that straddle activity changes (5-second overlap).

## Medium Priority: Feature Extensions
- [ ] **Multi-vehicle Locomotion**: Validate the `in_vehicle` branch across different transportation modes (using SHL dataset) rather than just a single car.
- [ ] **Lying vs. Resting**: Develop and test a more robust distinction between "Lying" (on body) and "Device Resting" (on a table).
- [ ] **Vigorous Activity Class**: Add a model for "Vigorous" activity beyond simple "Running".

## Long Term: Advanced Fusion
- [ ] **GPS-free Multi-cue Locomotion**: Integrate vibration analysis (4–15 Hz engine/road bands) and event detection (braking, cornering) to improve vehicle detection without location tracking.
- [ ] **Heart-Rate Integration**: Further refine the `overall_state` heart-rate context with more deterministic physiological cues.

## Technical Debt
- [ ] Fix `m/s^2` vs `g` unit inconsistencies across older notebooks.
- [ ] Improve magnetometer handling for device-specific "hard-iron" bias.
