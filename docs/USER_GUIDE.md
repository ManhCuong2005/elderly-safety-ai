# Hướng dẫn sử dụng

## Laptop

Mở project ở `D:\DANC2\Project\elderly-safety-ai`. Thử video trước bằng lệnh trong README. Webcam index0 đã được probe kỹ thuật đọc15 frame và nhả/mở lại, không lưu hình/không gửi cloud. Chưa có pose toàn thân đủ tin cậy trong probe này. Nếu cần cấp quyền: Windows Settings → Privacy & security → Camera → cho phép desktop apps.

Đặt laptop cố định, nhìn thấy toàn thân từ đầu đến chân, ánh sáng đủ, không có người khác đi vào cảnh. Khung hình một người là điều kiện của V1; ghế, giường và vật che chân có thể làm mất landmarks. Không dùng camera nhìn thẳng từ trên xuống để kỳ vọng các quy tắc phối cảnh hiện tại hoạt động như camera ngang.

Chạy `scripts\run-local.cmd --source 0`. Đổi `--source 1` nếu webcam USB là thiết bị1. Start là khởi chạy lệnh; Space dừng phân tích tạm thời, Q kết thúc và nhả camera. R xác nhận lựa chọn lại người, xóa lịch sử chuyển động để không nối hai người/đoạn thiếu dấu thành một lần ngã.

Overlay có tư thế, person_status, FSM, vận tốc torso/s, FPS inference và trạng thái Firebase. UNKNOWN nghĩa là chưa đủ bằng chứng. PERSON_NOT_DETECTED là không thấy pose; IDENTITY_RESET_REQUIRED/MULTIPLE_PEOPLE_RESET_REQUIRED cần kiểm tra cảnh rồi nhấn R. Skeleton chỉ vẽ khớp đủ confidence. Đừng xem overlay “ALERT” từ dữ liệu tổng hợp là bằng chứng nhận diện thật.

Connected Mode chỉ cho webcam thật và profile đã provision; video và demo bị từ chối để không gửi thử nghiệm cho người thân. Cấu hình bình thường nằm lâu30 phút, bất động10 phút; `--demo` chỉ chạy local với15/20 giây. Chưa nghiệm thu thuật toán nên các thử nghiệm tiếp theo cần được giám sát.

## Điện thoại người thân

Cài APK debug, mở app An Tâm, đăng nhập tài khoản đã tạo trong Firebase Auth. Chưa có chức năng tự đăng ký/link tùy ý. Nếu hiện “Chưa có hồ sơ”, quản trị viên liên kết bằng script, không đổi Rules thành public.

Chọn mã hồ sơ ở đầu trang. Tổng quan hiển thị tên, tư thế mới nhất, camera/AI online/offline, thời gian cập nhật và5 cảnh báo gần nhất. Thống kê là trong5 cảnh báo này, không phải tổng toàn bộ lịch sử. Heartbeat quá90 giây hoặc dữ liệu chỉ có cache không được coi là đang theo dõi trực tiếp.

Hoạt động và Cảnh báo có nút tải thêm, tối đa300 mục mỗi lần truy cập. Chi tiết cảnh báo có thời gian, nguồn, mức độ và hai thao tác riêng: “Tôi đã xem” chỉ xác nhận đã đọc; “Đã kiểm tra • người thân an toàn” chỉ bấm khi đã kiểm tra thực tế. Viewer không có quyền xác nhận. Thao tác đang chờ máy chủ hiển thị riêng; dữ liệu cache không cho gửi xác nhận.

Cài đặt cho bật/tắt thông báo trên riêng thiết bị này và đăng xuất. Android13+ cần quyền thông báo. Nếu tắt quyền hệ thống, bật lại trong Android Settings. Thông báo không thay thế trang Cảnh báo: FCM có thể không giao push; hãy kiểm tra trạng thái thiết bị và kết nối.

Laptop và điện thoại có thể ở hai mạng khác nhau. Laptop phải chạy liên tục và có Internet; tắt máy/ngủ/ngắt camera làm mất quan sát. Khi dừng engine đúng cách, cloud ghi offline; nếu bị tắt đột ngột app chờ heartbeat hết hạn.
