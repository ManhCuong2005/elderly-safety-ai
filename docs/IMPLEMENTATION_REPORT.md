# Báo cáo triển khai — 10/11/2026

**Trạng thái tổng thể: CHƯA ĐẠT NGHIỆM THU V1.** Mã nguồn, pipeline, Firebase và APK đã được triển khai/kiểm tra theo bằng chứng dưới đây; độ nhạy phát hiện ngã trên video test vẫn không đạt. Không đánh dấu toàn hệ thống DONE chỉ vì code chạy và unit tests đạt.

**Cập nhật web test:**đã thêm màn hình Flutter Web nhận diện camera/video qua API Python loopback, không Firebase/FCM; build web và APK release cùng source đã PASS. Test hiện76+1=77 Python,7 Flutter. Browser Chrome đã có videoRGB thật, skeleton và nhãn đứng; reset/tua, camera giả lập, offline và viewport được kiểm tra trong web-browser-test.json. Xem WEB_TEST_GUIDE.md.

**Đính chính benchmark:**54 MP4 UR có depth/RGB ghép ngang; các số liệu trước khi tách RGB bên dưới là lịch sử chạy với đầu vào sai, không đại diện đúng năng lực model. Đã sửa tiền xử lý, không đổi rule1.4. Chẩn đoán10 clip cũ với RGB đúng:0 TP/1 FP/5 FN/4 TN; không phải test độc lập. Chi tiết INPUT_LAYOUT_CORRECTION.md. Các số Recall20%/F1 cũ không còn dùng để kết luận độ chính xác.

## 1. Tổng quan

Project tại `D:\DANC2\Project\elderly-safety-ai`. Kiến trúc thực tế: OpenCV→MediaPipe Tasks Pose Landmarker→hình học→temporal window→quy tắc/FSM→queue/worker Firebase Admin→Firestore/FCM→Flutter Android. Chỉ pose dùng pretrained Deep Learning; không có huấn luyện Random Forest hoặc bộ phân loại hành động khác.

Python3.12.10 riêng trong project, MediaPipe0.10.21, OpenCV contrib4.11, Firebase Admin6.9. Flutter3.29/Dart3.7, Material3, Android NDK27, Firebase Auth/Firestore/Messaging và local notifications. Version đầy đủ trong requirements-lock.txt/pubspec.lock. Không push Git, không tạo project Firebase mới, không nâng Blaze, không dùng Cloud Functions hoặc dịch vụ trả phí.

## 2. Dataset

Đã tải60 chuỗi UR Fall:30 Fall,30 Non-Fall. Sáu chuỗi PNG RGB có timestamp nguồn,54 MP4 nguồn. Download gốc483.843.628 byte; tổng thư mục500.109.847 byte tại lần tổng hợp cuối, dưới800 MB/hard cap1 GB. Đã giải mã9180 frame nguồn, số đếm khớp toàn bộ60 chuỗi. Dữ liệu ở ai_engine/datasets; URL/hash/license/split ở metadata/manifest.json; timing/count ở inventory.json. ZIP kiểm tra CRC, archive đã giải nén được xóa để không lưu hai lần.

Nguồn/giấy phép xem DATASET.md. Chưa xác minh subject ID hoặc đầy đủ nhãn ngồi/đứng dậy/cúi/nằm chủ động theo frame; không tự gán nhãn từ thuật toán. Không có onset RGB đáng tin, latency=null. Các test04–08,11–15,16–20,21–25 và26–30 giữ riêng theo từng vòng; không dùng clip đã xem để tuyên bố test mới khách quan.

## 3. Detection Algorithm

Có góc hông/gối/thân, aspect và tương quan các khớp, chuẩn hóa tỷ lệ ảnh, EMA telemetry, window theo timestamp, vận tốc chuẩn hóa thân, walking cần chuyển động liên tục. Thiếu pose, timestamp lỗi/gap, nhiều người nhập nhằng và ra khỏi ảnh có xử lý riêng.

FSM NORMAL→SUSPECTED_FALL→VERIFYING→ALERT hoặc RECOVERED. Cảnh báo sớm lưu/gửi khi đủ tổ hợp tín hiệu; xác minh cập nhật cùng ID, không ghi đè acknowledgment/gửi push trùng. Thân một phần cần confidence cao và nằm trong ảnh; posture công khai UNKNOWN. Có bằng chứng co hình chiếu toàn thân, không suy độ cao vật lý. Nhãn hiển thị debounce riêng; tiền sự kiện cần nhiều frame thô đủ khoảng thời gian. Cấu hình cuối tại configs/calibrated-v1_4.json, công thức trong DETECTION_ALGORITHM.md.

