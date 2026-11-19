# Thuật toán và giới hạn

Các công thức chỉ dùng hình chiếu 2D. Không tính độ cao thực so với sàn hoặc vận tốc m/s. Chuẩn hóa `x' = x * width/height`, `y'=y`, để hai trục cùng đơn vị chiều cao ảnh. `z` từ MediaPipe chưa dùng để suy ra độ cao vật lý.

Góc ABC = `acos(clip(dot(A-B,C-B)/(norm(A-B)*norm(C-B)),-1,1))`. Vector rỗng hoặc không hữu hạn trả về không hợp lệ. Trung điểm vai và hông xác định độ dài thân chuẩn hóa. Góc nghiêng thân = `atan2(abs(dx),abs(dy))` trong khoảng 0–90°. Góc hông và gối lấy trung bình hai bên. Tỷ lệ thân = chiều cao/chều rộng bounding box tám khớp vai/hông/gối/cổ chân. Khoảng cách theo phương dọc hông–cổ chân chia độ dài thân.

Gate cơ sở: cả bốn khớp vai/hông và ít nhất một chuỗi hông–gối–cổ chân có visibility/presence tối thiểu0,6; thân dài ít nhất0,04 đơn vị ảnh. Các điểm sử dụng phải trong vùng ảnh có margin nhỏ. Có hai chân thì lấy trung bình, một chân rõ thì chỉ dùng chân đó; không điền tọa độ giả cho chân bị che. WALKING đòi hỏi cả hai chân rõ. Dữ liệu thiếu hoặc NaN/Inf không được phân tích.

Nếu không có chân rõ nhưng cả bốn khớp thân có confidence≥0,85 và nằm thật bên trong ảnh, `extract_core` trả CORE_ONLY. Tư thế công khai vẫn UNKNOWN; không gán LYING hoặc tính nằm lâu/bất động từ thân đơn lẻ. Đường cảnh báo chỉ chấp nhận thân nghiêng≥65° và bbox thân cao/rộng≤1,0, kết hợp toàn bộ điều kiện chuyển động và tư thế trước đó. Gọi bằng chứng này COLLAPSED_TORSO, không coi nó là quan sát đủ toàn thân. Mất pose hoàn toàn không đi vào đường này.

Quy tắc mặc định:

| Nhãn | Điều kiện đồng thời |
|---|---|
| STANDING | nghiêng ≤32°, gối ≥150°, hông ≥150° |
| SITTING | nghiêng ≤47°, gối ≤135°, hông ≤140° |
| LYING | nghiêng ≥62°, tỷ lệ cao/rộng ≤1,35, độ dọc chân ≤0,55 thân |
| UNKNOWN | không đủ các bằng chứng trên |

Ngưỡng nằm cần nhiều tín hiệu nhưng vẫn không giải quyết mọi góc camera. Camera từ trên xuống hoặc người ngã hướng thẳng vào camera có thể không tạo hình chiếu thân ngang. Không ép thành LYING. Nhãn cần ổn định 0,25 giây; UNKNOWN có hiệu lực ngay để không giữ nhãn tin cậy giả. EMA góc thân có hằng số thời gian 0,12 giây, chỉ dùng telemetry, không làm mất xung ngã.

Window mặc định2,5 giây, giới hạn1000 mẫu, dùng timestamp nguồn. Gap>0,5 giây xóa lịch sử chuyển động, nhãn debounce và đồng hồ nằm/bất động, đồng thời ngắt xác minh liên tục. Timestamp âm, trùng, lùi hoặc không hữu hạn gây lỗi rõ. Vận tốc chuyển động = khoảng cách trung bình bốn điểm vai/hông so với mẫu khoảng0,3 giây trước / độ dài thân tham chiếu / Δt. Đây là torso/s; khoảng ngắn giúp giảm jitter. Tín hiệu ngã nhanh vẫn dùng mẫu thô riêng.

WALKING cần nhãn đứng, ít nhất 8 mẫu trong khoảng ≥1,2 giây, biên độ chênh lệch chân ≥0,25 thân, ít nhất hai lần đảo chiều quanh median và vận tốc cơ thể ≥0,15 thân/s. Một frame hoặc lắc nhẹ không đủ. Chưa có nhãn walking theo frame để xác nhận độ chính xác thực tế.

