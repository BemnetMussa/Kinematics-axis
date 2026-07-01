# """
# SHL (Sussex-Huawei Locomotion) Dataset Loader Stub.
# Compatible with SHL Challenge 2018/2020/2021 Txt formats.
# """
# import os
# import numpy as np
# import pandas as pd

# # SHL 2018 Label mapping
# SHL_LABELS = {
#     1: "stationary",
#     2: "on_foot",
#     3: "on_foot",
#     4: "cycling",
#     5: "in_vehicle",
#     6: "in_vehicle",
#     7: "in_vehicle",
#     8: "in_vehicle"
# }

# def load_shl_windows(data_dir, placement="Hips", fs=100, window_sec=5.0, overlap=0.5):
#     """
#     Expects files like 'Hips_Accelerometer.txt', 'Label.txt' in data_dir.
#     Columns are usually: [Timestamp, X, Y, Z]
#     """
#     window_samples = int(fs * window_sec)
#     hop_samples = int(window_samples * (1 - overlap))
    
#     # Load Label
#     label_path = os.path.join(data_dir, "Label.txt")
#     if not os.path.exists(label_path):
#         raise FileNotFoundError(f"Label.txt not found in {data_dir}")
    
#     labels_raw = pd.read_csv(label_path, sep=r"\s+", header=None).values
#     # SHL labels are: [Timestamp, LabelID]
    
#     # Load Sensors
#     sensors = ["Accelerometer", "Gyroscope", "Magnetometer", "Orientation"]
#     data = {}
#     for s in sensors:
#         path = os.path.join(data_dir, f"{placement}_{s}.txt")
#         if os.path.exists(path):
#             # Acc/Gyr/Mag: [T, X, Y, Z]; Orientation: [T, W, X, Y, Z]
#             df = pd.read_csv(path, sep=r"\s+", header=None)
#             data[s.lower()] = df.iloc[:, 1:].values # exclude timestamp
#         else:
#             print(f"Warning: {s} not found for {placement}")
#             data[s.lower()] = None

#     # Slice into windows
#     out = []
#     n_samples = len(labels_raw)
#     for start in range(0, n_samples - window_samples + 1, hop_samples):
#         end = start + window_samples
#         win_labels = labels_raw[start:end, 1]
        
#         # Only keep windows with a single, consistent label (non-null)
#         unique_labels = np.unique(win_labels)
#         if len(unique_labels) == 1 and unique_labels[0] in SHL_LABELS:
#             label_id = unique_labels[0]
            
#             win = {
#                 "accel": data["accelerometer"][start:end] if data["accelerometer"] is not None else None,
#                 "gyro": data["gyroscope"][start:end] if data["gyroscope"] is not None else None,
#                 "mag": data["magnetometer"][start:end] if data["magnetometer"] is not None else None,
#                 "quat": data["orientation"][start:end] if data["orientation"] is not None else None,
#                 "label": SHL_LABELS[label_id],
#                 "kind": f"shl_{label_id}"
#             }
#             out.append(win)
            
#     return out

# if __name__ == "__main__":
#     # Test stub
#     print("SHL Loader initialized. Mapping SHL (1-8) to Kinematic Axis labels.")
#     print("Usage: windows = load_shl_windows('/path/to/SHL_Dataset/User1/220617')")
