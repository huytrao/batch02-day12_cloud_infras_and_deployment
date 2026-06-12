# Day 12 Lab - Solution Answers (Codelab 1-5)

> **Student:** Trảo An Huy | **ID:** 2A202600819 | **Date:** 2026-06-12

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in basic app.py
1. **Hardcoded API key** (`api_key = "sk-abc123..."`): Lộ mã khóa bí mật trực tiếp trong mã nguồn. Nếu đưa lên GitHub/GitLab, người khác có thể lợi dụng để đánh cắp tiền/tài nguyên.
2. **Hardcoded port** (`app.run(port=8000)`): Cố định cổng dịch vụ khiến ứng dụng không linh hoạt và dễ bị lỗi nếu cổng đó bị xung đột trên môi trường production.
3. **Debug mode always on** (`debug=True`): Khi có lỗi xảy ra, stack trace và trình debug tương tác sẽ hiển thị trực tiếp cho người dùng, tạo cơ hội cho tin tặc khai thác thông tin hệ thống.
4. **No health check endpoint**: Không có các endpoint kiểm tra trạng thái hoạt động khiến các nền tảng đám mây không thể tự động phát hiện và khởi động lại container bị lỗi/treo.
5. **No graceful shutdown**: Tiến trình bị ngắt ngay lập tức khi nhận tín hiệu SIGTERM, làm hủy bỏ các request đang xử lý dở dang và có khả năng gây hỏng dữ liệu.
6. **`print()` instead of structured logging**: Sử dụng hàm `print()` thông thường thay vì log có cấu trúc (như JSON), làm cho việc phân tích, tìm kiếm và giám sát log trên các hệ thống giám sát tập trung gặp khó khăn.
7. **State in memory**: Lưu trữ dữ liệu lịch sử hội thoại trong biến toàn cục (RAM) của ứng dụng, khiến hệ thống không thể scale ngang (load balancing giữa nhiều instance vì mỗi instance có một bản lưu dữ liệu khác nhau) và dữ liệu sẽ mất sạch khi ứng dụng khởi động lại.

### Exercise 1.3: Comparison table

| Feature | Develop (Basic) | Production (Advanced) | Why Important? (Tại sao quan trọng?) |
|---------|-----------------|----------------------|--------------------------------------|
| **Config** | Hardcoded values | Environment variables (`.env`) | Bảo mật (không lộ bí mật trong code) và linh hoạt (chạy ứng dụng trên nhiều môi trường khác nhau không cần sửa code). |
| **Health check** | ❌ Missing | ✅ `/health` returns 200 | Giúp hệ thống tự động phát hiện container hỏng để khởi động lại, và cân bằng tải tránh hướng traffic vào instance lỗi. |
| **Logging** | `print()` statements | Structured JSON logs | Dễ dàng quản lý, lọc và giám sát log bằng các công cụ quản lý log tập trung như CloudWatch, Datadog hay ELK Stack. |
| **Shutdown** | Abrupt (kill process) | Graceful (SIGTERM handler) | Giúp hoàn thành các request đang chạy và đóng các kết nối an toàn để tránh mất dữ liệu hoặc hỏng session. |
| **Auth** | ❌ None | ✅ API key / JWT | Bảo vệ tài nguyên và API để không ai có thể gọi API bừa bãi và làm tăng chi phí LLM vô tội vạ. |
| **Rate Limiting** | ❌ None | ✅ 10 req/min per user | Ngăn ngừa tấn công từ chối dịch vụ (DDoS) và lạm dụng API gây phát sinh chi phí đột biến. |
| **State storage** | In-memory dict | Redis | Lưu trữ trạng thái không phụ thuộc vào bộ nhớ RAM của tiến trình đơn lẻ, cho phép scale ngang nhiều bản sao và duy trì session khi khởi động lại. |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions
1. **Base image:** `python:3.11-slim` — Phiên bản rút gọn (slim) của Python 3.11 chính thức. Nó loại bỏ hầu hết các package không cần thiết để giảm thiểu kích thước Docker image xuống khoảng 60%.
2. **Working directory:** `/app` — Thư mục làm việc mặc định trong container mà tất cả các câu lệnh tiếp theo sẽ chạy tại đó.
3. **Tại sao COPY requirements.txt trước?** — Tận dụng cơ chế lưu cache layer của Docker. Docker chỉ rebuild layer `pip install` khi file `requirements.txt` thay đổi. Điều này giúp đẩy nhanh tốc độ build đáng kể khi chỉ thay đổi mã nguồn mà không đổi thư viện.
4. **CMD vs ENTRYPOINT:**
   - `ENTRYPOINT` định nghĩa câu lệnh cố định luôn được chạy khi khởi tạo container (ví dụ: `python`). Nó không thể dễ dàng bị ghi đè.
   - `CMD` định nghĩa các đối số mặc định truyền cho `ENTRYPOINT` và có thể bị ghi đè khi ta chạy lệnh `docker run <image> <args>`. Khi kết hợp: `ENTRYPOINT ["python"]` và `CMD ["app.py"]`, nếu ta gõ `docker run my-img test.py` thì container sẽ chạy `python test.py`.

