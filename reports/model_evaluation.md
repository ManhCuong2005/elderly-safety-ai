# Đánh giá pilot theo sự kiện

Model đã chốt: **Logistic Regression** · ngưỡng 0.98 · `pilot-93aa2711b8e0`.
Train thực tế: 23 clip, 10 người, 2 ca Fall.
Cửa sổ train: 8 Fall, 1331 No_Fall.

Validation có 4 người. Ngân sách so sánh là 0 lần báo giả trong thời lượng ADL đã xác nhận.

| Validation | Ngưỡng | Bắt được | Recall | Báo giả | Phút ADL | Báo giả/giờ |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 0.98 | 1/2 | 50.0% | 0 | 2.59 | 0.00 |
| Random Forest | 0.65 | 0/2 | 0.0% | 0 | 2.59 | 0.00 |

Test độc lập: 11 clip từ 4 người.
- Bắt được 4/4 ca (100.0%), bỏ sót 0.
- 0 báo giả trong 2.98 phút ADL (0.00/giờ).
- Độ trễ từng ca (giây, cảnh báo trừ lúc chạm): [-0.168, 0.829, -0.493, 0.137].
- Không nhìn rõ 11.70 giây, chưa thấy người 3.38 giây trên 255.22 giây test. Cảnh báo khác: 0.

Ghép cảnh báo đầu tiên từ 0,25 giây trước lúc mất thăng bằng đến 1,5 giây sau lúc chạm. Độ trễ âm nghĩa là báo trước khi chạm.
Thời lượng ADL pilot ngắn. Số báo giả/giờ là phép quy đổi từ số quan sát được.
Xem `test_mistakes.csv` để mở lại clip và timestamp sai.

## Clip mở khi chấm

| Tập | Nhãn xác nhận | Clip gốc | Mốc chạm (giây) |
|---|---|---|---:|
| train | Fall | [Trip_n_Fall/Person35](../data/raw/varishta/Trip_n_Fall/Person35/Person35_video.mp4) | 6.51 |
| train | No_Fall | [Walking/Person22](../data/raw/varishta/Walking/Person22/Person22_video.mp4) | — |
| test | Fall | [Trip_n_Fall/Person27](../data/raw/varishta/Trip_n_Fall/Person27/Person27_video.mp4) | 6.69 |
| test | No_Fall | [Sitting/Person30](../data/raw/varishta/Sitting/Person30/Person30_video.mp4) | — |

Các ca trong báo cáo là mô phỏng. Nhiều clip dùng cùng bối cảnh dù người được chia độc lập.
Pilot trước dùng tập test khác và được lưu tại [pilot_01](pilot_01/model_evaluation.md).
