# An Tâm — AI Elderly Safety V1

Python/OpenCV/MediaPipe xử lý trên laptop → Firestore và FCM → Flutter Android tiếng Việt. Không huấn luyện bộ phân loại, không livestream, không dùng Cloud Functions hoặc nâng cấp Blaze.

**Trạng thái: bản triển khai thử nghiệm, chưa đạt nghiệm thu phát hiện ngã.** Pipeline chạy được trên video thật; kiểm thử logic đạt nhưng đánh giá ban đầu bỏ sót ngã. Không đánh đồng kiểm thử FSM bằng landmarks tổng hợp với độ chính xác thực tế. Đọc [báo cáo kết quả](docs/IMPLEMENTATION_REPORT.md) và [hướng dẫn kiểm thử](docs/TESTING_GUIDE.md) trước khi vận hành.

**Đã có web test nhận diện:**chạy Python bằng `scripts\run-web-ai.cmd`, rồi trong flutter_app chạy `flutter run -d chrome --web-port 7357`. Web dùng camera/video→Python local, không Firebase/thông báo; Android vẫn là app người chăm sóc. Đọc [WEB_TEST_GUIDE](docs/WEB_TEST_GUIDE.md).

**Hiệu chỉnh đầu vào:**54 MP4 UR là khung ghép depth/RGB; đã xác minh và tách RGB. Các benchmark cũ không đại diện đúng RGB. Xem [ghi nhận sửa đầu vào](docs/INPUT_LAYOUT_CORRECTION.md); chẩn đoán với RGB đúng vẫn chưa đạt yêu cầu ngã.

## Chạy nhanh trên máy này

Mở PowerShell:

```powershell
cd D:\DANC2\Project\elderly-safety-ai
.\tools\python\python.exe -m pytest ai_engine/tests -q
.\scripts\run-local.cmd --source 0
```

`Q` dừng, `Space` tạm dừng/tiếp tục, `R` chọn lại người khi cần. Khi khởi động chỉ để một người trong khung hình. Webcam index0 đã mở, đọc15 frame640×480 và nhả/mở lại được; mẫu thử chưa có pose toàn thân tin cậy. GUI, nhận diện tư thế trực tiếp và chạy bền vẫn cần kiểm thử với người dùng.

Video có sẵn:

```powershell
.\scripts\run-local.cmd --source ai_engine/datasets/raw/fall-04-cam0.mp4
.\scripts\run-local.cmd --source ai_engine/datasets/raw/fall-01-cam0-rgb --sync ai_engine/datasets/metadata/fall-01-data.csv
```

CLI dùng model Full và configs/calibrated-v1_4.json; không đổi ngưỡng khi sửa đầu vào. Nguồn dataset đã có metadata được tự tách RGB, webcam/videoRGB khác giữ nguyên. Cache ghép cũ bị từ chối khi đánh giá RGB. Chẩn đoán sau sửa trên10 clip cũ:TP0,FP1,FN5,TN4; không phải kiểm định độc lập và không dùng số Recall20% cũ như độ chính xác hệ thống.

## Flutter Android

```powershell
cd flutter_app
flutter pub get
flutter analyze
flutter test
flutter run -d <ANDROID_DEVICE_ID>
```

APK debug: `flutter_app/build/app/outputs/flutter-apk/app-debug.apk`. Cấu hình client dùng project `elderly-safety-ai`, package `vn.elderlysafety.elderly_safety_app`; không chứa private key. APK debug dành cho thử nghiệm; phát hành cần keystore riêng.

Đã build cả web và release-mode APK ở flutter_app/build/app/outputs/flutter-apk/app-release.apk. APK vẫn ký Android Debug để cài thử, chưa có keystore phát hành riêng/chưa kiểm thử trên điện thoại. Web test không cần Firebase Web; khởi tạo theo nền tảng nên không ảnh hưởng luồng Firebase Android.

## Firebase thật

