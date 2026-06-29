# Synheart Kinematics Knowledge Base

This document is a compact operating manual for the repository. It is written so another AI can understand the project quickly and work on it safely.

## 1. Project Purpose

Synheart Kinematics implements a deterministic, on-device human-state pipeline from a single phone sensor stream. The live system produces five readings:

- activity
- movement regularity
- posture
- locomotion
- overall state

The design constraints are:

- on-device computation
- deterministic rules, not machine learning
- privacy-first output: only state readings leave the device, not raw traces

The live implementation is split into acquisition, calibration, axis logic, and presentation. The notebook and LaTeX layer contain the derivations and reports behind those rules.

## 2. High-Level Structure

### Live system

- [live/live_hsi.py](live/live_hsi.py) is the main entry point.
- [live/interface/sources.py](live/interface/sources.py) provides the swappable sensor source layer.
- [live/interface/dashboard.py](live/interface/dashboard.py) handles startup calibration and the terminal technical view.
- [live/interface/web.py](live/interface/web.py) serves the human-facing web view.
- [live/core/config.py](live/core/config.py) centralizes thresholds and constants.
- [live/core/features.py](live/core/features.py) contains shared feature math.
- [live/axes/activity_state.py](live/axes/activity_state.py) implements activity classification.
- [live/axes/movement_regularity.py](live/axes/movement_regularity.py) implements the regularity score.
- [live/axes/postural_state.py](live/axes/postural_state.py) implements posture.
- [live/axes/locomotion_state.py](live/axes/locomotion_state.py) implements locomotion.
- [live/axes/overall_state.py](live/axes/overall_state.py) combines the four axis readings into a situation summary.

### Derivation and reports

- [maths/kinematics_maths.tex](maths/kinematics_maths.tex) is the main math write-up.
- [maths/starter_insights.tex](maths/starter_insights.tex), [maths/pipeline_insights.tex](maths/pipeline_insights.tex), [maths/locomotion_insights.tex](maths/locomotion_insights.tex), and [maths/live_demo.tex](maths/live_demo.tex) are supporting notes.
- [report/report.tex](report/report.tex) is the full live-implementation report.
- [report/progress_report.tex](report/progress_report.tex) is the short progress report.

### Datasets and exploration

- [Dataset/MotionSense](Dataset/MotionSense)
- [Dataset/PAMAP2_data/PAMAP2_Dataset](Dataset/PAMAP2_data/PAMAP2_Dataset)
- [Dataset/UCI HAR Dataset](Dataset/UCI%20HAR%20Dataset)
- [Dataset/HHAR](Dataset/HHAR)
- [UCI_HAR_Dataset/csv_files/train.csv](UCI_HAR_Dataset/csv_files/train.csv)
- [UCI_HAR_Dataset/csv_files/test.csv](UCI_HAR_Dataset/csv_files/test.csv)
- [exploration/Understand_UCI_HAR_Dataset.ipynb](exploration/Understand_UCI_HAR_Dataset.ipynb)
- [exploration/Detect_Motion_Starter_local.ipynb](exploration/Detect_Motion_Starter_local.ipynb)
- [exploration/Orientation_Test.ipynb](exploration/Orientation_Test.ipynb)

## 3. Core Runtime Flow

The live entry point follows this sequence:

1. Select a sensor source.
2. Register the source globally.
3. Start the presentation web server.
4. Run startup calibration.
5. Loop over windows and classify each axis.
6. Print the technical dashboard and publish the human view.

That flow is implemented in [live/live_hsi.py](live/live_hsi.py), with the actual window handling performed through [live/interface/sources.py](live/interface/sources.py).

### Sources

- `PhyphoxSource` reads from a phone over WiFi using the Phyphox remote API.
- `SyntheticSource` replays a scripted timeline for offline verification and demos.
- Missing sensors do not crash the pipeline. Each axis checks for the inputs it needs and returns a null reading with a note when its prerequisites are missing.

### Windowing

- The system resamples every available sensor onto a common 50 Hz grid.
- Activity uses a 2.56 s window.
- Regularity, posture, and locomotion use a 5 s window.
- Overall state consumes the already-computed axis readings rather than the raw signal.

## 4. Calibration Model

Calibration is required because posture and locomotion depend on references that are specific to the current phone placement and environment.

At startup the user is expected to:

- place the phone in its deployment position
- stand upright
- remain still through the calibration window

The calibration captures:

- the standing gravity direction used as the postural `up` reference
- the magnetometer baseline magnitude and inclination used by locomotion

