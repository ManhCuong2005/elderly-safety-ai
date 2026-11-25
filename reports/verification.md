# Kiểm tra pipeline và website

- Môi trường Windows x64 chạy Python 3.12.10 từ `.venv`. Kiểm tra dependency của pip đạt. MoveNet v4 đã mở bằng LiteRT và checksum khớp hồ sơ.
- `scripts/run.ps1 Check` đạt 13 bài kiểm tra sau khi tải đủ 450 video. Các bài thử bao gồm thoát thư mục, chặn truy cập clip từ mạng LAN, xử lý tên file khác mã thư mục, tách người và bản trùng đã biết, giữ nhân quả và bỏ cửa sổ sau bước nhảy do mất dấu.
- Giải mã mới một clip test từ MP4 rồi đối chiếu với cache. Sai số tuyệt đối tối đa cho phép của đặc trưng là `1e-7`. Timestamp, trạng thái và cảnh báo của API replay khớp kết quả đọc mới. SHA-256 và kích thước MP4 giữ nguyên sau kiểm tra.
- Chrome mở tại `127.0.0.1:8765` bằng liên kết trực tiếp, phát `Trip_n_Fall/Person27` và hiển thị đúng một cảnh báo. Tua về đầu xóa cảnh báo tương lai khỏi danh sách. Liên kết trực tiếp tới trang rà nhãn hiển thị mốc chạm đã lưu. Đã kiểm tra bố cục 1320 × 900 và 390 × 844.
- Luồng camera trình duyệt được thử bằng video thật của dataset cấp cho thiết bị camera mô phỏng trong Chrome. Phiên kiểm tra cuối gửi 19 yêu cầu frame trước khi bấm **Dừng**. Máy xử lý xác nhận đóng phiên, trình duyệt giải phóng stream, và không ghi nhận yêu cầu frame mới sau khi dừng.

Webcam vật lý, điện thoại và chứng chỉ HTTPS trong mạng chấm chưa được xác minh trên thiết bị thật.

## Thử video và nhãn tư thế

- `Check` đạt 15 bài kiểm tra sau khi thêm chức năng. Đối chiếu API replay trên cả 11 clip test với báo cáo đã chốt cho kết quả trùng tất cả mốc cảnh báo. Checksum của model té ngã, cấu hình, split và kết quả test khớp bản trước khi thay đổi.
- Chrome tải MP4 của `Trip_n_Fall/Person27` qua bộ chọn file và hiện một cảnh báo ở 6,52 giây. Bấm thời điểm đưa video tới đúng cảnh báo. Chrome cũng tải được WebM tạo từ clip `Standing/Person32`, hiện **Đứng** và không có cảnh báo. Clip `Sitting/Person31` hiện **Ngồi** trong chế độ phát lại. Camera mô phỏng cũng hiện nhãn tư thế trong lúc theo dõi và ẩn nhãn khi bấm dừng.
- Model tư thế huấn luyện trên 18 clip, với 766 khung hình sử dụng được. Trên 8 clip của 4 người khác, model hiện nhãn ở 220/384 khung lấy mẫu và đúng ở 216 trong số 220 khung có nhãn. Các khung trong một clip có tương quan thời gian. [Số liệu theo clip](posture.json)
