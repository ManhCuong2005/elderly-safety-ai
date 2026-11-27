# Thiết kế giao diện

Skill evon:ui-ux đọc file này trước khi dựng. Sửa tay được; file trái với code thì code thắng.

## Sản phẩm
- Sản phẩm: CameraAI — web app giám sát té ngã người cao tuổi qua camera cục bộ (MoveNet) và cảnh báo ảnh Telegram
- Người dùng: người chăm sóc gia đình đặt thiết bị cố định ở phòng, kiểm tra lịch sử và cấu hình báo động
- Việc chính: bật camera theo dõi trực tiếp, phát hiện và mở khóa báo động té ngã, soát lịch sử sự cố kèm ảnh, thử video cục bộ, cài đặt cảnh báo vắng mặt và liên kết Telegram
- Nền tảng: máy tính (đặt giám sát) và điện thoại (kiểm tra nhanh, mở khóa, xem lịch sử)
- Điểm khác biệt: xử lý AI hoàn toàn trong RAM tại máy cục bộ, khóa báo động an toàn tới khi người chăm sóc xác nhận

## Giao diện
- Bộ mặt: Dark Sidebar (P13): sidebar tối khóa màu (`.force-dark`, 256px desktop, drawer trượt mobile `☰ Menu`), vùng chứa classic (`max-w-[1520px]`), header content dính (`64px`), bề mặt phẳng Flat (P6), font Inter tự lưu (`web/fonts/`)
- Sắc: Neutral (P17)
- Màu nhấn: Xanh ngọc brand `#17624c` (nền sáng) / `#34d399` (sidebar tối), token `--primary` ở `web/style.css`
- Phong cách: phẳng (P6), hai bậc viền `--border` (`#f7f7f8`) và `--border-strong` (`#eaeaea`), không glass, không gradient
- Nền tối: không bật dark mode cho vùng nội dung; chỉ khóa tối ở sidebar & drawer qua `.force-dark`

## Màn đã dựng
- `/` Đăng nhập / Đăng ký (`#account-screen`): Phương án A, card đơn không viền giữa trang (`M29`), nút hiện/ẩn mật khẩu (`I27`)
- `/#camera` Theo dõi camera: Phương án A, dải cảnh báo khóa ở đỉnh kèm nút `Xác nhận an toàn (Mở khóa)`, khung camera 16:10 cạnh cột `Trạng thái phiên` + `Sự kiện trong phiên`
- `/#thu-video` Thử video: Phương án A, khung xem trước + vùng kéo thả tệp video (`file-upload.md`) và danh sách mốc cảnh báo bấm để tua
- `/#lich-su` Lịch sử cảnh báo: Phương án A, bộ lọc ngày có popover lịch 6 hàng + lọc loại sự kiện, dòng thời gian nhóm theo ngày, modal xem ảnh lớn và thanh phân trang
- `/#cai-dat-camera` Cài đặt camera: Phương án A, form một cột chia đường kẻ (`settings.md`), công tắc 24×44 và nhóm nút đề xuất thời gian
- `/#tai-khoan` Tài khoản & Telegram: Phương án A, thẻ hồ sơ + thẻ kết nối Telegram kèm hướng dẫn 3 bước + thẻ phiên đăng nhập (`#toi` tự chuyển hướng về `#tai-khoan`)

## Luồng
Đường chính: Đăng nhập `/` → Theo dõi camera `/#camera` → (khi báo động khóa) `Xác nhận an toàn (Mở khóa)` / `Xem lịch sử` → Lịch sử cảnh báo `/#lich-su` → bấm ảnh thu nhỏ → Hộp xem ảnh lớn.

| # | Từ màn | Người dùng làm gì | Tới | Loại |
| --- | --- | --- | --- | --- |
| 1 | Đăng nhập `/` | Nhập email, mật khẩu → bấm `Đăng nhập` | Theo dõi camera `/#camera` | Chính |
| 2 | Đăng nhập `/` | Bấm `Tạo tài khoản` | Chuyển form Đăng ký tại `/` | Nhánh |
| 3 | Theo dõi camera `/#camera` | Bấm `Bắt đầu theo dõi` | Bật luồng camera trực tiếp + nút `Dừng` / `Đổi camera` | Chính |
| 4 | Theo dõi camera `/#camera` | Khi báo động khóa → bấm `Xác nhận an toàn (Mở khóa)` | Gọi `/api/session/<token>/confirm-safe`, gỡ khóa | Chính |
| 5 | Theo dõi camera `/#camera` | Bấm `Xem lịch sử` (header) hoặc `Lịch sử cảnh báo` (sidebar) | Lịch sử cảnh báo `/#lich-su` | Chính |
| 6 | Lịch sử cảnh báo `/#lich-su` | Chọn ngày ở lịch popover hoặc chọn nhóm ở `Tất cả loại` | Lọc danh sách sự kiện; hiện nút `Bỏ lọc` | Nhánh |
| 7 | Lịch sử cảnh báo `/#lich-su` | Bấm ảnh thu nhỏ sự kiện | Mở hộp xem ảnh lớn tại chỗ (kèm `Mở ảnh gốc`) | Chính |
| 8 | Mọi màn (sidebar) | Bấm `Thử video` (chỉ localhost) | Thử video `/#thu-video` | Nhánh |
| 9 | Thử video `/#thu-video` | Kéo thả/chọn MP4/WebM → bấm `Phân tích video` → bấm mốc | Tua video tới mốc cảnh báo tương ứng | Chính |
| 10 | Mọi màn (sidebar) | Bấm `Cài đặt camera` | Cài đặt camera `/#cai-dat-camera` | Nhánh |
| 11 | Mọi màn (sidebar / menu hồ sơ) | Bấm `Tài khoản & Telegram` (hoặc truy cập `/#toi`) | Tài khoản & Telegram `/#tai-khoan` | Nhánh |
| 12 | Tài khoản / menu hồ sơ | Bấm `Đăng xuất` | Dừng camera, gọi `/api/account/logout` → về `/` | Thoát |
