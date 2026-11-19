# Hướng dẫn kiểm thử V1 — dành cho người mới

**Cập nhật 10/11/2026:** bản web local đã có hướng dẫn tại [WEB_TEST_GUIDE.md](WEB_TEST_GUIDE.md). Đã sửa đầu vào MP4 ghép depth/RGB; benchmark cũ không còn dùng để đánh giá độ chính xác RGB, xem [INPUT_LAYOUT_CORRECTION.md](INPUT_LAYOUT_CORRECTION.md).

Mở PowerShell. Các lệnh dưới đây chạy từ `D:\DANC2\Project\elderly-safety-ai` trừ khi có ghi khác. Đọc README để hiểu giới hạn phát hiện hiện tại. PASS của một bài kỹ thuật không tự biến thành PASS của toàn bộ hệ thống.

```powershell
cd D:\DANC2\Project\elderly-safety-ai
```

Không tự diễn ngã. Dùng video có nhãn để thử phát hiện ngã; những kiểm tra tư thế trực tiếp chỉ thực hiện hoạt động bình thường trong điều kiện phù hợp.

## A. Cài đặt và khởi chạy

**Mục tiêu:** xác nhận Python, dependency và lệnh CLI chạy được.

**Chuẩn bị:** Internet nếu cài lại; khoảng vài GB cho runtime/SDK/cache, dataset dưới1 GB riêng. Flutter tại `D:\Flutter`; Python riêng trong `tools/python` đã cài trên máy này.

```powershell
.\tools\python\python.exe --version
.\tools\python\python.exe -m pip check
.\tools\python\python.exe -m pytest ai_engine/tests -q
.\tools\python\python.exe ai_engine/main.py --help
```

