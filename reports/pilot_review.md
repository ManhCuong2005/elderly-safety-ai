# Rà nhãn trước khi huấn luyện pilot

Đợt đầu tải 18 clip của 6 mã người từ cả 9 nhóm để rà độ phân giải, FPS, chiều xoay và độ phủ vai/hông. Sau đó chọn thêm clip ở các đợt thu khác để tìm ca có mốc chạm quan sát được và lấy clip sinh hoạt tương ứng với các mã người.

Đã xem các khung trải dọc clip và rà dày đến 8–12 khung/giây quanh các mốc cần ghi cho pilot. Không có timestamp ngã chính thức trong tài liệu RGB đã tải. Các mốc do rà hình, xấp xỉ theo PTS và liên kết với đúng phiên bản video bằng SHA-256. Việc chấm điểm dùng các mốc trong [confirmed.json](../data/annotations/confirmed.json), độc lập với đầu ra MoveNet và classifier.

| Ca mô phỏng đã xác nhận vòng đầu | Mất thăng bằng (giây) | Chạm (giây) |
|---|---:|---:|
| Trip_n_Fall/Person33 | 6,27 | 7,01 |
| Trip_n_Fall/Person35 | 4,77 | 6,51 |
| Trip_n_Fall/Person41 | 10,40 | 10,76 |
| Walk_n_Fall/Person20 | 24,33 | 24,77 |

`Trip_n_Fall/Person05` là âm tính khó trong khoảng 2,50–9,65 giây theo khung hình. Clip cho thấy cúi và bước điều chỉnh rồi đứng thẳng lại. Manifest giữ nguyên nhãn gốc và lưu cả quyết định No_Fall.

Hai clip ghi mã người có dấu hiệu mâu thuẫn là `Sitting/Person04` và `Stair_Climbing/Person02`. Cả hai nằm ngoài split. Hai clip xoay sai do thiếu metadata được chỉnh khi đọc theo [overrides.json](../data/review/overrides.json). Clip `Sit_n_Fall/Person20` giữ trạng thái review vì động tác gần giống ca Walk cùng người và mốc chạm khó xác định.

Mở web rồi rà 3 clip sau để xác nhận thêm các ca khó. Chọn **Không rõ** nếu khung hình còn thiếu bằng chứng về mất thăng bằng hoặc điểm chạm.

- `Sit_n_Fall/Person14`, xem khoảng 6–9 giây. [Mở trang rà nhãn](http://127.0.0.1:8765/?review=Sit_n_Fall%2FPerson14)
- `Trip_n_Fall/Person21`, xem khoảng 6–10 giây. [Mở trang rà nhãn](http://127.0.0.1:8765/?review=Trip_n_Fall%2FPerson21)
- `Sit_n_Fall/Person33`, xem khoảng 10–15 giây. [Mở trang rà nhãn](http://127.0.0.1:8765/?review=Sit_n_Fall%2FPerson33)

Để mở rộng tập test, chọn mã người ngoài các đợt pilot đã dùng rồi xác nhận clip của họ trước khi tạo tập mới.

## Vòng hai

Hai model ở vòng đầu cùng bỏ sót ca validation. Báo cáo, split và cấu hình vòng đầu được lưu riêng. Vòng hai xác nhận thêm 8 ca từ các mã người 22, 24, 27, 29, 30, 31, 32 và 36. Clip âm tính đi và ngồi được rà riêng. Test vòng hai chọn người chưa tham gia split trước. Những người của test vòng đầu ở ngoài tất cả các tập của vòng hai. [Báo cáo vòng đầu](pilot_01/model_evaluation.md) · [Quy tắc test mới](../data/manifests/split_policy.json)

Mốc đợt hai trong `confirmed.json` ghi `confirmed_by: codex-visual-pilot-02`. Ca chậm, xa máy hoặc bị che một phần được giữ khi vẫn xác định được diễn tiến và mốc tiếp xúc xấp xỉ. Clip nhiều lần diễn lại với mốc chưa tách rõ tiếp tục nằm ở `review`.

Kiểm kê đủ 450 video phát hiện ba file gắn tên Person51 trùng byte với file Person41 trong các nhóm `Sitting`, `Trip_n_Fall` và `Walking`. Quy tắc chia tập gộp các mã có quan hệ này. Các khung trải đều của 18 file tải bổ sung đã lưu trong `data/review/`. Ba clip gắn nhãn Fall của Person52 tiếp tục chờ rà mốc. Các khung hiện có cho thấy đi lại hoặc cúi trong phòng, với người khác xuất hiện ở một số đoạn.
