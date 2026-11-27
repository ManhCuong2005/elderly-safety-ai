# Đánh giá model CameraAI (MoveNet Thunder 256×256 + 54 clip UR Fall)

- Pose backbone: **MoveNet SinglePose Thunder v4 (256×256, float16)**
- Classifier chốt: **MLP NeuralNet** · ngưỡng `0.7` · `urfall-thunder-bbf712a7f931`
- Tập dữ liệu (chia độc lập theo mã chuỗi video, không rò rỉ):
  - Train (`04..20`): **34 clip** (44 cửa sổ Fall, 223 cửa sổ No_Fall)
  - Validation (`21..25`): bắt **3/5** ca ngã, báo giả **1**
  - Holdout Test độc lập (`26..30`): bắt **4/5** ca ngã (Recall `80.0%`), báo giả **4**
- Toàn bộ 27 clip ADL UR Fall (`adl-04..30`): tổng báo giả **5**
