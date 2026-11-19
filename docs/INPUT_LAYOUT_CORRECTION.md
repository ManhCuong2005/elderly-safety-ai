# Hiệu chỉnh đầu vào UR Fall

Khi kiểm tra thực tế giao diện web ngày10/11/2026, MP4 trực tiếp từ trang UR được xác nhận ghép depth bên trái và RGB bên phải. Kiểm tra cả54 MP4 đã tải: kích thước khung ghép và3 frame thực mỗi clip xác nhận nửa trái gần grayscale, nửa phải là RGB. Sáu chuỗi PNG RGB gốc không cần tách. Bằng chứng tại ai_engine/datasets/metadata/input_layouts.json.

Các pipeline trước đây đã đưa toàn bộ khung ghép vào MediaPipe. Vì thế các chỉ số trong evaluation-test*,calibration-report* cũ không đại diện đúng độ chính xác trên RGB; số Recall20% từng báo cần hiểu là lịch sử chạy với đầu vào sai, không tiếp tục dùng làm đánh giá năng lực hệ thống.

Sửa ở bước tiền xử lý, không đổi model/ngưỡng/quy tắc1.4:

- Browser: nhận diện tên UR chuẩn + tỷ lệ khung ghép, hiển thị switch RGB phải; canvas gửi RGB và overlay vẽ cùng vùng.
- Source Python: auto chỉ với các file dataset đã có metadata xác minh trong raw; video RGB bên ngoài và webcam không bị tự cắt. Có thể chỉ định --input-layout rgb/ur-rgbd.
- Dataset extractor: đọc input_layout từ manifest; cache cũ có khung ghép bị từ chối khi yêu cầu đánh giá RGB, không xóa/ghi đè cache cũ.

Đã trích lại10 clip26–30 bằng RGB đúng, lưu cache rgb_input_fixed và báo cáo evaluation-test_v1_4-rgb_input_fixed.json. Đây là kiểm tra chẩn đoán sau sửa lỗi đầu vào, không phải một tập test độc lập mới và không hiệu chỉnh lại ngưỡng trên các clip này. Kết quả cảnh báo nghi ngờ:TP0,FP1,FN5,TN4; độ nhạy vẫn không đạt. Các báo cáo cũ được giữ để kiểm toán, không dùng chúng để kết luận độ chính xác hoặc cải thiện.

Tái lập kiểm tra chẩn đoán:

```powershell
.\tools\python\python.exe scripts/verify_dataset_layout.py
.\tools\python\python.exe ai_engine/scripts/evaluate.py --extract --extract-split test_v1_4 --split test_v1_4 --config ai_engine/configs/calibrated-v1_4.json --cache-tag rgb_input_fixed --report-tag=-rgb_input_fixed --model ai_engine/models/pose_landmarker_full.task
```

Để đánh giá khách quan tiếp theo cần chú giải và tập video mới chưa dùng trong phát triển, đúng đầu vào RGB, đủ toàn thân và đủ thời gian trước/sau sự kiện. Không tuyên bố ngã được xác minh chỉ từ việc pose nhận dạng được trên web.
