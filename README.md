# Phát hiện té ngã qua camera

Đồ án theo dõi một người bằng camera của thiết bị đang mở website. Laptop chạy MoveNet SinglePose Lightning v4 và bộ phân loại theo cửa sổ thời gian. Ảnh camera dùng trong RAM của phiên theo dõi. Đăng nhập và lưu lịch sử dùng Supabase, còn suy luận chạy trên máy.

## Mở demo trên laptop

Tại PowerShell trong thư mục project, chạy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Web
```

Mở [website tại 127.0.0.1](http://127.0.0.1:8765/) và đăng nhập. Chọn **Camera → Bắt đầu theo dõi** và cấp quyền camera. Đặt laptop cố định, đưa một người vào khung sao cho thấy vai, hông và chân. Hai giây đầu thấy rõ tư thế dùng để làm đầy cửa sổ. Nút **Dừng** giải phóng camera và đóng phiên. Khi rời trang hoặc máy xử lý mất kết nối, phiên kết thúc và buffer được giải phóng.

Hồ sơ từ model đến split, video gốc và mốc nằm trong [model_videos.csv](data/manifests/model_videos.csv). Xem số đo tại [Đánh giá model](reports/model_evaluation.md) và [Kiểm kê dữ liệu](reports/dataset_summary.md).

Clip demo của pilot hiện tại là **Test · Trip_n_Fall/Person27**. Khi phân tích trong **Thử video**, cảnh báo xuất hiện khoảng 6,52 giây, trước mốc chạm đã xác nhận 6,69 giây. Bảng cuối báo cáo đánh giá có thêm clip No_Fall của test và clip gốc đã dùng để train.

Để thử một video trên máy, mở **Thử video**, chọn MP4 hoặc WebM, rồi bấm **Phân tích video**. Giới hạn mỗi tệp là 64 MiB, 90 giây, 4K và khoảng 60 khung hình/giây. Kết quả cho biết model có cảnh báo hay thiếu dữ liệu tư thế và cho phép bấm mốc để tua. Tệp chỉ được gửi tới máy xử lý localhost. Ứng dụng không đưa tệp vào dữ liệu huấn luyện. Nếu tệp giống byte với một video train, giao diện sẽ báo. Bản cắt hoặc mã hóa lại có thể có checksum khác.

**Đứng** và **Ngồi** là nhãn phụ từ một Logistic Regression riêng, chạy từ cùng các điểm MoveNet. Dòng tư thế chỉ xuất hiện khi máy đang theo dõi và có đủ độ tin cậy. Khi có **Nghi té ngã**, giao diện ưu tiên cảnh báo. Mô hình tư thế hiện có hai lớp, vì dữ liệu đã rà cho bước này xác nhận Standing và Sitting. Khi cần huấn luyện lại riêng model tư thế, chạy `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Posture`. [Kết quả tư thế](reports/posture.json)

## Thiết lập tài khoản và cảnh báo

Trong Supabase, bật **Data API**, rồi chạy toàn bộ [schema.sql](supabase/schema.sql) trong **SQL Editor**. Trong **Authentication → URL Configuration**, đặt **Site URL** thành `http://127.0.0.1:8765` để liên kết xác nhận email quay về web local. Khi triển khai, thay bằng URL HTTPS của web.

Với project đã cấu hình, chạy lại [schema.sql](supabase/schema.sql) một lần để bổ sung nguồn và ảnh trong lịch sử. Các bản ghi có từ trước khi thêm nguồn được gắn nhãn **Camera**.

Lưu cấu hình phía máy chủ vào `.secrets/supabase.json`.

```json
{
  "project_url": "https://xxxxx.supabase.co",
  "publishable_key": "sb_publishable_...",
  "secret_key": "sb_secret_..."
}
```

