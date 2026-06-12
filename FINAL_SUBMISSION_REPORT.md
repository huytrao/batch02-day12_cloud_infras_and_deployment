# ✅ Delivery Checklist — Day 12 Lab Submission

> **Student Name:** Trảo An Huy
> **Student ID:** 2A202600819
> **Date:** 2026-06-12
> **GitHub Repo:** https://github.com/huytrao/day12_ha-tang-cloud_va_deployment
> **API URL:** https://day12-ai-agent.onrender.com

---

## 📋 Trạng thái nộp bài (Lab Submission Status)

### 1. 📝 File Đáp án (`Solution.md`)
- [x] Đã hoàn thành toàn bộ câu trả lời cho các bài Codelab từ **Part 1 -> Part 5**.
- [x] Link đến file: [Solution.md](./Solution.md)

### 2. 🤖 Dự án Cuối khóa (`06-lab-complete`)
- [x] **Thay thế Agent:** Đã đưa mock_llm Agent tinh gọn và chuẩn hóa vào `06-lab-complete/app` để thuận tiện cho việc tích hợp hạ tầng và các tiêu chuẩn chạy Production.
- [x] **Tích hợp Lab 4 (Security & Control):**
  - [x] **API Key & JWT Auth:** Bảo vệ API `/ask` qua `X-API-Key` header và route `/auth/token`.
  - [x] **Rate Limiting:** Giới hạn 10 requests/phút lưu trữ qua Redis sliding window (fallback local in-memory).
  - [x] **Cost Guard:** Tự động tính toán lượng token, quản lý ngân sách tháng ($10/tháng) và chặn request khi vượt ngưỡng (trả về lỗi 402).
- [x] **Tích hợp Lab 5 (Reliability & Scaling):**
  - [x] **Stateless Session:** Lưu lịch sử hội thoại vào Redis dựa theo `session_id`, cho phép scale ngang không đồng bộ.
  - [x] **Health & Readiness Check:** Endpoint `/health` (liveness) và `/ready` (kiểm tra kết nối Redis).
  - [x] **Graceful Shutdown:** Middleware và signal handlers (`SIGTERM`/`SIGINT`) tự động trì hoãn 30s để xử lý nốt các in-flight requests trước khi tắt hẳn.
- [x] **Chạy thử local & Cloud:**
  - [x] Xác minh và test thành công toàn bộ API tại local (`http://127.0.0.1:8000`).
  - [x] Deploy và kiểm thử thành công trên Render/Railway.

**🚀 Chúc các bạn nộp bài thành công!**