### Exercise 2.3: Image size comparison

| Build | Size | Notes |
|-------|------|-------|
| Develop (basic Dockerfile) | ~900 MB – 1.2 GB | Sử dụng base image đầy đủ và để lại toàn bộ các công cụ build (gcc, header files, v.v.). |
| Production (multi-stage) | ~150 – 200 MB | Chỉ sao chép các dependencies đã được biên dịch xong sang runtime image và loại bỏ các công cụ build thừa. |
| **Difference** | **~85%** nhỏ hơn | Giảm thời gian pull/push image lên registry và tiết kiệm dung lượng lưu trữ trên cloud. |

*Cơ chế:* Multi-stage build cho phép chia quá trình dựng ảnh làm hai (hoặc nhiều) giai đoạn. Giai đoạn `builder` sử dụng đầy đủ các công cụ để compile/install các thư viện C/Python, sau đó giai đoạn `runtime` chỉ copy thư viện đã cài đặt sang một môi trường sạch sẽ và gọn nhẹ, loại bỏ các file tạm và build tools dư thừa.

### Exercise 2.4: Architecture diagram
```
Client
  │ HTTP :80
  ▼
Nginx (port 80)   ← Cân bằng tải / Reverse Proxy
  │ round-robin
  ├──────┬──────┐
  ▼      ▼      ▼
Agent  Agent  Agent   ← Các instance FastAPI (:8000) chạy stateless
  └──────┴──────┘
         │
         ▼
       Redis :6379   ← Bộ lưu trữ trạng thái tập trung (session, rate limit, budget)
```
Các dịch vụ giao tiếp nội bộ trong mạng Docker. Nginx gọi tới Agent thông qua DNS nội bộ của Docker Compose (`http://agent:8000`). Các Agent giao tiếp với Redis qua địa chỉ `redis:6379`.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway/Render deployment
- **URL:** https://day12-ai-agent.onrender.com
- **Platform:** Render.com (Tài khoản được liên kết và thiết lập thông qua Render Blueprint Blueprint Instance tự động).
- **Các bước thực hiện:**
  1. Cấu hình dịch vụ Redis và Web service sử dụng Dockerfile trong file `render.yaml`.
  2. Commit và push code lên GitHub repository.
  3. Kết nối repo với tài khoản Render.
  4. Tạo Blueprint Instance. Render tự động thiết lập và liên kết Redis `connectionString` vào biến môi trường `REDIS_URL` của web service.
  5. Đăng ký các biến môi trường bảo mật bổ sung như `AGENT_API_KEY`, `JWT_SECRET`.
  6. Deploy thành công và xác nhận ứng dụng chạy trực tuyến.

### Exercise 3.2: Comparison of render.yaml vs railway.toml

| Aspect | `railway.toml` | `render.yaml` |
|--------|----------------|---------------|
| **Builder** | `DOCKERFILE` | `docker` |
| **Health check** | `healthcheckPath` | `healthCheckPath` |
| **Start command** | `startCommand` | Tự động đọc từ `Dockerfile CMD` hoặc chỉ định `startCommand` |
| **Auto-deploy** | Tự động khi push | Tự động khi push |
| **Key difference** | Cấu hình cho một service đơn lẻ, tập trung vào môi trường chạy local/remote CLI. | Hỗ trợ cấu hình hạ tầng phức tạp (nhiều service liên kết như web + redis + db) trong cùng một file duy nhất. |

