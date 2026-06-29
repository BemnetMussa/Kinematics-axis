# Kinematics-axis Project Memory

This document serves as a guide for agents to understand the Kinematics-axis project, its architecture, core logic, and usage.

## Project Overview
**Kinematics-axis** is a human activity recognition (HAR) system designed to be **orientation-proof**. It uses smartphone sensor data (accelerometer and gyroscope) to detect physical states like sitting, walking, running, and cycling without requiring the phone to be in a specific orientation.

### Design Principles
- **On-device**: All computation happens where the data is produced. No sensor stream leaves the phone; only high-level state readings do.
- **Deterministic**: Every reading is produced by an explicit physical rule over named features, not by an opaque learned model.
- **Privacy-first**: Inference remains on-device, and the readings are abstractions of state rather than reconstructions of raw activity.

### Core Philosophy
- **Physical Rules over Hand-Tuning**: Rules are derived from physical quantities (energy, cadence, autocorrelation, tilt) validated against public datasets (MotionSense, HHAR, PAMAP2).
- **Orientation Independence**: By focusing on the magnitude of acceleration $|a| = \sqrt{x^2+y^2+z^2}$, the system remains accurate whether the phone is in a pocket, held in hand, or sideways.

---

## Project Structure

### 1. `live/` (The Real-time Pipeline)
This directory contains the production-ready code for real-time detection.
- **`phyphox_live.py`**: The main entry point. It connects to the [Phyphox](https://phyphox.org/) app on a smartphone via WiFi to stream live sensor data.
- **`live_hsi.py`**: Likely the main integration script (HSI = Human State Interface).
- **`axes/`**: Modular classifiers for different types of human state.
    - `activity_state.py`: Classifies Still, Walking, Running, Cycling.
    - `locomotion_state.py`: Focuses on types of ground movement.
    - `postural_state.py`: Detects Sitting, Standing, Lying using tilt and gravity vectors.
    - `movement_regularity.py`: Measures how "rhythmic" or "cadenced" the movement is (e.g., steady walk vs. erratic movement).
- **`core/`**: Shared logic.
    - `config.py`: Thresholds (STILL_TH, WALK_TH), sampling rates, and port settings.
    - `features.py`: Signal processing utilities like magnitude calculation and bandpass filtering.
- **`interface/`**: How the data is shown to the user.
    - `web.py`: Serves a minimalist, premium-looking dashboard on `localhost:8000`.
    - `dashboard.py`: Logic for terminal-based or combined visualizations.

### 2. `maths/` & `exploration/` (R&D)
- Contains Jupyter notebooks (`.ipynb`) where the mathematical rules were derived and validated.
- **`maths/experiments/`**: Testing the logic against standard HAR datasets (UCI HAR, PAMAP2).
- **`maths/figs/`**: Generated visualizations of the kinematics pipeline.

### 3. `Dataset/`
- Raw data from **UCI HAR**, **PAMAP2**, and **MotionSense** used for validating the deterministic rules.

---

## Key Technical Concepts

### 1. The Magnitude Rule
The primary feature used is the standard deviation of the acceleration magnitude.
- `std(|a|) < 0.7`: Sedentary / Still.
- `std(|a|) > 4.0`: Running / Vigorous activity.

### 2. Postural Tilt
By comparing the mean acceleration vector (which represents gravity when still) to a "calibrated up" vector, the system calculates the angle (tilt) of the phone relative to the user's thigh or body.
- Small tilt -> Standing.
- Large tilt (~90°) -> Sitting or Lying down.

### 3. Regularity & Cadence
Uses autocorrelation of the acceleration signal to find the "dominant beat" of human motion. This allows distinguishing between a "steady walk" and "erratic fidgeting".

---

## How to Run Live
1.  **Setup Phone**: Install **Phyphox**, open "Acceleration with g", and "Allow remote access".
2.  **Deployment**: Place the phone in its final position (standardly the **front trouser pocket**).
3.  **Startup Calibration**: 
    - Stand up straight and hold still during the 10-second countdown.
    - The system captures a "gravity reference" (up) and a "magnetic baseline" (local field).
    - If calibration fails (e.g., moving too much or magnetic interference), it will report a suspect baseline.
4.  **Run Script**: 
    ```bash
    python live/phyphox_live.py http://<phone-ip>:8080
    ```
5.  **View UI**: Open `http://localhost:8000` in a browser.

## Critical Files to Watch
- `live/core/config.py`: Adjust this if detection sensitivity is off.
- `live/axes/activity_state.py`: The heart of the classification logic.
- `live/interface/web.py`: The UI presentation layer.