Lưu `{"bot_token": "..."}` vào `.secrets/telegram.json` và khởi động lại web. Giữ `.secrets` ngoài Git. Khi triển khai có thể dùng `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `TELEGRAM_BOT_TOKEN` và một `CAMERAAI_SESSION_SECRET` ngẫu nhiên ở phía máy chủ. Với cấu hình local mặc định, khởi động lại web sẽ yêu cầu đăng nhập lại.

Đăng ký bằng email, xác nhận qua email nếu Supabase yêu cầu, rồi đăng nhập. Trong **Tôi → Tài khoản & Telegram**, tạo liên kết, mở bot và bấm **Start**. Quay lại CameraAI, bấm **Kiểm tra kết nối** rồi **Xác nhận liên kết** khi thấy đúng tài khoản. Một chat Telegram chỉ liên kết với một tài khoản CameraAI. Dùng một máy chủ CameraAI cho mỗi bot và tắt webhook Telegram nếu đã cấu hình webhook trước đó.

Nếu bật xác nhận email cho người dùng bên ngoài nhóm Supabase, cấu hình [SMTP riêng](https://supabase.com/docs/guides/auth/auth-smtp) để gửi email đăng ký.

Camera trực tiếp lưu một ảnh JPEG tại mỗi mốc **Nghi té ngã** vào lịch sử của tài khoản đã mở phiên. Bot gửi ảnh và giờ cảnh báo tới chat đã liên kết. Nếu không tạo được ảnh hoặc Telegram từ chối ảnh, bot gửi tin chữ thay thế. **Tôi → Lịch sử cảnh báo** nhóm sự kiện theo ngày, hiện giờ Việt Nam và cho phép chọn ngày hoặc chuyển trang. Khi **Thử video** phát hiện nghi té ngã, bot gửi một ảnh ở mốc cảnh báo đầu tiên với nhãn **[THỬ VIDEO]** và lưu một mục lịch sử có nguồn **Thử video**, kể cả khi Telegram chưa kết nối hoặc gửi lỗi. Web hiển thị kết quả phân tích và trạng thái gửi ảnh. [Telegram Bot API](https://core.telegram.org/bots/api#sendphoto)

Trong **Tôi → Cài đặt camera**, bạn có thể bật **Báo khi không thấy người** và chọn thời gian chờ từ 10 đến 3600 giây. Tính năng tắt sẵn. Mốc mặc định là 60 giây, với đề xuất 30 giây cho góc rộng và 180 giây cho góc hẹp. Sau khi camera đã thấy người, một lần vắng mặt liên tục đủ lâu sẽ chụp ảnh JPEG tại thời điểm cảnh báo, lưu ảnh trong mục **Không thấy người** của lịch sử và gửi ảnh kèm thông báo tới Telegram đã liên kết. Camera phải tiếp tục theo dõi và thấy người quay lại trước khi gửi cảnh báo cho lần rời khung hình tiếp theo. Với dự án Supabase đã tạo từ trước, chạy lại [schema.sql](supabase/schema.sql) trong **SQL Editor** để bổ sung phần cài đặt và loại cảnh báo mới.

Ảnh từ **Camera** và **Thử video** hiện trong lịch sử riêng của tài khoản. Bấm vào ảnh thu nhỏ để xem kích thước đầy đủ.

## Chuẩn bị lại từng bước

Video RGB được cung cấp theo nhóm hoạt động trong [GitHub Release VARISHTA-MM50 v5](https://github.com/ManhCuong2005/elderly-safety-ai/releases/tag/varishta-mm50-v5). Để phát lại trên máy khác, tải ZIP của nhóm cần dùng rồi giải nén vào thư mục gốc của project, giữ cấu trúc `data/raw/varishta/`. Clip demo Person27 nằm trong gói `Trip_n_Fall.zip`. Để lấy toàn bộ metadata gốc phục vụ kiểm kê và train lại, dùng `Download -All` như dưới đây.

Video RGB được cung cấp theo nhóm hoạt động trong [GitHub Release VARISHTA-MM50 v5](https://github.com/ManhCuong2005/elderly-safety-ai/releases/tag/varishta-mm50-v5). Để phát lại trên máy khác, tải ZIP của nhóm cần dùng rồi giải nén vào thư mục gốc của project, giữ cấu trúc `data/raw/varishta/`. Clip demo Person27 nằm trong gói `Trip_n_Fall.zip`. Để lấy toàn bộ metadata gốc phục vụ kiểm kê và train lại, dùng `Download -All` như dưới đây.

Chạy từng lệnh từ thư mục project. Cách gọi PowerShell bên dưới áp dụng execution policy cho tiến trình lệnh. Python 3.12.10 x64 portable nằm trong `.tools` và mọi package chạy trong `.venv`. Phiên bản đầy đủ nằm trong [requirements.lock.txt](requirements.lock.txt).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Model
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Catalog
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Download
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Inventory
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Sheets
```