**Test mới26–30,10 video:TP=1,FP=0,FN=4,TN=5. Precision=100%,Recall=20%,F1≈33,3%,FP rate=0.** Đây là cảnh báo nghi ngờ ở fall-28; verified metrics vẫn0 TP/5 FN. CLI chạy trực tiếp toàn clip fall-28 cũng tạo SUSPECTED_FALL tại1,6 giây, không dùng cache/không gửi cloud. Precision dựa một cảnh báo đúng không chứng minh độ chính xác tổng thể100%. Bản1.2 trước đó có1 FP; các báo cáo thất bại cũ giữ nguyên. Các tập test khác nhau, không coi đây là so sánh cải thiện có kiểm soát. Độ nhạy vẫn quá thấp để nghiệm thu.

Các vấn đề quan sát trong phát triển gồm occlusion, body projection, detection nhiều pose/trùng, thiếu tư thế trước/sau sự kiện trong clip ngắn và điều kiện rule chưa phù hợp. Chưa chú giải độc lập đủ để quy toàn bộ false negative cho riêng một nguyên nhân. Cần xem lại dữ liệu/geometry và test mới trước thay đổi tiếp, không đơn giản hạ confidence để tăng số cảnh báo.

## 4. Firebase

Dùng project elderly-safety-ai hiện có. Đã đăng ký Android app package vn.elderlysafety.elderly_safety_app và kiểm tra google-services.json khớp Dart options. Rules đã deploy sau17/17 emulator tests.

Production đã PASS15 kiểm tra: Email/Password server sign-in, Admin tạo/đọc event, client được liên kết đọc profile/status, chặn unlinked/anonymous, chặn giả event, seen/safe acknowledgment server timestamp, escalation giữ safeAt, đăng ký device của chính user và chặn user khác đọc token. Firestore snapshot listener thật PASS. FCM Admin validate-only PASS; không gửi push thực trong bài này.

Các tài khoản/profile thử có ID riêng đã dọn, không sao chép credential vào source. Sau khi người dùng chỉ định email/tên hồ sơ, đã tạo tài khoản Auth thật và liên kết caregiver, đọc lại xác nhận đúng quyền. Tài khoản mới chưa có mật khẩu; người dùng đặt mật khẩu qua Quên mật khẩu trong app. Không gửi email/reset link bằng script. Hồ sơ thật không được điền status/sự kiện giả. Tham chiếu hai báo cáo production và provisioning-status.json (không commit). Key từng dán vào chat cần thu hồi nếu chưa thực hiện.

Collections: users/{uid}/profiles, users/{uid}/devices; profiles/{id}/caregivers,status,events,alerts và deliveries riêng. Flutter không tự cấp quyền hoặc tạo sự kiện AI. Token chỉ chủ tài khoản đọc/ghi. Admin SDK vẫn bỏ qua Rules nên cần bảo vệ máy/key và IAM. Quota/retention xem FIREBASE_SETUP.md.

## 5. Flutter

Có khởi tạo Firebase/auth gate, login/reset mật khẩu, dashboard, history, alerts/detail, profile/settings, multi-profile selection, empty/error/cache/permission states. Giao diện tiếng Việt, Material3 teal, card bo góc. Không tự điền dữ liệu giả. Dashboard tự hết hạn heartbeat; alert có hai thao tác riêng đã xem/xác nhận an toàn. Kiểm tra membership từ server trước mở profile hoặc alert từ notification.

Foreground local notification/channel, Android permission, background handler, cold-start payload, token refresh và nhiều device theo tài khoản đã có code. FCM receipt/tap trên thiết bị thật chưa kiểm thử. Logout cố gắng xóa đăng ký token trước sign-out; cần mạng để hoàn tất an toàn trên thiết bị dùng chung.

flutter analyze:không có issue. flutter test:4/4 PASS. Android debug APK build thành công ở build/app/outputs/flutter-apk/app-debug.apk. Chưa cài/mở trên điện thoại thật, chưa có bản ký phát hành bằng keystore riêng.

Cập nhật kiểm tra build: `flutter build apk --release` đã thành công, tạo app-release.apk khoảng47,8 MB. apksigner verify PASS, certificate CN=Android Debug; release-mode để cài thử, chưa có khóa ký phát hành riêng. Báo cáo artifact/hash tại android-release-build.json. Web chưa triển khai: chưa có target web, FirebaseOptions mới có Android và xử lý thông báo hiện dành cho Android.

## 6. Testing

