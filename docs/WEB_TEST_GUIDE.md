# Chạy nhận diện trên web và vẫn build APK

Cùng một project Flutter/Dart. Khi chạy web, app mở phòng thử nhận diện dùng Python local, không khởi tạo Firebase/FCM. Khi build Android, app giữ giao diện người chăm sóc và luồng Firebase hiện có. Python vẫn thực hiện MediaPipe, geometry và FSM; không chuyển hoặc huấn luyện lại model nhận dạng hành động.

## Chạy bằng hai terminal VS Code

Terminal1 — giữ Python AI đang chạy:

```powershell
cd D:\DANC2\Project\elderly-safety-ai
.\scripts\run-web-ai.cmd
```

Mong đợi: `Local pose API: http://127.0.0.1:8765 | Firebase/FCM disabled`.

Terminal2 — mở giao diện Flutter trên Chrome:

```powershell
cd D:\DANC2\Project\elderly-safety-ai\flutter_app
flutter run -d chrome --web-port 7357
```

Giữ cả hai terminal. Cổng7357 được cấu hình CORS cho bản test này; dùng localhost/127.0.0.1 trên chính laptop chạy Python. Không mở index.html bằng double-click và không dùng bản local này như site public từ máy khác.

## Thử nhận diện

1. Bấm Bật webcam, cấp quyền camera Chrome. Đặt camera thấy toàn thân, chỉ một người trong khung hình.
2. Hoặc Chọn video, dùng MP4 mà Chrome đọc được. Có thể chọn `ai_engine/datasets/raw/adl-04-cam0.mp4` để kiểm tra standing/skeleton.
3. Các MP4 UR Fall được cung cấp dưới dạng depth trái/RGB phải. Với tên UR chuẩn và khung ghép rộng, UI tự bật lựa chọn chỉ dùng RGB bên phải, có switch hiển thị để kiểm tra/tắt. Video RGB thông thường và webcam dùng toàn khung.
4. Xem skeleton, tư thế/hành động, FSM, chất lượng pose và sự kiện. Phần trăm pose là độ tin cậy khớp, không phải xác suất ngã.
5. Dừng sẽ dừng camera và đóng phiên Python. Chọn lại người/reset xóa bằng chứng chuyển động trước. Tua ngược hoặc tua xa video tạo lại phiên để không nối các thời điểm khác nhau thành chuyển động giả.

Màn hình hỗ trợ STANDING/SITTING/LYING/WALKING/UNKNOWN và cảnh báo nghi ngờ của engine V1; không nhận dạng mọi loại hành động hoặc dự đoán chắc chắn sẽ ngã. Web này chưa có đăng nhập/dashboard Firebase hay thông báo theo phạm vi thử nghiệm đã chọn.

## Build cả hai nền tảng

Trong thư mục flutter_app:

```powershell
flutter build web --release --no-web-resources-cdn
flutter build apk --release
```

Web output tại build/web; APK tại build/app/outputs/flutter-apk/app-release.apk. Release APK vẫn ký bằng Android Debug để cài thử, chưa có keystore phát hành riêng. Thêm web không thay ngôn ngữ frontend hoặc phá luồng Android.

## Lỗi thường gặp

- Chưa kết nối Python AI: kiểm tra Terminal1, rồi bấm kiểm tra kết nối. API chỉ bind127.0.0.1:8765.
- Camera bị chặn: cấp quyền camera trong Chrome và dùng localhost/127.0.0.1. App khác đang giữ thiết bị có thể cần đóng.
- Video không đọc được: dùng MP4 có codec Chrome hỗ trợ.
- Không thấy người/UNKNOWN: kiểm tra toàn thân, ánh sáng, nguồn RGB và camera angle. Không ép phân loại khi thiếu landmarks.
- Phiên bị thay thế: chỉ để một tab đang phân tích, bấm bắt đầu/reset. Server chỉ có một phiên active để không lẫn hai người.
- Tắt web bằng Ctrl+C ở Terminal2; Ctrl+C ở Terminal1 để dừng API. Đóng tab cũng dừng media stream phía trình duyệt, nhưng nên bấm Dừng trước khi thoát.

## Bằng chứng kiểm thử

OpenAPI tại api/local_pose.openapi.json. Pytest kiểm tra Origin/Host, phiên mới/hết hạn, timestamp, body lỗi và inputRGB; browser tests kiểm tra video thật, skeleton/nhãn đứng, reset/tua, mở-dừng camera giả lập, viewport1440/390 và backend offline. Camera giả lập chỉ kiểm tra luồng kỹ thuật, không dùng làm ground truth ngã. Chi tiết tại web-browser-test.json; ảnh QA trong tools/browser-qa (không commit).

Đã phát hiện lỗi đầu vào ghép RGB/depth trong benchmark cũ; xem INPUT_LAYOUT_CORRECTION.md. Nhận diện tư thế chạy được không đồng nghĩa thuật toán ngã đạt yêu cầu an toàn.
