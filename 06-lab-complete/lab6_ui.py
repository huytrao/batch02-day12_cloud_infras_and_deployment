import streamlit as st
import requests
import uuid

st.set_page_config(page_title="Production AI Agent", page_icon="🤖")

st.title("🤖 Production AI Agent (Lab 6)")
st.caption("Giao diện UI tương tác với Backend chuẩn Production (Bảo mật, Rate Limit, Cost Guard, Stateless)")

# Sidebar Settings
st.sidebar.header("⚙️ Cấu hình Kết nối")
api_key = st.sidebar.text_input("🔑 API Key", type="password", value="your-secret-api-key")

# Tạo ngẫu nhiên 1 session_id cho mỗi người dùng hoặc cho phép nhập
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
session_id = st.sidebar.text_input("🆔 Session ID", value=st.session_state.session_id)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Thông số Request Gần Nhất")
metrics_placeholder = st.sidebar.empty()

# Lịch sử chat
if "messages" not in st.session_state:
    st.session_state.messages = []

# Nút Xóa lịch sử (để test stateless)
if st.sidebar.button("🗑️ Xóa lịch sử (UI)"):
    st.session_state.messages = []
    st.rerun()
    
st.sidebar.info("💡 Lưu ý: Lịch sử trên Backend thực chất được lưu bằng Redis theo `Session ID`. Xóa lịch sử UI không làm mất lịch sử ở Redis.")

# Hiển thị tin nhắn
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Input người dùng
if prompt := st.chat_input("Nhập câu hỏi (VD: Xin chào, bạn tên gì?)..."):
    # Thêm câu hỏi vào UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Gửi request lên Backend
    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý (có thể trễ vài giây để test Graceful Shutdown)..."):
            try:
                response = requests.post(
                    "http://127.0.0.1:8000/ask",
                    headers={"X-API-Key": api_key},
                    json={"question": prompt, "session_id": session_id}
                )
                
                # Xử lý Response
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "Không có câu trả lời")
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    
                    # Update Metrics
                    with metrics_placeholder.container():
                        st.success("✅ Thành công")
                        st.write(f"**Tokens sử dụng:** {response.headers.get('x-tokens-used', 0)}")
                        st.write(f"**Chi phí LLM:** ${response.headers.get('x-cost-usd', '0.00')}")
                        st.write(f"**Rate Limit còn lại:** {response.headers.get('x-ratelimit-remaining', 'N/A')}/10 (phút)")
                        
                elif response.status_code == 429:
                    st.error("⚠️ Bạn đã thao tác quá nhanh! (Bị chặn bởi Rate Limiter - 10 req/min)")
                elif response.status_code == 402:
                    st.error("💸 Bạn đã sử dụng hết ngân sách tháng này! (Bị chặn bởi Cost Guard)")
                elif response.status_code == 401:
                    st.error("🔒 Sai API Key! Backend từ chối truy cập.")
                else:
                    st.error(f"Lỗi {response.status_code}: {response.text}")
                    
            except requests.exceptions.ConnectionError:
                st.error("🔌 Không thể kết nối! Hãy chắc chắn bạn đã chạy Backend (FastAPI) ở cổng 8000.")