Nếu chưa có runtime: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`.

**Mong đợi/PASS:** phiên bản Python3.12, pip không báo dependency hỏng, toàn bộ tests đạt, CLI có --source/--mode. **FAIL:** import lỗi hoặc test thất bại. **Xử lý:** chạy setup, dùng đúng Python trong project, lưu lỗi vào phiếu kết quả; không cài thêm opencv-python song song với opencv-contrib-python.

## B. Webcam và MediaPipe

**Mục tiêu:** mở camera thật, thấy skeleton, giải phóng thiết bị.

**Chuẩn bị:** cấp quyền camera Windows, đóng Teams/Zoom/app chiếm webcam; một người, toàn thân trong ảnh; model file có sẵn.

```powershell
.\scripts\run-local.cmd --source 0
```

Đứng trong ảnh, quan sát skeleton/FPS; Space tạm dừng, Space tiếp tục, Q thoát. Mở lại lệnh để kiểm tra camera đã nhả. Thử thêm `--source 1` nếu có webcam USB.

**Mong đợi/PASS:** hình thật, khớp phù hợp, không đứng hình khi thoát/mở lại. **FAIL:** không có ảnh, model không mở, chương trình chiếm camera sau thoát. **Xử lý:** kiểm tra quyền, source index và model; khi cần chọn lại người, kiểm tra cảnh rồi nhấn R. Probe kỹ thuật đã mở/đọc15 frame/nhả/mở lại webcam0; chưa có pose toàn thân tin cậy nên GUI/skeleton/tư thế trực tiếp vẫn PENDING_USER_TEST.

## C. Đứng/ngồi/nằm/đi lại

**Mục tiêu:** đánh giá nhãn và độ ổn định trên camera cụ thể.

**Chuẩn bị:** camera thấy toàn thân; thực hiện tư thế bình thường, không thử diễn ngã. Dùng Local Mode như B.

**Thao tác:** đứng yên5 giây; ngồi ghế bình thường5 giây; đứng lên; đi vài bước liên tục trong vùng ảnh; nếu phù hợp dùng video nằm có sẵn thay thử trực tiếp. Ghi UNKNOWN khi bị che thay vì ép nhãn.

**Mong đợi/PASS:** STANDING/SITTING/LYING đúng khi đủ góc quan sát; WALKING chỉ sau chuyển động liên tục, đứng lắc nhẹ không thành đi. **FAIL:** nhấp nháy liên tục, ép LYING khi ngồi hoặc WALKING từ1 frame. **Xử lý:** đổi bố trí camera, lưu video đồng ý của người tham gia để chú giải và đánh giá độc lập. Unit tests chỉ kiểm tra quy tắc hình học tổng hợp; nhãn thật theo frame còn PENDING_COVERAGE.

## D. Dataset ngã thật và false alarm

**Mục tiêu:** tính confusion matrix theo clip, không tự gán nhãn bằng engine.

**Chuẩn bị:** manifest, raw, cache có sẵn; không cần Firebase. Nếu tải lại dùng hai lệnh dataset trong README, không tải toàn bộ dataset.

```powershell
.\tools\python\python.exe scripts/verify_dataset_layout.py
.\tools\python\python.exe ai_engine/scripts/evaluate.py --extract --extract-split test_v1_4 --split test_v1_4 --config ai_engine/configs/calibrated-v1_4.json --cache-tag rgb_input_fixed --report-tag=-rgb_input_fixed --model ai_engine/models/pose_landmarker_full.task
```

Mở `docs/evaluation-test_v1_4-rgb_input_fixed.json`. Đây là kiểm tra chẩn đoán sau sửa đầu vào, không phải test độc lập mới và không hiệu chỉnh lại ngưỡng. Kiểm tra TP/FP/FN/TN, Precision, Recall, F1, FP rate, coverage và frame thiếu pose; latency null khi chưa có onset nguồn đáng tin. `metrics` tính cảnh báo nghi ngờ, `verified_metrics` chỉ tính cảnh báo đã đủ bằng chứng xác minh; cả hai không khẳng định chắc chắn người đã ngã.

**Mong đợi/PASS kỹ thuật:** mọi clip đọc được, báo cáo sinh ra, không gửi FCM. **PASS cảnh báo nghi ngờ:** video FALL phải có SUSPECTED_FALL/POSSIBLE_FALL, clip bình thường không cảnh báo; mọi FN/FP phải ghi. Xác minh sau sự kiện chấm riêng. Chẩn đoán RGB đúng có TP0/FP1/FN5/TN4, chưa đạt yêu cầu phát hiện. Kỳ vọng cũ về cảnh báo fall-28 xuất phát từ đầu vào ghép sai và không còn áp dụng. **Xử lý:** xem quality/góc camera/thời gian trước-sau ngã; không loại clip lỗi hoặc chỉnh ngưỡng trên các clip đã đánh giá. Phát triển tiếp cần test mới chưa xem.

## E. Nằm lâu, bất động, ra khỏi ảnh

**Mục tiêu:** phân biệt pose ít chuyển động với không thấy người.

**Chuẩn bị:** Local Mode, một video đủ dài hoặc cảnh trực tiếp phù hợp; demo không được dùng Connected Mode.

```powershell
.\scripts\run-local.cmd --source 0 --demo --output tools/demo-telemetry.jsonl
```

**Thao tác:** giữ một tư thế quan sát được hơn20 giây; dùng cảnh/video nằm quan sát được hơn15 giây; sau đó người ra khỏi ảnh. Đọc events trong JSONL. Với vận hành thường không dùng --demo (ngưỡng30 phút/10 phút).

**Mong đợi/PASS:** từng đợt chỉ có1 alert tương ứng, mất landmarks không tạo ABNORMAL_INACTIVITY/POSSIBLE_FALL; UI báo PERSON_NOT_DETECTED hoặc yêu cầu chọn lại. **FAIL:** chỉ mất người đã báo ngã hoặc thời gian mất dấu được cộng vào bất động. **Xử lý:** kiểm tra max_gap, confidence và continuity; chạy lại pytest để xác định regression.

## F. Firebase Authentication

**Mục tiêu:** đăng nhập, báo lỗi, reset mật khẩu và giữ phiên.

**Chuẩn bị:** tài khoản Email/Password thật do quản trị viên tạo trong `elderly-safety-ai`, APK đã cài, Internet. Không lưu mật khẩu vào log/phiếu.

**Thao tác:** đăng nhập sai một lần, đăng nhập đúng, đóng/mở app, dùng Quên mật khẩu cho email của chính mình, đăng xuất.

**Mong đợi/PASS:** sai mật khẩu có lỗi dễ hiểu, đúng thì vào trang hồ sơ, mở lại giữ phiên, reset có thông báo phù hợp, logout về login. **FAIL:** app crash hoặc vào hồ sơ không liên kết. **Xử lý:** kiểm tra Email/Password, config, mạng/giờ máy. Auth server đã PASS bằng tài khoản thử tạm được dọn; giao diện Android, giữ phiên và email reset thực tế vẫn PENDING_DEVICE_TEST.

## G. Firestore realtime và heartbeat

**Mục tiêu:** xác minh đường Python→Firestore→Flutter và offline.

**Chuẩn bị:** credential riêng, user đã liên kết hồ sơ bằng admin.py; xem FIREBASE_SETUP. Không dùng video ở Connected Mode.

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS='D:\private\elderly-safety-ai-service-account.json'
.\tools\python\python.exe ai_engine/main.py --source 0 --mode connected --profile nguoi-than-01
```