Rules đã kiểm thử emulator và deploy lên project có sẵn. Auth server, Firestore production, listener realtime, phân quyền/xác nhận và FCM validate-only đã PASS bằng dữ liệu thử riêng được dọn sau test. Cần liên kết tài khoản/hồ sơ thật và kiểm thử điện thoại. File Admin credential người dùng cung cấp được đọc trực tiếp, không sao chép vào repository. Hướng dẫn tại [FIREBASE_SETUP](docs/FIREBASE_SETUP.md).

```powershell
cd D:\DANC2\Project\elderly-safety-ai
$env:GOOGLE_APPLICATION_CREDENTIALS='D:\private\elderly-safety-ai-service-account.json'
.\tools\python\python.exe scripts/admin.py --profile nguoi-than-01 --name 'Người thân' --caregiver-email 'EMAIL_DA_TAO_TRONG_AUTH'
# Lệnh trên chỉ xem trước. Sau khi kiểm tra đúng tài khoản/hồ sơ:
.\tools\python\python.exe scripts/admin.py --profile nguoi-than-01 --name 'Người thân' --caregiver-email 'EMAIL_DA_TAO_TRONG_AUTH' --apply --confirm nguoi-than-01
.\tools\python\python.exe ai_engine/main.py --source 0 --mode connected --profile nguoi-than-01
```

Không dán credential vào chat, không bỏ credential trong Flutter. `.env.example` chỉ là mẫu; chương trình đọc biến môi trường, không tự nạp `.env`.

## Dataset và tái lập

```powershell
.\tools\python\python.exe ai_engine/scripts/download_dataset.py --format rgb --per-class 3
.\tools\python\python.exe ai_engine/scripts/download_dataset.py --format mp4 --start-index 4 --per-class 7 --append
.\tools\python\python.exe ai_engine/scripts/download_dataset.py --format mp4 --start-index 11 --per-class 10 --append
.\tools\python\python.exe ai_engine/scripts/download_dataset.py --format mp4 --start-index 21 --per-class 5 --append
.\tools\python\python.exe ai_engine/scripts/download_dataset.py --format mp4 --start-index 26 --per-class 5 --append
.\tools\python\python.exe scripts/verify_dataset_layout.py
.\tools\python\python.exe ai_engine/scripts/evaluate.py --extract --extract-split test_v1_4 --split test_v1_4 --config ai_engine/configs/calibrated-v1_4.json --cache-tag rgb_input_fixed --report-tag=-rgb_input_fixed --model ai_engine/models/pose_landmarker_full.task
```

Downloader giới hạn tổng thư mục1.000.000.000 byte, tính cả archive và dữ liệu giải nén. Hiện có60 chuỗi (30 Fall/30 Non-Fall), khoảng500 MB, dưới800 MB. Không chạy song song nhiều downloader. Nhãn lấy từ nguồn, không từ bộ phát hiện. Clip01/09/10 thuộc calibration;02/03 thuộc test đầu;04–08,11–15,16–20,21–25 là các vòng test trước;26–30 là test mới bản1.4. Chưa xác minh độc lập theo người. Không sửa ngưỡng theo test cuối rồi dùng lại kết quả đó làm đánh giá khách quan.

## Cấu trúc

- `ai_engine/src`: camera, pose, features, posture, motion, fall detection, FSM, Firebase.
- `ai_engine/scripts`: tải chọn lọc và đánh giá offline.
- `ai_engine/tests`: kiểm thử công thức, thời gian, FSM và tình huống mất dấu.
- `flutter_app`: ứng dụng Android, giao diện và kiểm thử heartbeat/link thông báo.
- `firebase`: Security Rules, Rules tests và Python emulator integration.
- `docs`: thiết kế, dữ liệu, vận hành, kiểm thử và báo cáo bằng chứng.
- `tools`: Python riêng, dependency/cache và log, không commit.

Cài lại môi trường Python trên Windows: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`. Cờ chỉ áp dụng tiến trình cài đặt này, không đổi Execution Policy toàn hệ thống.
