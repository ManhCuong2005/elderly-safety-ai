# Dataset và provenance

**Hiệu chỉnh đầu vào:**54 MP4 đã được xác minh là khung ghép grayscale depth trái/RGB phải, không phải toàn khungRGB. Metadata input_layouts.json và manifest đã cập nhật; Source chỉ tự tách với file dataset đã xác minh, browser có switch nguồn. Các benchmark lịch sử trước sửa không dùng làm độ chính xác RGB; xem INPUT_LAYOUT_CORRECTION.md.

Nguồn đã kiểm tra ngày 09/11/2026: [UR Fall](https://fenix.ur.edu.pl/~mkepski/ds/uf.html), [UP-Fall](https://sites.google.com/up.edu.mx/har-up). UR cung cấp RGB PNG theo chuỗi, MP4, CSV đồng bộ và nhãn Fall/ADL; dùng CC BY-NC-SA 4.0 cho học thuật phi thương mại, cần trích dẫn Kwolek & Kepski, 2014, *Human fall detection on embedded platform using depth maps and wireless accelerometer*. UP-Fall có cấu trúc theo subject/activity/trial và RGB camera ZIP; phiên này chọn UR do link tải trực tiếp nhỏ, không tải UP-Fall và chưa xác minh giấy phép/dung lượng từng archive UP-Fall.

## Dữ liệu thực tế trong project

60 chuỗi: fall-01…fall-30, adl-01…adl-30;30 Fall,30 Non-Fall. Sáu chuỗi01–03 là RGB PNG gốc kèm timestamp CSV;54 chuỗi04–30 là MP4 nguồn, kèm CSV để lưu provenance. Đã giải mã9180 frame nguồn, số đếm khớp metadata của tất cả60 chuỗi. Không nhân ảnh tĩnh giả chuyển động. Mốc MP4 dùng presentation time do OpenCV đọc; CSV UR chỉ dùng làm timestamp cho chuỗi PNG, không áp dụng nhầm vào MP4 khi chưa kiểm tra ánh xạ frame.

Tải trực tiếp ZIP đầu: fall-01 57.727.213 byte, adl-01 69.079.050 byte theo HTTP Content-Length đã kiểm tra. Các file thực tế được ghi SHA-256 sau tải; ZIP kiểm tra CRC trước khi giải nén. Archive đã xác minh được xóa, chỉ giữ PNG và marker để không chiếm hai lần dung lượng. SHA kiểm chứng thay đổi file tải, không phải chữ ký xác thực do tác giả công bố. Downloader không có checksum độc lập từ nhà cung cấp.

Đường dẫn:

- `ai_engine/datasets/raw`: PNG sequences và MP4.
- `ai_engine/datasets/metadata/manifest.json`: ID, nhãn nguồn, URL, hash, số byte tải, split, camera, license.
- `ai_engine/datasets/metadata/*-data.csv`: timestamp nguồn.
- `ai_engine/datasets/processed/*.landmarks.jsonl`: landmark được MediaPipe trích xuất hoặc null kèm lý do.
- `ai_engine/datasets/processed/*.features.csv`: geometry, motion và tư thế từng frame.
- `ai_engine/datasets/processed/*.performance.json`: số frame và throughput đo thật.
- `docs/evaluation-*.json`: kết quả theo video, danh sách frame thiếu pose, sự kiện và confusion matrix.

Ban đầu 6 RGB chiếm417.561.808 byte; sau thêm MP4 và một phần cache là438.479.793 byte. Số đo cuối có trong `docs/verification-summary.json`. Giới hạn downloader 1.000.000.000 byte tính cả file tạm/archive/giải nén, kiểm tra trước tải và từng block. Không chạy nhiều downloader đồng thời. Pipeline trích xuất hiện không có hard cap bộ nhớ đĩa độc lập; với tập đã chọn đã đo dưới800 MB, cần kiểm tra dung lượng trước khi mở rộng dataset.

## Split và giới hạn đánh giá

| Split | IDs mỗi lớp | Mục đích |
|---|---|---|
| calibration | 01, 09, 10 | chỉ chọn ngưỡng tại đây |
| test | 02, 03 | đánh giá ban đầu, báo cáo giữ riêng |
| test_final | 04–08 | kiểm thử cuối với config đã đóng băng |
| test_v1_1 | 11–15 | đánh giá sửa continuity/occlusion ban đầu |
| test_v1_2 | 16–20 | test cuối mới cho cảnh báo sớm/core evidence |
| test_v1_3 | 21–25 | test mới sau bổ sung bằng chứng co hình chiếu |
| test_v1_4 | 26–30 | test mới sau sửa bằng chứng trước debounce và tư thế phối cảnh |

Chưa biết subject ID của từng clip, nên không khẳng định tách theo người. Các clip có thể cùng phòng, người và camera. Không đồng nhất clip ngã của người trẻ với ngã tự nhiên ở người cao tuổi. Tập nhỏ và có diễn xuất; không đại diện tất cả camera/ánh sáng.

Nhãn FALL/NON_FALL lấy từ phân nhóm trên trang nguồn. Chưa có nhãn STANDING/SITTING/LYING/WALKING theo frame hoặc nhãn riêng cúi người, đứng dậy, nằm chủ động được xác minh. Những tình huống này còn PENDING_COVERAGE; không suy ra ground truth bằng kết quả của engine. Không có fall_onset_s được ánh xạ RGB đáng tin cậy trong manifest; detection_latency_s=null. Hệ thống không tự bịa latency từ thời điểm ứng viên của chính nó.

Kết quả1.2 theo video: dương khi có ít nhất một cảnh báo SUSPECTED_FALL/POSSIBLE_FALL; verified_metrics chỉ tính POSSIBLE_FALL. Báo cáo trước1.2 chỉ tính POSSIBLE_FALL, được giữ nguyên thay vì viết đè. Cả hai cách đều không tính POSTURE_CHANGE. FP rate=FP/(FP+TN) theo video. Không có nhãn nhiều sự kiện trong cùng clip nên chưa đánh giá event matching chi tiết. Clip thiếu pose vẫn giữ trong mẫu, không loại ra để tăng Recall. Test1.2 TP=0,FP=1,FN=5,TN=4; chưa đạt nghiệm thu.

Bản1.3 giữ nguyên định nghĩa cảnh báo sớm, bổ sung co chiều cao hình chiếu nhanh khi toàn thân còn thấy rõ. Test21–25:TP=0,FP=0,FN=5,TN=5; vẫn không đạt. Không tiếp tục hiệu chỉnh trên các clip này rồi gọi chúng là test độc lập.

Bản cuối1.4 giữ cùng định nghĩa cảnh báo sớm, test mới26–30 cóTP=1,FP=0,FN=4,TN=5; cảnh báo đúng ở fall-28. Precision=1,Recall=0,2,F1≈0,333. Verified metrics vẫn0 TP/5 FN. Các tập test khác nhau nên không dùng bảng giữa phiên bản để kết luận cải thiện có kiểm soát. Đây là kết quả thử nghiệm nhỏ, độ nhạy chưa chấp nhận được.

Không commit PNG, MP4, landmarks hoặc cache lớn. Chỉ chia sẻ metadata nhỏ được phép, script và báo cáo không có thông tin cá nhân. Khi sử dụng ngoài đồ án phi thương mại cần xem lại điều khoản nguồn và xin phép phù hợp.
