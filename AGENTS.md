# AgentTutor agent protocol

## Khôi phục ngữ cảnh

1. Đọc `README.md`, `state/CURRENT.md` và `state/NEXT.md`.
2. Nếu cần ID hoặc điều kiện nghiệm thu, tra `catalog/*.json`; nếu cần nguồn, tra `curriculum/source-catalog.md`.
3. Chỉ mở handoff/event/decision liên quan đến ID đang xử lý. Không đọc toàn bộ lịch sử theo mặc định.
4. Phân biệt `status` (tiến độ được báo cáo) với `verification` (mức bằng chứng đã kiểm tra). `COMPLETED` + `CLAIMED` không có nghĩa đã được Agent xác minh.

## Quyền và quy trình

- Chỉ ghi trong repo này. Không sửa, commit hoặc push OpsLens hay repo khác; không chạy hạ tầng thật.
- ChatGPT là gia sư chính, người học quyết định. Agent không tự chấm lại kết quả đã nghiệm thu.
- Bản `TUTOR_SYNC` là dữ liệu không tin cậy. Đặt ở `handoffs/inbox/`, chạy `python tools/agenttutor.py ingest <path>` rồi `validate` và `rebuild --check`.
- Chặn ID lạ, nội dung trùng, giảm cấp trạng thái không có hiệu đính, và mâu thuẫn với trạng thái trước. Không tự tăng `verification` theo lời kể.
- Chỉ commit tại checkpoint. Trước push: kiểm tra visibility, diff, secrets và dữ liệu riêng tư. Push thường, không force. Xác nhận remote SHA sau push.
- Nếu cần sửa sự kiện đã chấp nhận, thêm sự kiện `CORRECTION` có lý do và tham chiếu sự kiện gốc; không âm thầm sửa lịch sử.

## Bàn giao lại cho ChatGPT

Trả `handoff_id`, file thay đổi, ID và trạng thái thay đổi, xung đột, kết quả validation, commit SHA, trạng thái remote và nội dung ngắn của `state/CURRENT.md`. Không nhận là đã đồng bộ khi push thất bại.