---

## Part 4: API Security

### Exercise 4.1: API Key authentication
- API key được kiểm tra tại `app/auth.py` bằng hàm `verify_api_key()` tích hợp trong cơ chế Dependency Injection (`Depends`) của FastAPI.
- Nếu request không chứa key hoặc key không hợp lệ, hệ thống sẽ trả về lỗi **401 Unauthorized** kèm tiêu đề `WWW-Authenticate: ApiKey`.
- Để thay đổi/rotate key: cập nhật biến môi trường `AGENT_API_KEY` trong bảng điều khiển Cloud (Render/Railway) mà không cần thay đổi mã nguồn ứng dụng.

### Exercise 4.2: JWT authentication
JWT flow hoạt động như sau:
1. Client gửi yêu cầu đăng nhập chứa username và password tới `POST /auth/token`.
2. Hệ thống kiểm tra thông tin, nếu đúng sẽ tạo một chuỗi JWT đã được ký với khoá bảo mật `JWT_SECRET` (chứa tên người dùng và vai trò) gửi về cho Client.
3. Trong các request tiếp theo, Client gửi token này qua header `Authorization: Bearer <token>`.
4. Máy chủ giải mã token bằng `JWT_SECRET` để lấy thông tin user_id và kiểm tra thời hạn (thường hết hạn sau 60 phút). Nếu hết hạn hoặc sai chữ ký, hệ thống trả về lỗi **401 Unauthorized**.

### Exercise 4.3: Rate limiting
- **Thuật toán sử dụng:** Fixed-window counter (Cửa sổ thời gian cố định).
- **Giới hạn cấu hình:** 10 requests mỗi 60 giây cho mỗi user (cấu hình linh hoạt qua biến môi trường `RATE_LIMIT_PER_MINUTE`).
- **Nơi lưu trữ:** Redis — Đảm bảo tính nhất quán trên toàn bộ các bản sao (instance) khác nhau khi ứng dụng scale ngang.
- **Admin bypass:** Sử dụng `rate_limiter_admin` cho phép Admin gọi tới 100 requests/phút.
- **Khi vượt ngưỡng:** Trả về mã lỗi **429 Too Many Requests** kèm theo header `Retry-After` chỉ định số giây cần chờ trước khi thử lại.

### Exercise 4.4: Cost guard implementation
- **Cách thức hoạt động:** Lưu trữ tổng chi phí tích luỹ của từng user trong Redis bằng cách tăng dần số thực (`incrbyfloat`). Sử dụng chuỗi định danh theo tháng `budget:<user_id>:<YYYY-MM>` và đặt thời gian hết hạn (`expire`) là 32 ngày để tự động reset hạn mức vào đầu mỗi tháng.
- Trước khi xử lý request, hệ thống gọi `check_budget()` để đảm bảo tổng số tiền chưa vượt hạn mức cấu hình (ví dụ $10/tháng). Nếu vượt quá, trả về mã lỗi **402 Payment Required** và từ chối xử lý LLM. Sau khi gọi LLM thành công, ghi nhận token sử dụng và cập nhật chi phí vào Redis.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health and readiness checks
- `/health` (Liveness probe): Dùng để báo cho nền tảng deploy biết tiến trình ứng dụng vẫn đang chạy (trả về 200).
- `/ready` (Readiness probe): Kiểm tra xem ứng dụng đã sẵn sàng xử lý traffic chưa bằng cách thử kết nối tới các dịch vụ hạ tầng phụ thuộc như Redis (`_redis.ping()`). Nếu kết nối thất bại, trả về lỗi **503 Service Unavailable** để load balancer biết và ngừng chuyển traffic tới instance này.

### Exercise 5.2: Graceful shutdown
- Khi nền tảng đám mây muốn tắt hoặc deploy bản mới, nó sẽ gửi tín hiệu `SIGTERM` tới container.
- Chương trình bắt tín hiệu `SIGTERM` bằng hàm xử lý `shutdown_handler`.
- Đặt trạng thái ứng dụng thành đang tắt (`_shutting_down = True`), các middleware sẽ ngay lập tức trả về lỗi 503 cho các request mới đến.
- Hệ thống chờ một khoảng thời gian ngắn (ví dụ: 2 giây) để các request hiện tại (in-flight) kịp hoàn thành xử lý.
- Sau đó, đóng kết nối cơ sở dữ liệu/Redis và gọi `sys.exit(0)` kết thúc tiến trình an toàn mà không làm rớt kết nối đột ngột của người dùng.