**Thao tác:** trên điện thoại mở hồ sơ đúng, đổi tư thế bình thường, quan sát cập nhật cloud đã gộp. Q dừng engine; chạy lại rồi tắt đột ngột để kiểm tra heartbeat quá hạn.

**Mong đợi/PASS:** trạng thái/thời gian thay đổi, dừng đúng cách ghi offline, dừng đột ngột chuyển offline sau tối đa khoảng100 giây (90 giây+UI10 giây). **FAIL:** ONLINE mãi hoặc frame/video bị upload. **Xử lý:** kiểm tra credential, profile và network. Production Admin writes/client reads/snapshot listener đã PASS; đường hiển thị trên Flutter thật và webcam vẫn phải làm bài này.

## H. Flutter Android

**Mục tiêu:** kiểm tra source, tests và APK.

**Chuẩn bị:** Flutter3.29/Dart3.7, Android SDK, NDK27.0.12077973, Java17+.

```powershell
cd flutter_app
flutter analyze
flutter test
flutter build apk --debug
flutter devices
flutter run -d <DEVICE_ID>
cd ..
```

**Mong đợi/PASS:** analyze không lỗi, tests đạt, APK tồn tại và cài/mở được trên máy thật. Kiểm tra tất cả tab, empty state, mạng tắt, permission denied và xoay/đổi cỡ chữ. **FAIL:** overflow/crash hoặc hiển thị dữ liệu giả khi chưa có hồ sơ. **Xử lý:** NDK mismatch đặt đúng version trong build.gradle.kts; SDK license/cmdline-tools dùng Android Studio SDK Manager và tự đọc/chấp nhận license. Build đã thành công ở máy phát triển, cài/mở điện thoại vẫn PENDING_DEVICE_TEST.

## I. FCM foreground/background/terminated

**Mục tiêu:** xác minh nhận push và mở đúng chi tiết, không chỉ API gửi thành công.

**Chuẩn bị:** Android có Google Play Services, đã mở app ít nhất1 lần và đăng nhập, bật POST_NOTIFICATIONS, user/hồ sơ thử riêng, token đã đăng ký.

```powershell
.\tools\python\python.exe scripts/firebase_smoke.py --profile ho-so-test --confirm ho-so-test --notify
```

**Thao tác:** lần1 để app foreground; lần2 đưa app background; lần3 đóng app theo cách thông thường rồi gửi, bấm thông báo để cold-start. Không force-stop trong Android Settings vì hệ điều hành có thể chặn nhận đến khi mở lại. Mỗi lần tạo ID test riêng; lệnh hiện rõ SIMULATED_TRANSPORT_TEST.

**Mong đợi/PASS:** nhận từng trường hợp, không hiện hai lần, tap đến đúng alert, source là simulation; bấm đã xem không tự đặt safeAt; xác nhận an toàn đặt safeAt/safeBy. Thử nhiều điện thoại và logout/tắt notification một điện thoại.

