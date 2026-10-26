import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import agenttutor as tutor


class AgentTutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[1]
        for name in ("catalog", "config", "history", "curriculum", "charter", "templates"):
            shutil.copytree(source / name, self.root / name)
        for name in ("README.md", "AGENTS.md", "architecture.md"):
            shutil.copy2(source / name, self.root / name)
        (self.root / "handoffs" / "accepted").mkdir(parents=True)
        self.old = {key: getattr(tutor, key) for key in ("ROOT", "SCHEMAS", "EVENTS", "ACCEPTED", "SNAPSHOT", "CURRENT", "NEXT")}
        tutor.ROOT = self.root
        tutor.SCHEMAS = self.root / "config" / "schemas"
        tutor.EVENTS = self.root / "history" / "events"
        tutor.ACCEPTED = self.root / "handoffs" / "accepted"
        tutor.SNAPSHOT = self.root / "state" / "snapshot.json"
        tutor.CURRENT = self.root / "state" / "CURRENT.md"
        tutor.NEXT = self.root / "state" / "NEXT.md"
        tutor.rebuild()

    def tearDown(self):
        for key, value in self.old.items():
            setattr(tutor, key, value)
        self.tmp.cleanup()

    def handoff(self, ident, status="IN_PROGRESS", summary="Kết quả checkpoint"):
        return {
            "schema_version": 1, "handoff_id": ident,
            "timestamp": "2026-10-27T10:00:00+07:00", "source": "chatgpt-primary-tutor",
            "track_id": "track-devops", "milestone_id": "ms-devops-s56",
            "status": status, "summary": summary, "evidence": [],
            "competencies": {"updated": []}, "decisions": [], "misconceptions": [],
            "open_issues": ["Chờ kiểm tra"], "next_action": "Kiểm tra bằng chứng."
        }

    def save(self, payload):
        path = self.root / "input.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_ingest_rebuild_and_duplicate_guard(self):
        payload = self.handoff("ho-test-checkpoint-1")
        with contextlib.redirect_stdout(io.StringIO()):
            tutor.ingest(self.save(payload))
            tutor.validate()
        state = tutor.rebuild(check=True)
        self.assertEqual(state["context"]["last_handoff_id"], payload["handoff_id"])
        self.assertEqual(state["entities"]["milestone"]["ms-devops-s56"]["verification"], "CLAIMED")
        with self.assertRaisesRegex(tutor.Invalid, "already accepted"):
            tutor.ingest(self.save(payload))
        payload["handoff_id"] = "ho-test-checkpoint-2"
        with self.assertRaisesRegex(tutor.Invalid, "Duplicate content"):
            tutor.ingest(self.save(payload))

    def test_completed_downgrade_requires_correction(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tutor.ingest(self.save(self.handoff("ho-test-complete-1", "COMPLETED", "Theo báo cáo đã hoàn thành")))
        with self.assertRaisesRegex(tutor.Invalid, "needs CORRECTION"):
            tutor.ingest(self.save(self.handoff("ho-test-downgrade-2", "IN_PROGRESS", "Yêu cầu mở lại")))

    def test_invalid_reference_and_snapshot_drift(self):
        payload = self.handoff("ho-test-invalid-1")
        payload["competencies"]["updated"] = [{"id": "comp-unknown", "status": "COMPLETED", "summary": "Không tồn tại"}]
        with self.assertRaisesRegex(tutor.Invalid, "Unknown competency"):
            tutor.ingest(self.save(payload))
        tutor.CURRENT.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(tutor.Invalid, "Snapshot drift"):
            tutor.validate()

    def test_handoff_tamper_is_detected(self):
        payload = self.handoff("ho-test-tamper-1")
        with contextlib.redirect_stdout(io.StringIO()):
            tutor.ingest(self.save(payload))
        accepted = tutor.ACCEPTED / "ho-test-tamper-1.json"
        changed = json.loads(accepted.read_text(encoding="utf-8"))
        changed["summary"] = "Modified after acceptance"
        accepted.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(tutor.Invalid, "payload changed"):
            tutor.validate()


if __name__ == "__main__":
    unittest.main()
