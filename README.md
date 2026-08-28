# kicban — Video → Text

Web app nhỏ: dán link video (YouTube/TikTok/Facebook/URL trực tiếp) hoặc tải file video/audio lên,
tool tự động trích văn bản giọng nói (đa ngôn ngữ). Có 2 engine speech-to-text để chọn: **local**
(miễn phí, chạy bằng `faster-whisper` trên máy) hoặc **OpenAI API** (trả phí, nhanh hơn khi cần xử lý nhiều).

## Yêu cầu hệ thống

- Windows với [`uv`](https://docs.astral.sh/uv/) đã cài (dùng để ghim Python 3.12 riêng cho project,
  vì Python 3.14 mặc định trên máy chưa có wheel tương thích cho `faster-whisper`).
- `ffmpeg`/`ffprobe` có sẵn trên PATH (dùng để trích audio từ video).
- (Tuỳ chọn) GPU NVIDIA + [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) cài đặt riêng
  nếu muốn engine local chạy nhanh trên GPU. **Lưu ý**: chỉ cài driver NVIDIA thôi thường chưa đủ —
  `ctranslate2` trên Windows cần cuBLAS/cuDNN từ CUDA Toolkit; nếu thiếu, app tự động rơi về chạy CPU
  (chậm hơn nhưng vẫn hoạt động đúng, đã kiểm chứng khi build).

## Cài đặt

```bash
uv sync
cp .env.example .env
```

Sửa `.env` nếu muốn:
- Đổi `WHISPER_MODEL` (`tiny`/`base`/`small`/`medium`/`large-v3`) — mặc định `medium`.
- Điền `OPENAI_API_KEY` nếu muốn bật engine OpenAI trên UI (để trống thì nút OpenAI sẽ bị ẩn/disable).

## Chạy

```bash
uv run uvicorn app.main:app --reload
```

Mở `http://localhost:8000`.

## Chạy test

```bash
uv run pytest
```

## Đưa lên web công khai (nhiều người dùng)

Nếu dùng cá nhân trên máy này thì bỏ qua phần này. Nếu muốn public cho người khác dùng:

- **Host trên nền tảng không có GPU** (Render/Railway/VPS thường...): dùng engine **OpenAI** làm
  chính (`OPENAI_API_KEY` bắt buộc set trên server) — engine Local vẫn chạy được (đã test kỹ trong
  Docker container không GPU, tự động fallback về CPU đúng cách) nhưng sẽ **rất chậm** trên CPU dùng
  chung của nhiều người, không phù hợp cho nhiều người dùng cùng lúc.
- Đã có sẵn `Dockerfile` + `.dockerignore`, build/test được bằng Docker thật (không chỉ lý thuyết):
  ```bash
  docker build -t kicban .
  docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e MAX_JOBS_PER_HOUR_PER_IP=10 kicban
  ```
- **Rate limit** đã có sẵn (`MAX_JOBS_PER_HOUR_PER_IP`, mặc định 5/giờ/IP) để tránh bị spam tốn tiền
  OpenAI API — chỉnh qua biến môi trường tuỳ nhu cầu thực tế.
- **YouTube/TikTok chặn IP của hosting cloud**: đây là vấn đề rất phổ biến — các nền tảng này
  chặn/bot-check các IP datacenter (Render, AWS, v.v.), khiến `yt-dlp` không tải được dù code đúng.
  Cách khắc phục: dùng cookies từ tài khoản thật để `yt-dlp` giả dạng người dùng thật. Xem hướng dẫn
  chi tiết bên dưới.
- **Deploy lên Render.com** (đơn giản nhất cho người mới):
  1. Push code lên GitHub (repo git đã có sẵn ở đây, `git init` đã chạy tự động lúc `uv init`).
  2. Trên Render: New → Web Service → connect repo → Render tự nhận diện `Dockerfile`.
  3. Tab Environment: thêm `OPENAI_API_KEY`, `MAX_JOBS_PER_HOUR_PER_IP`, `MAX_UPLOAD_MB`,
     `MAX_DURATION_SECONDS` tuỳ ý.
  4. Deploy. Gói miễn phí của Render dùng ổ đĩa tạm (ephemeral) — nghĩa là `data/jobs.db` (lịch sử
     job) sẽ mất khi service restart/redeploy. Không ảnh hưởng chức năng transcribe, chỉ mất lịch sử
     cũ. Muốn giữ lịch sử lâu dài thì cần gói trả phí có Persistent Disk gắn vào `/app/data`.

### Cấu hình cookies cho yt-dlp (bắt buộc nếu deploy lên cloud)

1. Cài extension **"Get cookies.txt LOCALLY"** (Chrome/Edge Web Store) hoặc extension tương tự xuất
   cookie định dạng Netscape.
2. Đăng nhập YouTube bằng tài khoản Google thật trên trình duyệt → mở extension → xuất cookies cho
   `youtube.com` → lưu file. Làm tương tự cho TikTok (đăng nhập `tiktok.com` → xuất cookies) — có thể
   gộp chung 1 file `cookies.txt` (mỗi dòng ghi domain riêng, không xung đột nhau).
3. Trên Render: vào service → **Environment** → mục **Secret Files** → **Add Secret File**:
   - Filename/path: `/etc/secrets/cookies.txt`
   - Contents: dán nội dung file `cookies.txt` vừa xuất.
4. Cũng ở tab Environment, thêm biến `YTDLP_COOKIES_FILE` = `/etc/secrets/cookies.txt`.
5. Render tự redeploy sau khi lưu. Thử lại link YouTube/TikTok.

⚠️ Cookie có thể hết hạn theo thời gian (vài tuần đến vài tháng tuỳ nền tảng) — nếu link lại bị lỗi
"not supported" sau một thời gian, lặp lại bước 1-2 để lấy cookie mới.

## Cấu trúc

Xem chi tiết trong `app/` — `media.py` (tải video/audio), `audio.py` (chuẩn hoá bằng ffmpeg),
`transcribe.py` (2 engine STT), `jobs.py` (hàng đợi xử lý nền), `routes/` (API + trang web).
Dữ liệu job lưu tại `data/jobs.db` (SQLite), model local tải về `models/`.