**FAIL:** API accepted nhưng không có thông báo, tap sai hồ sơ, gửi lặp, user khác đọc token. **Xử lý:** kiểm tra permission/channel/battery restriction, Play Services, token refresh và Rules; tra delivery state mà không in token. FCM validate-only đã PASS, không gửi thật. Nhận push ở cả3 trạng thái vẫn PENDING_DEVICE_TEST.

## J. Hai mạng khác nhau

**Mục tiêu:** kiểm tra giám sát từ xa không cần chung Wi-Fi.

**Chuẩn bị:** G và I đã PASS; laptop dùng Wi-Fi, điện thoại tắt Wi-Fi dùng4G/5G.

**Thao tác:** mở dashboard, đổi tư thế bình thường, gửi sự kiện transport test như I; sau đó tắt Internet laptop và điện thoại lần lượt.

**Mong đợi/PASS:** trạng thái và thông báo đến qua Internet, mất kết nối hiển thị stale/cache đúng, không yêu cầu IP LAN của laptop. **FAIL:** chỉ hoạt động chung Wi-Fi hoặc vẫn báo trực tiếp khi không có mạng. **Xử lý:** kiểm tra mạng/DNS/Firestore permission; không cần mở cổng router.

## K. Bảo mật và quyền

**Mục tiêu:** không truy cập chéo hồ sơ, không tự cấp quyền/tạo ngã, token riêng tư.

**Chuẩn bị:** Node/Java, dependency trong firebase đã cài; emulator không dùng dữ liệu thật.

```powershell
npm.cmd --prefix firebase install
firebase.cmd emulators:exec --only firestore --project demo-elderly-safety "npm.cmd --prefix firebase test"
firebase.cmd emulators:exec --only firestore --project demo-elderly-safety "tools\python\python.exe firebase\tests\publisher_smoke.py"
.\tools\python\python.exe scripts/check_secrets.py
```

**Mong đợi/PASS:**17 Rules tests, Python integration và secrets scan đạt. Trên điện thoại user không liên kết không đọc được profile; viewer không được xác nhận; caregiver chỉ sửa trường ack, không sửa event kind. **FAIL:** bất kỳ truy cập trái phép nào thành công. **Xử lý:** không mở allow read/write true, sửa rules rồi chạy lại emulator trước deploy. Sau khi deploy, kiểm tra lại bằng user thật vì Admin SDK luôn bỏ qua Rules.

## L. Hiệu năng và ổn định

**Mục tiêu:** đo tốc độ thực và khi mất mạng, không tự khẳng định đạt realtime.

**Chuẩn bị:** video thật, hoặc webcam đã cấp quyền; Connected Mode cần cấu hình G. Đóng ứng dụng nặng khác.

```powershell
.\tools\python\python.exe ai_engine/main.py --source ai_engine/datasets/raw/fall-04-cam0.mp4 --headless --output tools/performance.jsonl
```

**Thao tác:** ghi FPS tổng CLI và throughput trong processed/performance JSON; thử camera30 phút, ngắt mạng1–2 phút rồi kết nối lại, dừng đúng cách và mở lại. Theo dõi RAM, queue health, Firestore Usage. FPS inference overlay khác FPS camera và FPS cả pipeline.

**Mong đợi/PASS:** không treo webcam do mạng, queue hữu hạn, worker reconnect, tài nguyên giải phóng, quota không vượt; mục tiêu10–15 FPS phải đo trên camera thật. **FAIL:** crash/leak, queue tăng vô hạn, ghi cloud mỗi frame. **Xử lý:** giảm độ phân giải/FPS, dùng model lite, xem log lỗi đã che token; lỗi queue đầy có thể mất event mới nên ghi nhận hạn chế. Chưa chạy soak30 phút trong phiên này.

## Phiếu kết quả

Sao chép [TEST_RESULTS.csv](TEST_RESULTS.csv) để ghi ngày, thiết bị, phiên bản, PASS/FAIL/PENDING và bằng chứng. Khi không có thiết bị/credential, ghi PENDING tương ứng, không sửa thành PASS theo suy đoán. Khi thuật toán bỏ sót một clip FALL, phải ghi FN ngay cả khi nguyên nhân là không quan sát được pose.