| Hạng mục | Kết quả |
|---|---|
| Python unit/regression |61 PASS,0 fail;2 deprecation warnings từ protobuf dependency |
| Dependency integrity |pip check PASS |
| Python compilation |PASS |
| Firestore Rules emulator |17 PASS |
| Python→Firestore emulator/retry/escalation |PASS |
| Flutter analyze |PASS |
| Flutter unit/widget |4 PASS |
| Android debug build |PASS |
| Webcam0 capture/inference/release/reopen |PASS15 frame640×480;0 pose toàn thân tin cậy |
| Production Auth/Firestore/rules/ack |15 checks PASS |
| Production realtime snapshot |PASS |
| FCM validate-only |PASS;không chứng minh nhận push |
| Video test cuối |FAIL nghiệm thu:1/5 ngã được cảnh báo nghi ngờ,4 FN |
| Webcam posture/skeleton và Android/FCM/cross-network/soak |PENDING_USER/DEVICE_TEST |

Đã sửa các lỗi thực tế: SDK/runtime ban đầu thiếu Python, Gradle NDK mismatch, Dart lint/async context, test integration đọc trước write hoàn tất, continuity khóa vĩnh viễn sau một ambiguity, gap thời gian cộng sai vào verification, một chân bị che làm mất toàn bộ geometry, nhãn/nguồn test notification, early safe acknowledgment và kiểm tra quyền trước hiển thị cache. Những sửa logic không đủ làm thuật toán đạt video benchmark.

Throughput file thật trong processed/*.performance.json. Probe webcam15 frame đạt khoảng2,53 FPS khi tính cả mở camera/model;10 frame sau khởi động có throughput khoảng33,4 FPS, median inference22,2 ms. Mẫu ngắn,0 pose toàn thân tin cậy, có thể chịu buffering nên chưa chứng minh realtime10–15 FPS khi giám sát người lâu dài. Bảng tại TEST_RESULTS.csv; hướng dẫn A–L tại TESTING_GUIDE.md.

## 7. Hướng dẫn chạy

```powershell
cd D:\DANC2\Project\elderly-safety-ai
.\scripts\run-local.cmd --source 0
# Video local, không gửi Firebase/FCM:
.\scripts\run-local.cmd --source ai_engine/datasets/raw/fall-04-cam0.mp4
# Connected chỉ webcam, cần profile đã provision:
$env:GOOGLE_APPLICATION_CREDENTIALS='DUONG_DAN_FILE_CREDENTIAL_RIENG'
.\tools\python\python.exe ai_engine/main.py --source 0 --mode connected --profile MA_HO_SO
# Android:
cd flutter_app
flutter run -d DEVICE_ID
```

Lệnh provisioning/dataset/evaluation trong README/FIREBASE_SETUP. Local và evaluation không gửi cảnh báo thật. Connected từ chối video/demo. Q dừng và nhả camera; Space pause/resume; R chọn lại người. Có thể dùng scripts/firebase_smoke.py với hồ sơ thử để kiểm tra push có nhãn SIMULATED_TRANSPORT_TEST sau khi có điện thoại; không dùng sự kiện đó làm bằng chứng nhận diện ngã.

## 8. Các phần chưa hoàn thành

1. **Thuật toán chưa đạt độ nhạy thực tế**:đây là phần thiếu quan trọng nhất, không bị che bằng số unit tests. Cần cải tiến quy tắc/độ quan sát và bổ sung ground truth hoạt động/onset, sau đó đánh giá test mới độc lập. Không huấn luyện model phân loại trong V1 để lách phạm vi.
2. **Kiểm thử trực tiếp**:webcam capture đã chạy, cần bố trí người toàn thân và kiểm tra skeleton/tư thế; nối Android có Play Services để thử app/FCM/tap/nhiều device/hai mạng và chạy bền30 phút.
3. **Tài khoản người dùng**:đã tạo và liên kết theo chỉ định. Người dùng cần tự đặt mật khẩu qua Quên mật khẩu, đăng nhập trên điện thoại và cấp quyền thông báo; không gửi mật khẩu vào chat.
4. **Các giới hạn vận hành**:queue chưa bền qua restart; khi queue đầy/tắt lúc backlog có thể mất sự kiện; FCM claim at-most-once có delivery_unknown; chưa có retention job; chưa có SLA/quota bảo đảm nhiều engine; camera2D chưa hiệu chuẩn và danh tính chỉ dựa continuity.

Các bằng chứng nằm ở verification-summary.json, evaluation-*.json, python-tests.xml và hai báo cáo production. Đã có một cảnh báo nghi ngờ trên video FALL thật; không tuyên bố xác minh ngã thành công hoặc hệ thống đã đủ độ an toàn.