Ứng viên ngã cần LYING hoặc COLLAPSED_TORSO hiện tại, từng đứng/ngồi trong1,2 giây trước, đồng thời đổi góc≥38°, tốc độ góc≥45°/s, hông đi xuống≥0,5 thân, tốc độ hông≥0,65 thân/s. Các độ dịch chuyển và tốc độ cùng một mẫu tham chiếu. Không đủ các yếu tố thì không tạo cảnh báo chỉ vì ngồi nhanh, nằm sẵn hoặc biến mất.

FSM: `NORMAL → SUSPECTED_FALL → VERIFYING → ALERT`. Khi đạt ứng viên, phát cảnh báo sớm SUSPECTED_FALL ở mức warning và bắt đầu xác minh. Nếu vẫn có LYING/COLLAPSED_TORSO tin cậy, vận tốc<0,3 thân/s liên tục1 giây thì cập nhật cùng ID thành POSSIBLE_FALL, mức high. Đứng/ngồi trở lại→RECOVERED. Quá5 giây không đủ bằng chứng→UNVERIFIED_CANDIDATE; thiếu pose không tự nâng cấp thành ngã. Cảnh báo sớm vẫn lưu, không bị xóa hoặc tự đánh dấu an toàn. Recovery quan sát được hoặc caregiver xác nhận an toàn đưa FSM về RECOVERED rồi NORMAL với cooldown30 giây. “Đã xem” không gọi xác nhận an toàn. Xác nhận an toàn hợp lệ cũng có thể kết thúc giai đoạn đang VERIFYING.

Nằm liên tục 1800 giây → LYING_TOO_LONG. Bất động khi vẫn có pose tin cậy 600 giây → ABNORMAL_INACTIVITY. Mỗi đợt chỉ phát một lần, hoạt động trở lại/mất dấu sẽ reset. Demo cục bộ rút còn 15/20 giây, cấm trong Connected Mode.

Toàn bộ ngưỡng có tên trong `src/config.py`; CLI mặc định dùng `configs/calibrated-v1_2.json`, model Full. Grid chỉ thử visibility0,5/0,6 và góc nằm55°/62° trên calibration. Báo cáo1.2 định nghĩa dương tính là cảnh báo SUSPECTED_FALL hoặc POSSIBLE_FALL; `verified_metrics` chỉ tính POSSIBLE_FALL. Các báo cáo cũ chỉ tính POSSIBLE_FALL, không so trực tiếp hai định nghĩa để tuyên bố cải thiện. Test mới16–20 được giữ riêng trước thay đổi này; kết quả0 TP/1 FP/5 FN/4 TN cho thấy chưa tổng quát tốt. Unit tests đạt không thay đổi kết luận đó.

Ở bản1.3, cấu hình là `configs/calibrated-v1_3.json`. Bản này bổ sung COLLAPSED_BODY khi toàn bộ hai chân tin cậy, posture UNKNOWN, bbox cao/rộng≤1,35 và chiều dọc chân≤0,9 thân. Trong window cần chiều cao bbox còn≤60% so với cùng coverage trước, đổi góc≥15° cùng hip drop/tốc độ trước đó. Không so chiều cao FULL với CORE_ONLY để tránh chuyển động giả do mất landmarks. Đây là hình chiếu, không suy độ cao vật lý. Test21–25 vẫn0 TP/5 FN; chưa đủ để chấp nhận thuật toán.

**Cấu hình CLI hiện tại là calibrated-v1_4.json.** Nhãn STANDING có thêm nhánh phối cảnh: thân vẫn gần dọc, chân theo chiều dọc≥1,4 thân, đùi theo chiều dọc≥0,5 thân và góc hông≥145°; không phụ thuộc duy nhất góc gối2D. Window dùng nhãn thô tin cậy để giữ tiền sự kiện ngắn; nhãn hiển thị vẫn debounce. Bằng chứng đứng/ngồi trước ngã cần ít nhất2 frame kéo dài≥0,08 giây, không lấy một frame lẻ. Tập mới26–30:1 TP/0 FP/4 FN/5 TN ở mức nghi ngờ; xác minh sau sự kiện chưa đạt. Không hiệu chỉnh tiếp trên tập này rồi gọi là đánh giá độc lập.

Tham chiếu API pose: [MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker?tab=Python).
