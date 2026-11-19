# Cấu hình Firebase Spark

Project hiện có `elderly-safety-ai`, Firestore Standard `(default)` tại `asia-southeast1` theo cấu hình người dùng cung cấp. Không tạo project mới, không bật Blaze, không dùng Cloud Functions. Android app đã đăng ký package `vn.elderlysafety.elderly_safety_app`; `google-services.json` và Dart FirebaseOptions khớp nhau. Không cần chạy lại FlutterFire configure để dùng cấu hình này.

## Dữ liệu

| Đường dẫn | Chủ thể ghi | Nội dung |
|---|---|---|
| `users/{uid}` | Admin | dữ liệu tài khoản tối thiểu |
| `users/{uid}/profiles/{profileId}` | Admin | hồ sơ được liên kết và role |
| `users/{uid}/devices/{deviceId}` | chính uid | token FCM riêng từng thiết bị |
| `profiles/{profileId}` | Admin | displayName, notes tùy chọn |
| `profiles/{profileId}/caregivers/{uid}` | Admin | role caregiver/viewer |
| `profiles/{profileId}/status/current` | AI Engine Admin | trạng thái + heartbeat |
| `profiles/{profileId}/events/{id_kind}` | AI Engine Admin | sự kiện có origin |
| `profiles/{profileId}/alerts/{id}` | AI Engine Admin | cảnh báo và xác nhận |
| `profiles/{profileId}/alerts/{id}/deliveries/{hash}` | Admin | trạng thái gửi, không token |

Mọi rule còn lại mặc định deny. Caregiver chỉ cập nhật cặp seenBy/seenAt hoặc safeBy/safeAt của hồ sơ được cấp quyền, uid phải trùng người đăng nhập, timestamp phải là serverTimestamp. Viewer chỉ xem. Flutter không tự ghi event, status, profile hoặc quyền. FCM token chỉ chủ tài khoản đọc/ghi; không đưa token vào event/log.

## Credential riêng và tài khoản

1. Firebase Console → Project settings → Service accounts → Firebase Admin SDK. Nếu chưa có key, người quản trị tự tạo và giữ file JSON ngoài repository, ví dụ `D:\private\elderly-safety-ai-service-account.json`. Không gửi nội dung file vào chat.
2. Chỉ cấp IAM cần cho Firestore/FCM và thao tác quản trị Auth cho máy tin cậy. Nếu dùng credential chạy engine lâu dài, tách khỏi credential provisioning có quyền Auth. Security Rules không giới hạn được Admin SDK.
3. Authentication → Users → tạo tài khoản người thân Email/Password. Không dùng mật khẩu mặc định hoặc commit mật khẩu.
4. Trong PowerShell, đặt `$env:GOOGLE_APPLICATION_CREDENTIALS='D:\private\elderly-safety-ai-service-account.json'`.
5. Chạy `scripts/admin.py` theo README để xem trước và liên kết. `--apply --confirm <profile-id>` mới ghi batch. Không có màn hình tự nâng quyền trong Flutter.

CLI đã có phiên đăng nhập khi triển khai. Người dùng đã cung cấp đường dẫn credential mới; file được đọc trực tiếp, không sao chép key vào source. Test production đã PASS Auth Email/Password, Python→Firestore→client REST, chặn tài khoản không liên kết/ẩn danh, chặn giả mạo event, acknowledgment bằng server timestamp, quyền token và listener snapshot thật. FCM validate-only PASS; chưa chứng minh điện thoại nhận. Tài khoản/hồ sơ thử riêng đã dọn, xem `live-firebase-test.json` và `live-transport-test.json`. Nếu CLI hết phiên: `firebase.cmd login` do người dùng thực hiện.

Có thể chạy lại test production cô lập (tạo rồi dọn tài nguyên thử, không gửi push thật):

```powershell
.\tools\python\python.exe scripts/live_firebase_test.py --run
.\tools\python\python.exe scripts/live_transport_test.py --run
```

Hai lệnh cần biến GOOGLE_APPLICATION_CREDENTIALS. Test không tạo hồ sơ thật hoặc tự liên kết người thân; thực hiện provisioning thật theo email/tên người dùng chỉ định. Credential nằm ngoài thư mục monorepo; tránh thêm nó khi tạo Git repository ở thư mục cha. Key đã dán vào chat cần được thu hồi nếu chưa thực hiện.

