# Chuẩn bị V2

V1 đã chia module pose, geometry, posture, motion, FSM, dataset và Firebase. V2 có thể thay `classify()`/candidate bằng classifier mới nhưng phải giữ confidence, continuity, provenance và kiểm thử rò rỉ dữ liệu.

Ưu tiên trước khi huấn luyện: bổ sung video full-body nhiều góc, người tham gia khác nhau, nhãn hoạt động/onset bằng con người, đánh giá đủ ngồi nhanh/nằm chủ động/cúi người và kiểm thử camera thật. Khắc phục các false negative và detector duplicate, đo chất lượng landmarks thay vì chỉ thêm classifier trên dữ liệu lỗi.

Nếu phát triển Random Forest ở V2: xuất feature CSV theo window với subject ID, chia train/validation/test theo người, chọn ngưỡng trên validation và đóng băng trước test; không dùng frame lân cận của cùng video nằm ở cả train và test. Báo cáo recall, precision, F1, FP/giờ quan sát, latency theo onset được chú giải và khoảng bất định.

Không có code huấn luyện mô hình trong V1. Không tự thêm iOS, camera IP, IoT, livestream, Cloud Functions hoặc tài nguyên trả phí. V2 cần review lại quyền credential, retention event, quota và độ bền queue trước khi vận hành lâu dài.
