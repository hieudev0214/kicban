# kicban — Video → Text

Web app: đăng ký/đăng nhập tài khoản, nạp tiền vào ví bằng chuyển khoản ngân hàng (quét mã VietQR,
admin xác nhận thủ công), dán link video (TikTok/Facebook/URL trực tiếp) hoặc tải file video/audio lên
để trích văn bản giọng nói (đa ngôn ngữ) qua OpenAI API. Mỗi lượt transcribe trừ tiền vào ví theo **bậc
thang thời lượng video** (xem mục "Bảng giá" bên dưới) - tài khoản mới được **1 lượt miễn phí** cho
video ngắn. Có trang quản trị (admin) để duyệt yêu cầu nạp tiền, xem user/job, cộng/trừ tiền thủ công,
khoá/xoá tài khoản.

**YouTube tạm thời chưa được hỗ trợ** (YouTube chặn PO Token trên IP cloud, xem `CLAUDE.md` để biết
chi tiết) — engine local (`faster-whisper`) cũng đã bị gỡ bỏ, chỉ còn dùng OpenAI API.

## Yêu cầu hệ thống

- [`uv`](https://docs.astral.sh/uv/) đã cài (ghim Python 3.12 riêng cho project).
- `ffmpeg`/`ffprobe` có sẵn trên PATH (dùng để trích audio từ video).
- Tài khoản OpenAI API (bắt buộc — không còn engine miễn phí).
- Một tài khoản ngân hàng để nhận tiền nạp ví (không cần đăng ký merchant/cổng thanh toán nào —
  xem mục "Cấu hình nạp tiền" bên dưới).

## Cài đặt

```bash
uv sync
cp .env.example .env
```

Sửa `.env`:
- `OPENAI_API_KEY` — bắt buộc, dùng cho transcribe.
- `SECRET_KEY` — bắt buộc trong production, ký session đăng nhập. Sinh bằng:
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_EMAILS` — email nào đăng ký/đăng nhập bằng email này sẽ tự động thành admin. Đây là cách
  duy nhất để tạo tài khoản admin đầu tiên.
- `BANK_ID`, `BANK_ACCOUNT_NO`, `BANK_ACCOUNT_NAME` — tài khoản ngân hàng nhận tiền nạp ví (xem mục
  bên dưới). Nếu để trống, tính năng nạp tiền sẽ bị vô hiệu hoá (nút "Nạp tiền" báo lỗi), các phần
  khác vẫn chạy bình thường.

## Chạy

```bash
uv run uvicorn app.main:app --reload
```

Mở `http://localhost:8000`.

## Chạy test

```bash
uv run pytest
```

## Bảng giá

Phí transcribe tính theo **bậc thang thời lượng video** (định nghĩa trong `app/pricing.py`, không phải
biến môi trường vì đây là cả bảng chứ không phải một con số):

| Thời lượng video | Giá |
|---|---|
| ≤ 2 phút | 3.000đ |
| 2–5 phút | 6.000đ |
| 5–8 phút | 10.000đ |
| 8–15 phút | 15.000đ |
| 15–30 phút | 25.000đ |
| 30–60 phút | 40.000đ |
| 60–120 phút | 70.000đ |

Mỗi bậc định giá cao hơn hẳn chi phí thật (Whisper ~$0.006/phút, tức ~150đ/phút) kể cả ở giới hạn trên
của bậc đó, nên không bậc nào bị lỗ. Tài khoản mới được **1 lượt transcribe miễn phí** cho video ≤10
phút (`pricing.FREE_TRIAL_MAX_SECONDS`) — nếu lượt đó lỗi, hệ thống trả lại lượt miễn phí thay vì tính
là đã dùng.

Muốn đổi giá/bậc, sửa trực tiếp `TIERS` trong `app/pricing.py` rồi deploy lại.

## Cấu hình nạp tiền (chuyển khoản thủ công + VietQR)

Không dùng cổng thanh toán trung gian nào (VNPay/MoMo/PayOS...) — mọi cổng thanh toán tự động đều bắt
buộc xác thực danh tính/doanh nghiệp trước khi cấp API key (quy định pháp luật, không né được), việc
đó tốn thời gian chờ duyệt. Thay vào đó dùng thẳng tài khoản ngân hàng cá nhân/doanh nghiệp bạn đang
có sẵn, hiển thị mã QR chuẩn VietQR (miễn phí, công khai, không cần đăng ký) cho khách quét chuyển
khoản, rồi admin tự đối chiếu và duyệt.

1. Điền vào `.env`:
   - `BANK_ID` = mã ngân hàng viết tắt hoặc mã BIN (ví dụ `vietcombank` hoặc `970436`) — tra cứu đầy đủ
     tại https://api.vietqr.io/v2/banks.
   - `BANK_ACCOUNT_NO` = số tài khoản nhận tiền.
   - `BANK_ACCOUNT_NAME` = tên chủ tài khoản (không dấu, đúng như trên thẻ/tài khoản).
2. Luồng hoạt động:
   - User bấm "Nạp tiền", nhập số tiền → hệ thống tạo yêu cầu (trạng thái `pending`) kèm **nội dung
     chuyển khoản riêng** (dạng `NAP XXXXXXXX`) và hiện mã QR VietQR tương ứng.
   - User quét mã bằng app ngân hàng, chuyển khoản **giữ nguyên nội dung** đó.
   - Admin vào `/admin`, mục "Yêu cầu nạp tiền đang chờ" — đối chiếu với sao kê ngân hàng thật, bấm
     **Duyệt** để cộng tiền vào ví, hoặc **Từ chối** nếu không khớp/không nhận được tiền.
   - Không có xác nhận tự động — đây là đánh đổi chấp nhận được để tránh phải qua quy trình đăng ký
     merchant tốn thời gian của các cổng thanh toán.

## Tài khoản admin

Không có giao diện "tạo admin" riêng — thêm email của bạn vào biến `ADMIN_EMAILS` (phân tách bằng dấu
phẩy nếu nhiều email) trước khi đăng ký/đăng nhập bằng email đó, tài khoản sẽ tự động có quyền admin.
Trang quản trị ở `/admin`: duyệt/từ chối yêu cầu nạp tiền, xem danh sách user + số dư + lịch sử job,
cộng/trừ tiền thủ công, khoá/mở khoá, xoá tài khoản.

## Đưa lên web công khai

- Đã có sẵn `Dockerfile` + `.dockerignore`:
  ```bash
  docker build -t kicban .
  docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e SECRET_KEY=... -e ADMIN_EMAILS=you@example.com kicban
  ```
- **Rate limit** có sẵn (`MAX_JOBS_PER_HOUR_PER_IP`, mặc định 5/giờ/IP) chống spam ngoài cơ chế ví tiền.
- **Deploy lên Render.com**:
  1. Push code lên GitHub.
  2. Render: New → Web Service → connect repo → tự nhận diện `Dockerfile`.
  3. Tab Environment: thêm đầy đủ biến trong `.env.example` (đặc biệt `SECRET_KEY`, `ADMIN_EMAILS`,
     `OPENAI_API_KEY`, `BANK_*`).
  4. Deploy. Gói miễn phí dùng ổ đĩa tạm (ephemeral) — `data/jobs.db` (user, ví, lịch sử job) sẽ **mất
     khi redeploy**. Muốn giữ dữ liệu lâu dài cần gói trả phí có Persistent Disk gắn vào `/app/data`,
     **bắt buộc** một khi đã có user thật nạp tiền thật (mất dữ liệu = mất luôn thông tin số dư/thanh
     toán của khách).

### Cấu hình cookies cho yt-dlp (TikTok/Facebook trên cloud)

⚠️ **Dùng file cookies riêng cho TikTok, không gộp chung với cookies khác** — đã kiểm chứng thực tế:
gộp cookies domain khác vào cùng file làm hỏng khả năng vượt bot-check của TikTok.

1. Cài extension **"Get cookies.txt LOCALLY"** (Chrome/Edge Web Store).
2. Đăng nhập TikTok bằng tài khoản thật → mở extension trên tab `tiktok.com` → **Export** (không phải
   "Export All Cookies") → lưu thành file `cookies.txt`.
3. Trên Render: **Environment → Secret Files → Add Secret File**: Filename `cookies.txt`, dán nội dung.
4. Thêm biến `YTDLP_COOKIES_FILE` = `/etc/secrets/cookies.txt`.
5. Render tự redeploy. Thử lại link TikTok.

⚠️ Cookie TikTok hết hạn khá nhanh trong thực tế (đã ghi nhận chỉ ~1 ngày) — nếu lại lỗi "Could not
access this video", lặp lại bước 2 để lấy cookie mới. `YTDLP_COOKIES_FILE_YOUTUBE` vẫn còn trong code
(dự phòng cho lúc bật lại YouTube) nhưng hiện không cần cấu hình vì YouTube đang bị chặn ở tầng API.

## Cấu trúc

Xem chi tiết trong `CLAUDE.md`. Tóm tắt: `media.py` (tải video/audio), `audio.py` (chuẩn hoá bằng
ffmpeg), `transcribe.py` (OpenAI STT), `jobs.py` (hàng đợi xử lý nền + hoàn tiền tự động khi lỗi),
`auth.py`/`routes/auth.py` (đăng ký/đăng nhập), `vietqr.py`/`routes/wallet.py` (yêu cầu nạp tiền +
tạo mã QR), `routes/admin.py` (quản trị, gồm duyệt nạp tiền). Dữ liệu lưu tại `data/jobs.db` (SQLite).
