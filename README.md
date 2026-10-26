# AgentTutor

AgentTutor lưu **hồ sơ học tập có thể kiểm tra bằng Git**. ChatGPT Chat giảng dạy và đánh giá; người học quyết định. Agent này chỉ tiếp nhận bản bàn giao, kiểm tra, lưu sự kiện và dựng lại trạng thái. Độ bền dữ liệu phụ thuộc vào commit, push và bản sao lưu thành công.

## Bắt đầu một phiên học

Đọc [AGENTS.md](AGENTS.md), rồi [state/CURRENT.md](state/CURRENT.md). Mở [catalog/competencies.json](catalog/competencies.json) hoặc [catalog/milestones.json](catalog/milestones.json) khi cần tra ID. Không cần nạp toàn bộ repo.

## Sơ đồ dữ liệu

| Nơi lưu | Vai trò |
| --- | --- |
| `config/` | Registry workspace và JSON Schema |
| `charter/`, `curriculum/` | Nguyên tắc sư phạm, chương trình nháp và nguồn |
| `catalog/` | ID, phụ thuộc và tiêu chí năng lực/milestone |
| `history/events/` | Sự kiện được chấp nhận; sửa sai bằng sự kiện hiệu đính |
| `handoffs/accepted/` | Bản `TUTOR_SYNC` đã tiếp nhận |
| `state/` | Snapshot tái tạo được từ event, không phải nguồn lịch sử |
| `tools/` | CLI kiểm tra, tiếp nhận và tái tạo snapshot |

Không lưu transcript, mã nguồn OpsLens, bí mật hay dữ liệu riêng tư vào repo public.

## Tiếp nhận TUTOR_SYNC

ChatGPT tạo JSON theo [mẫu](templates/TUTOR_SYNC.json). JSON là một tập con hợp lệ của YAML, nên có thể đặt trong khối `TUTOR_SYNC` dễ sao chép. Lưu vào `handoffs/inbox/` (được Git bỏ qua), kiểm tra nội dung rồi chạy:

```powershell
python tools/agenttutor.py ingest handoffs/inbox/<file>.json
python tools/agenttutor.py validate
git diff --check
```

`ingest` kiểm tra schema, ID, trùng lặp và xung đột, lưu handoff/sự kiện rồi dựng lại snapshot. Thông tin từ ChatGPT luôn bắt đầu ở mức **CLAIMED**; `reported_verification` chỉ ghi lời báo cáo. Bằng chứng phải được kiểm tra riêng trước khi nâng mức xác minh. Nếu lệnh thất bại, không commit. Sau khi rà soát dữ liệu public và diff, commit rồi push; chỉ báo “đã đồng bộ” sau khi xác nhận remote trỏ tới commit mới.

Quyết định trong handoff cần `id`, `summary`, `rationale`, `tradeoffs`; sai lầm cần `id`, `summary`, `root_cause`, `remedy`. Mọi ID phải mới. Nếu một quyết định hoặc sai lầm cần sửa, dùng sự kiện hiệu đính thay vì tái sử dụng ID.

```powershell
python tools/agenttutor.py rebuild --check
git status --short
```

## Phạm vi

Chỉ chỉnh sửa repo này. `D:\opslendev` và các repo khác là nguồn tham chiếu, không được thay đổi. Đường dẫn local trong registry chỉ là metadata và không được ghi thành bằng chứng đã kiểm tra. Thiết kế chi tiết: [architecture.md](architecture.md).