Đổi quyền bằng admin.py --role viewer/caregiver. Thu hồi liên kết bằng --revoke, vẫn cần --apply --confirm đúng profile ID; lệnh chỉ xóa membership/link, giữ hồ sơ và tài khoản Auth. Luôn chạy dry-run trước khi apply.

Nếu email chưa có trong Auth, thêm --create-user. Dry-run chỉ mô tả; --apply tạo tài khoản không mật khẩu, kiểm tra hỗ trợ reset nhưng không gửi/lưu/in link. Người chăm sóc dùng Quên mật khẩu trong app để nhận email và tự đặt mật khẩu. Tài khoản/hồ sơ người dùng chỉ định trong phiên này đã được tạo và đọc lại xác nhận caregiver; chưa ghi sự kiện/status giả vào hồ sơ thật.

## Rules và kiểm thử

```powershell
cd D:\DANC2\Project\elderly-safety-ai
npm.cmd --prefix firebase install
firebase.cmd emulators:exec --only firestore --project demo-elderly-safety "npm.cmd --prefix firebase test"
firebase.cmd emulators:exec --only firestore --project demo-elderly-safety "tools\python\python.exe firebase\tests\publisher_smoke.py"
firebase.cmd deploy --only firestore:rules --project elderly-safety-ai
```

Rules đã deploy sau khi 17 kiểm thử emulator đạt. Không cần composite index cho các query theo từng hồ sơ rồi orderBy(createdAt). Không deploy file indexes rỗng lên project khác khi chưa kiểm tra index hiện có.

## FCM

Flutter xin quyền thông báo Android, tạo channel `safety_alerts`, đăng ký token từng thiết bị, xử lý refresh, foreground notification, notification tap ở background/cold start. Payload chỉ có ID hồ sơ/cảnh báo và loại sự kiện; không đưa tên người hoặc thông tin nhạy cảm lên màn hình khóa. Logout xóa đăng ký token trước khi kết thúc phiên; khi không có mạng có thể cần kết nối lại để hoàn tất.

Python ghi alert SUSPECTED_FALL trước rồi đọc caregiver được cấp quyền để gửi. Xác minh thành công cập nhật cùng alert thành POSSIBLE_FALL, giữ nguyên seenAt/safeAt; recovery/chưa đủ bằng chứng cập nhật trường verification. Token không hợp lệ bị xóa. Mỗi alert/device có delivery claim chống gửi lại, nên nâng cấp cùng alert không bắn thêm push trùng. Nếu lỗi mạng không biết FCM đã nhận chưa, ghi delivery_unknown và không tự gửi lặp. Đây là at-most-once, có thể mất push; Firestore vẫn giữ alert. accepted_by_fcm chỉ là API chấp nhận, không phải điện thoại đã nhận.

Thử đường truyền riêng sau khi đã provision hồ sơ kiểm thử:

```powershell
.\tools\python\python.exe scripts/firebase_smoke.py --profile ho-so-test --confirm ho-so-test --notify
```

Sự kiện mang `SIMULATED_TRANSPORT_TEST`, origin=simulation. Không dùng nó làm bằng chứng nhận diện ngã.

## Quota và vận hành

Heartbeat 30 giây ≈2880 lần ghi/ngày/engine; thay đổi trạng thái được gộp tối thiểu 15 giây và kèm history, tối đa khoảng11520 ghi/ngày trước sự kiện/alert/FCM bookkeeping. Lượng đọc tăng theo số điện thoại/listener. Đây là ước lượng, không bảo đảm quota khi nhiều engine hoặc sự kiện dày. Theo dõi Usage trong Console, giới hạn số hồ sơ hoạt động và thời gian chạy thử. Không dùng TTL trả phí hoặc tự bật dịch vụ trả phí. Lịch sử lưu lâu cần quản trị viên lên lịch dọn có kiểm soát; chưa có job retention tự động.

Tham chiếu chính thức: [Flutter setup](https://firebase.google.com/docs/flutter/setup), [FCM Flutter nhận thông báo](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages), [FCM Admin gửi thông báo](https://firebase.google.com/docs/cloud-messaging/send/admin-sdk), [Rules field restrictions](https://firebase.google.com/docs/firestore/security/rules-fields), [quota Firestore](https://firebase.google.com/docs/firestore/quotas).
