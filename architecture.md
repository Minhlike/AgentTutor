# Quyết định thiết kế v1

1. **JSON cho dữ liệu có cấu trúc, Markdown cho điều hướng.** JSON dùng được với Python chuẩn, là YAML hợp lệ, tránh phụ thuộc parser. JSON Schema mô tả hợp đồng; CLI kiểm tra các ràng buộc liên file và snapshot.
2. **Một event cho một handoff được chấp nhận.** Handoff gốc nằm ở `handoffs/accepted/`; event là nguồn thay đổi; `state/snapshot.json` và `state/CURRENT.md` được dựng lại. Hash nội dung chuẩn hóa và ID chống xử lý lặp. Lịch sử chỉ thêm; sai sót được sửa bằng `CORRECTION`.
3. **Tiến độ và độ tin cậy tách nhau.** `status` mô tả kết quả học tập được báo cáo; `verification` mô tả mức xác minh. Nguồn ChatGPT không tự nâng mức xác minh. `VERIFIED`, `ASSESSED`, `COMPLETED` chỉ được ghi khi người xử lý đã có bằng chứng phù hợp và sự kiện xác minh riêng.
4. **Catalog nhỏ, mở rộng theo nhu cầu.** ID track, competency và milestone ổn định, phụ thuộc tường minh. Không tạo hàng loạt module khi chưa thảo luận. Quy tắc module nằm trong template.
5. **Cross-repo bằng tham chiếu.** Registry quản lý nhiều workspace; OpsLens code, PR và tài liệu sản phẩm vẫn thuộc OpsLens. Tham chiếu nên có URL, path và commit SHA khi biết.
6. **Không dịch nguyên giáo trình.** Danh mục trỏ tới nguồn chính thức; chỉ viết mô tả tiếng Việt và bài tập tự xây dựng sau khi thống nhất mục tiêu.

Giới hạn v1: CLI chạy cho một người vận hành và một nhánh Git; nếu có nhiều người cập nhật đồng thời, phải pull/merge và giải quyết xung đột trước khi ingest. Snapshot có thể tái tạo từ Git, nhưng Git không thay thế backup ngoài repo.