Important caveat: if calibration is wrong, later posture and locomotion results are corrupted. The code treats calibration as a first-class input rather than an optional convenience.

## 5. The Five Axes

### Activity

- File: [live/axes/activity_state.py](live/axes/activity_state.py)
- Purpose: classify sedentary, walking, running, or cycling.
- Main features: body acceleration magnitude, cadence, and gyro energy.
- Rule style: frozen threshold logic derived from the MotionSense work.

### Movement regularity

- File: [live/axes/movement_regularity.py](live/axes/movement_regularity.py)
- Purpose: output a regularity score in the range [0, 1].
- Main features: autocorrelation peak, cycle adequacy, movement floor.
- Rule style: deterministic score, not a learned classifier.

### Posture

- File: [live/axes/postural_state.py](live/axes/postural_state.py)
- Purpose: classify standing, sitting, in_motion, lying, or device_resting.
- Main features: tilt relative to the calibrated standing reference and movement magnitude.
- Caveat: the flat branch is flagged low-confidence and is explicitly treated as untested.

### Locomotion

- File: [live/axes/locomotion_state.py](live/axes/locomotion_state.py)
- Purpose: classify stationary, on_foot, or in_vehicle.
- Main features: rhythmic stepping from acceleration autocorrelation and magnetometer deviation from baseline.
- Caveat: vehicle detection uses self-calibrated magnetometer thresholds and is marked provisional in the config.

### Overall state

- File: [live/axes/overall_state.py](live/axes/overall_state.py)
- Purpose: combine the four axis readings into a situation, exertion level, and short heart-rate note.
- It is a rule-based combiner, not a classifier over raw sensor data.

## 6. Shared Feature Math

The reusable math lives in [live/core/features.py](live/core/features.py).

It provides:

- body acceleration extraction, preferring linear acceleration when available
- magnitude in g
- autocorrelation peak computation
- vector angle computation
- magnetometer field magnitude, variance, and inclination using gravity only

The config file [live/core/config.py](live/core/config.py) is the single source of truth for thresholds, window sizes, and categorical labels.

## 7. Presentation Layer

The presentation layer does not classify anything. It only shows the outputs already produced by the pipeline.

- [live/interface/dashboard.py](live/interface/dashboard.py) prints the technical view in the terminal.
- [live/interface/web.py](live/interface/web.py) serves a local HTML dashboard and polls the latest readings.

This separation matters: if the presentation code changes, it should not alter classification behavior.

## 8. What the Reports Mean

- [report/progress_report.tex](report/progress_report.tex) is the short status report with validation summaries and next steps.
- [report/report.tex](report/report.tex) is the longer live-implementation report describing the architecture, calibration, and runtime design.
- [maths/kinematics_maths.tex](maths/kinematics_maths.tex) is the broad maths narrative for the activity and regularity work.

Generated PDFs are stored alongside their sources. Relevant outputs include:

- [report/report.pdf](report/report.pdf)
- [report/progress_report.pdf](report/progress_report.pdf)
- [maths/kinematics_maths.pdf](maths/kinematics_maths.pdf)
- [maths/live_demo.pdf](maths/live_demo.pdf)
- [maths/starter_insights.pdf](maths/starter_insights.pdf)
- [maths/pipeline_insights.pdf](maths/pipeline_insights.pdf)
- [maths/locomotion_insights.pdf](maths/locomotion_insights.pdf)

## 9. Conventions and Caveats

- The live system is deterministic and rule-based.
- Thresholds in [live/core/config.py](live/core/config.py) are intentionally centralized.
- Some locomotion and posture thresholds are marked provisional or untested.
- The pipeline degrades gracefully when sensors are missing.
- The project contains both live code and offline notebooks; the notebooks are where the derivations and experiments live.
- The repo includes a modified working tree file in [live/interface/dashboard.py](live/interface/dashboard.py) that was not touched while creating this knowledge base.

## 10. If Another AI Needs to Work Here

Use this order of reference:

1. [AI_KNOWLEDGE_BASE.md](AI_KNOWLEDGE_BASE.md)
2. [live/live_hsi.py](live/live_hsi.py)
3. [live/core/config.py](live/core/config.py)
4. [live/core/features.py](live/core/features.py)
5. The relevant file under [live/axes/](live/axes)
6. The relevant notebook or report under [maths/](maths) or [report/](report)

The main mental model is: one sensor stream, one calibration step, five deterministic axes, two presentation surfaces.