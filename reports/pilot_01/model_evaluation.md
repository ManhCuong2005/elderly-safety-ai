# Đánh giá pilot theo sự kiện

Model đã chốt: **Logistic Regression** · ngưỡng 1.01 · `pilot-6baa77e3c24d`.
Train thực tế: 16 clip, 8 người, 2 ca Fall.
Cửa sổ train: 6 Fall, 988 No_Fall.

| Validation | Ngưỡng | Bắt được | Recall | Báo giả | Phút ADL | Báo giả/giờ |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 1.01 | 0/1 | 0.0% | 0 | 1.22 | 0.00 |
| Random Forest | 0.65 | 0/1 | 0.0% | 0 | 1.22 | 0.00 |

Test độc lập: 5 clip từ 2 người.
- Bắt được 0/1 ca (0.0%), bỏ sót 1.
- 0 báo giả trong 1.87 phút ADL (0.00/giờ).
- Độ trễ từng ca (giây, cảnh báo trừ lúc chạm): [].
- Không nhìn rõ 4.50 giây, chưa thấy người 0.00 giây trên 161.58 giây test. Cảnh báo khác: 0.

Ghép cảnh báo đầu tiên từ 0,25 giây trước lúc mất thăng bằng đến 1,5 giây sau lúc chạm. Độ trễ âm nghĩa là báo trước khi chạm.
Thời lượng ADL pilot ngắn. Số báo giả/giờ là phép quy đổi từ số quan sát được.
Xem `test_mistakes.csv` để mở lại clip và timestamp sai.