### Exercise 5.3: Stateless design
- **Stateful (Lỗi thiết kế):** Lưu trữ thông tin hội thoại trong RAM của tiến trình thông qua biến toàn cục `conversation_history = {}`. Khi có nhiều instance chạy sau load balancer, request tiếp theo của một user có thể được chuyển sang instance khác và làm mất lịch sử trò chuyện.
- **Stateless (Chuẩn production):** Không lưu trữ bất kỳ trạng thái nào trong RAM. Mọi session chat, lịch sử hội thoại được lưu tập trung trong Redis. Khi nhận request, Agent sẽ kéo session tương ứng từ Redis, xử lý rồi lưu ngược lại Redis. Nhờ đó, bất kỳ instance nào cũng có thể xử lý yêu cầu của bất kỳ người dùng nào vào bất cứ lúc nào.

### Exercise 5.4 & 5.5: Load balancing & Stateless test
- Khi scale số instance: `docker compose up --scale agent=3`, Nginx sẽ phân phối yêu cầu theo thuật toán Round-Robin.
- Khi ta tắt đột ngột một instance (`docker compose kill agent` ngẫu nhiên), Nginx sẽ tự động định tuyến lại các request tiếp theo sang các instance còn lại.
- Do dữ liệu hội thoại nằm tập trung ở Redis, người dùng vẫn có thể tiếp tục trò chuyện bình thường mà không bị mất lịch sử chat hay gián đoạn trải nghiệm.

---

## Part 6: Final Project (Production AI Agent)

### Kiến trúc tổng thể và các tính năng đã tích hợp:
Dự án cuối khóa đã được thực hiện và lưu trong thư mục `06-lab-complete/app`. Tất cả các tính năng từ lý thuyết đã được áp dụng vào thực tế để biến một Agent cơ bản thành chuẩn Production:
https://day12-ai-agent-c4wo.onrender.com/
1. **Config Management:** Toàn bộ cấu hình (Port, Redis URL, JWT Secret, API Key, Budget) được đẩy ra biến môi trường (`.env`) và quản lý bằng `pydantic_settings` trong `app/config.py`.
2. **API Security:** 
   - Route `/ask` được bảo vệ nghiêm ngặt bằng Dependency xác thực `X-API-Key`.
   - Cung cấp thêm route `/auth/token` để hỗ trợ sinh JWT Token mở rộng đăng nhập cho người dùng.
3. **Rate Limiting & Cost Guard:** Tích hợp bộ đếm Sliding Window Limit trên Redis (giới hạn 10 requests/phút) và hệ thống kiểm soát ngân sách LLM ($10/tháng). Nếu người dùng vượt ngưỡng, hệ thống lập tức tự động chặn bằng mã lỗi HTTP `429 Too Many Requests` hoặc `402 Payment Required`.
4. **Reliability & Scaling:** 
   - **Health Checks:** Cung cấp chuẩn `/health` (Liveness) và `/ready` (Readiness) để các nền tảng đám mây (Render/Railway) tự động giám sát và quản lý container.
   - **Graceful Shutdown:** Bắt sự kiện ngắt `SIGTERM` bằng signal handler và vòng đời ứng dụng `lifespan`, kết hợp middleware đếm `_in_flight_requests` để đợi các request đang chạy dở hoàn tất trong 30s trước khi ngắt ứng dụng.
   - **Stateless Design:** Lịch sử trò chuyện (`session_id`) và dữ liệu giới hạn tài nguyên đều được lưu tập trung ở Redis thay vì RAM, cho phép Load Balancer tự do phân bổ request đến bất kỳ instance nào mà không bị lỗi.
5. **Deployment:** Ứng dụng đã được tối ưu đóng gói bằng Dockerfile (Multi-stage build) và deploy thành công trên nền tảng đám mây.

**🔗 Link API truy cập thực tế:** `https://day12-ai-agent.onrender.com`