`Download` mặc định lấy 18 clip đợt đầu của 6 người, đủ 9 nhóm nếu nguồn phục vụ. Thêm `-All` để lấy toàn bộ RGB và metadata theo từng file. Workspace hiện giữ đủ 450 video RGB của API v5. Dùng `-Video 'Trip_n_Fall/Person33'` để lấy một clip và metadata của nó. Với thư mục gốc `Person10` và `Person11`, tên file thực lần lượt là `Person51` và `Person52`. Manifest lưu cả mã thư mục và mã đối chiếu từ bảng nguồn. Tải lại sẽ so kích thước và checksum đã lưu, thử tiếp tục file dở nếu nguồn hỗ trợ. File tải dở ở `.cache/downloads`. Nguồn gốc, tên gốc, phiên bản và SHA-256 ở [download_manifest.csv](data/manifests/download_manifest.csv).

Kaggle cấp quyền công khai trong lần tải đã chạy. Nếu nhận HTTP 401/403, mở trang dataset bằng tài khoản của bạn, kiểm tra quyền hoặc điều khoản, và đặt credential vào `.secrets/kaggle.json` hoặc `.secrets/access_token`. Có thể dùng `KAGGLE_API_TOKEN` hoặc cặp `KAGGLE_USERNAME` và `KAGGLE_KEY` của phiên PowerShell. Giữ `.secrets` ngoài Git và ngoài gói bàn giao.

