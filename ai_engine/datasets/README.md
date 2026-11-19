# Dữ liệu cục bộ

Xem [docs/DATASET.md](../../docs/DATASET.md) cho nguồn, giấy phép, split và giới hạn.

`raw/` giữ video/chuỗi ảnh thật; `processed/` giữ kết quả MediaPipe; `metadata/` giữ manifest và timestamp nguồn. Không commit dữ liệu lớn. Tái lập bằng `ai_engine/scripts/download_dataset.py`, tổng thư mục tối đa1 GB khi tải/giải nén. Chuỗi ảnh yêu cầu CSV thời gian nguồn. Nghiêm cấm dùng ảnh tĩnh lặp lại để đánh giá vận tốc thực tế.