Các mốc đã rà lưu bằng giây trong [confirmed.json](data/annotations/confirmed.json) kèm checksum, mã người, nhãn nguồn và căn cứ quan sát. Với ca ngã, mốc chạm là khung đầu có tiếp xúc chịu tải quan sát được, ví dụ tay chống sàn. Khung đối chiếu nằm ở `data/review/`. Trạng thái `review` giữ clip cho lần rà tiếp theo. Kiểm kê đánh dấu bản trùng hoặc file lỗi theo manifest và giữ file gốc tại chỗ.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Split
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Extract
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Train
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Evaluate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Check
```

`Split` chạy lại được với cùng danh sách đủ điều kiện. Sau khi đã xem kết quả test, dùng `Split -Rebuild -FreshTest` khi có thêm nhãn từ người mới. Lệnh sẽ giữ người của test trước ở ngoài đợt mới và chọn test từ mã người chưa tham gia split trước. `Extract -IncludeReview` đo độ phủ tư thế của cả clip đang rà. `Web` đọc model có sẵn và khởi động độc lập với các bước tải và train.

## Dữ liệu đi qua model

1. PyAV đọc PTS, chọn frame theo nhịp 10 Hz và áp dụng góc xoay. Hai video pilot ngang sai metadata có góc sửa ghi tại [overrides.json](data/review/overrides.json). MoveNet v4 giữ nguyên trọng số, nhận ảnh RGB 192 × 192 có viền và trả 17 điểm. Pipeline bỏ phần viền khi đổi điểm về tọa độ pixel theo chiều ảnh gốc đã xoay. Cache `data/processed/` ghi PTS, kích thước, tọa độ, độ tin cậy, trạng thái quan sát và khóa gồm checksum, phiên bản runtime và cấu hình.
2. Mỗi khoảng 0,25 giây lấy tối đa hai giây quá khứ. Khi mất dấu, phiên báo không nhìn rõ. Sau khoảng trống trên 0,36 giây hoặc tọa độ nhảy quá 0,9 chiều dài thân khi bắt lại dấu, cửa sổ phải tích lũy lại. Khoảng mất dấu ngắn làm giảm đặc trưng độ phủ tư thế. Mô hình dùng độ hạ, vận tốc của vai và hông, độ nghiêng và biến đổi thân, chiều cao biểu kiến, độ phủ khớp và dịch chuyển ngang. Chuẩn hóa dịch chuyển bằng chiều dài thân ở phần đầu cửa sổ. Cờ thiếu và giá trị thiếu được giữ cho bộ điền dữ liệu.
3. Cửa sổ Fall cần giao với đoạn mất thăng bằng đến chạm ít nhất 0,20 giây hoặc 75% đoạn với ca ngắn hơn. Cửa sổ có thể kết thúc tới 0,75 giây sau chạm. Cửa sổ No_Fall phải nằm trọn trong một khoảng đã xác nhận. Khoảng ranh giới và phần nằm lâu sau ngã được bỏ qua khi tạo mẫu. Thứ tự đặc trưng và cấu hình lưu cùng classifier. `data/processed/train_windows.csv` cho tra lại mẫu train và thời điểm kết thúc.
4. Seed 37 chia theo người trước khi tạo cửa sổ, giữ cùng lượt quay và checksum trong một nhóm. Mã người thiếu hoặc mâu thuẫn nằm ngoài split. Logistic Regression và Random Forest nhận cùng đặc trưng. Imputer và scaler được fit trên train. Ngưỡng chọn trên validation, ưu tiên recall với mục tiêu 1 báo giả/giờ ADL. Khi video ADL quá ngắn để có ngưỡng bắt được ca trong mục tiêu đó, dùng số báo giả quan sát nhỏ nhất cho phép phát hiện trên validation làm ngân sách chung. Hai dự đoán liên tiếp vượt ngưỡng tạo một cảnh báo. Có thời gian reset 0,75 giây và khoảng cách tối thiểu 3 giây giữa hai báo.
5. Replay xử lý frame nối tiếp qua cùng engine dùng cho camera. Tại thời điểm đang phát, giao diện dùng kết quả mới nhất có timestamp không vượt quá thời gian video. Test dùng cấu hình đã chốt. Cảnh báo đầu trong khoảng từ 0,25 giây trước mất thăng bằng đến 1,5 giây sau chạm được ghép với sự kiện. Độ trễ âm nghĩa là cảnh báo trước mốc chạm.

Lệnh `Check` thử đường dẫn ngoài project, người/lượt quay/checksum giữa các tập, tính nhân quả, mất dấu, đánh giá sự kiện và đóng phiên. Với model và split có sẵn, kiểm tra lấy lại một clip test thật từ MP4, đối chiếu đặc trưng giữa giải mã mới và cache với sai số tuyệt đối 1e-7, rồi so timestamp, trạng thái và cảnh báo API replay. Kết quả kiểm tra Chrome và backend nằm trong [verification.md](reports/verification.md).

## Điện thoại cùng Wi-Fi

Camera của trình duyệt cần ngữ cảnh an toàn. Laptop truy cập qua localhost. Điện thoại kết nối vào địa chỉ HTTPS của laptop với chứng chỉ có SAN khớp địa chỉ IP và được điện thoại tin cậy. Đặt file PEM và private key trong `.secrets` của project. Chọn IPv4 riêng của laptop trên Wi-Fi và khởi chạy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 Web -HostAddress 192.168.1.20 -Cert .secrets/lan.pem -Key .secrets/lan-key.pem
```

Trên điện thoại mở `https://192.168.1.20:8765/` với IP thực của laptop, bấm **Bắt đầu theo dõi**, cấp quyền camera và dùng **Đổi camera** nếu có nhiều camera. HTTP tới IP LAN thường thiếu quyền truy cập camera. **Thử video** được phục vụ qua localhost. Thiết bị thật và chứng chỉ của mạng chấm cần được xác nhận tại chỗ. [MDN về quyền camera và HTTPS](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

## Nguồn

- VARISHTA-MM50 của Abha Tewari và Dhananjay Kalbande, Sardar Patel Institute of Technology, 2026. Danh mục tải ghim Kaggle API v5. Trang Kaggle ghi CC0, README trong dữ liệu ghi CC BY 4.0. Project giữ attribution theo README và các video gốc trong workspace để kiểm tra và demo. Ca ngã trong dataset là mô phỏng được giám sát. [Kaggle VARISHTA-MM50](https://www.kaggle.com/datasets/abhatewari22/varishta-mm50-organized)
- MoveNet SinglePose Lightning v4, bản TFLite float16, Apache 2.0. Nguồn và checksum tại [movenet.json](models/movenet.json). [Model Google trên Kaggle](https://www.kaggle.com/models/google/movenet/tflite/singlepose-lightning-tflite-float16/1) · [Hướng dẫn TensorFlow](https://www.tensorflow.org/hub/tutorials/movenet)
