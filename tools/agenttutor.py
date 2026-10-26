#!/usr/bin/env python3
"""Small, dependency-free AgentTutor event store and validator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "config" / "schemas"
EVENTS = ROOT / "history" / "events"
ACCEPTED = ROOT / "handoffs" / "accepted"
SNAPSHOT = ROOT / "state" / "snapshot.json"
CURRENT = ROOT / "state" / "CURRENT.md"
NEXT = ROOT / "state" / "NEXT.md"
STATUSES = {"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETED"}
VERIFICATIONS = {"CLAIMED", "PRACTICED", "VERIFIED", "ASSESSED", "COMPLETED", "BLOCKED"}
ID_PATTERN = re.compile(r"^(?:ws|track|comp|ms|mod|assess|ev|ho|dec|mis|evt)-[a-z0-9][a-z0-9-]{1,79}$")


class Invalid(ValueError):
    pass


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Invalid(f"{path}: {exc}") from exc


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pretty(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Invalid(f"Invalid ISO-8601 timestamp: {value}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise Invalid(f"Timestamp lacks timezone: {value}")
    return result.astimezone(timezone.utc)


def schema_check(value, schema, where="$", base="handoff.schema.json"):
    """Validate the JSON Schema subset used by this repository."""
    if "$ref" in schema:
        ref = schema["$ref"]
        file_name, _, pointer = ref.partition("#")
        if not file_name:
            file_name = base
        target = read_json(SCHEMAS / file_name)
        for part in pointer.lstrip("/").split("/") if pointer else []:
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return schema_check(value, target, where, file_name)
    allowed = schema.get("type")
    if allowed:
        types = allowed if isinstance(allowed, list) else [allowed]
        tests = {
            "object": lambda x: isinstance(x, dict),
            "array": lambda x: isinstance(x, list),
            "string": lambda x: isinstance(x, str),
            "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
            "null": lambda x: x is None,
        }
        if not any(tests[t](value) for t in types):
            raise Invalid(f"{where}: expected {types}")
    if "const" in schema and value != schema["const"]:
        raise Invalid(f"{where}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise Invalid(f"{where}: invalid value {value!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise Invalid(f"{where}: missing {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise Invalid(f"{where}: unknown fields {sorted(unknown)}")
        for key, item in value.items():
            if key in properties:
                schema_check(item, properties[key], f"{where}.{key}", base)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            schema_check(item, schema["items"], f"{where}[{index}]", base)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10**9):
            raise Invalid(f"{where}: invalid length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise Invalid(f"{where}: invalid ID/pattern")
        if schema.get("format") == "date-time":
            timestamp(value)


def catalogs():
    tracks = read_json(ROOT / "catalog" / "tracks.json")
    comps = read_json(ROOT / "catalog" / "competencies.json")
    milestones = read_json(ROOT / "catalog" / "milestones.json")
    workspaces = read_json(ROOT / "config" / "workspaces.json")
    all_docs = [(tracks, "tracks", "track"), (comps, "competencies", "comp"),
                (milestones, "milestones", "ms"), (workspaces, "workspaces", "ws")]
    ids = set()
    for doc, field, prefix in all_docs:
        if doc.get("schema_version") != 1 or not isinstance(doc.get(field), list):
            raise Invalid(f"{field}: bad catalog envelope")
        for row in doc[field]:
            ident = row.get("id")
            if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident) or not ident.startswith(prefix + "-"):
                raise Invalid(f"{field}: invalid ID {ident!r}")
            if ident in ids:
                raise Invalid(f"Duplicate catalog ID {ident}")
            ids.add(ident)
    track_ids = {x["id"] for x in tracks["tracks"]}
    comp_ids = {x["id"] for x in comps["competencies"]}
    for row in comps["competencies"]:
        if row.get("track_id") not in track_ids:
            raise Invalid(f"Unknown track for {row['id']}")
        for prerequisite in row.get("prerequisites", []):
            if prerequisite not in comp_ids or prerequisite == row["id"]:
                raise Invalid(f"Invalid prerequisite {prerequisite} in {row['id']}")
    graph = {x["id"]: x.get("prerequisites", []) for x in comps["competencies"]}
    visiting, done = set(), set()
    def visit(ident):
        if ident in visiting:
            raise Invalid(f"Competency dependency cycle at {ident}")
        if ident in done:
            return
        visiting.add(ident)
        for prereq in graph[ident]:
            visit(prereq)
        visiting.remove(ident)
        done.add(ident)
    for ident in graph:
        visit(ident)
    for row in milestones["milestones"]:
        if row.get("track_id") not in track_ids or any(x not in comp_ids for x in row.get("competency_ids", [])):
            raise Invalid(f"Invalid milestone references in {row['id']}")
    for row in workspaces["workspaces"]:
        if not all(isinstance(row.get(k), str) and row[k] for k in ("name", "type", "local_path", "remote_url", "role", "source_of_truth", "sync_rule")):
            raise Invalid(f"Incomplete workspace {row['id']}")
        if urlparse(row["remote_url"]).scheme != "https" or not isinstance(row.get("permissions"), list):
            raise Invalid(f"Invalid workspace URL/permissions {row['id']}")
    return track_ids, comp_ids, {x["id"] for x in milestones["milestones"]}


def check_handoff(handoff, known):
    schema_check(handoff, read_json(SCHEMAS / "handoff.schema.json"))
    tracks, comps, milestones = known
    if handoff["track_id"] not in tracks or handoff["milestone_id"] not in milestones:
        raise Invalid("Handoff references unknown track/milestone")
    milestone = next(x for x in read_json(ROOT / "catalog" / "milestones.json")["milestones"] if x["id"] == handoff["milestone_id"])
    if milestone["track_id"] != handoff["track_id"]:
        raise Invalid("Handoff track disagrees with milestone")
    if len({x["id"] for x in handoff["competencies"]["updated"]}) != len(handoff["competencies"]["updated"]):
        raise Invalid("Duplicate competency in handoff")
    if any(x["id"] not in comps for x in handoff["competencies"]["updated"]):
        raise Invalid("Unknown competency in handoff")
    identifiers = [x["id"] for section in ("evidence", "decisions", "misconceptions") for x in handoff[section]]
    if len(identifiers) != len(set(identifiers)):
        raise Invalid("Duplicate evidence/decision/misconception ID in handoff")
    if any(x["id"].startswith("dec-") is False for x in handoff["decisions"]):
        raise Invalid("Decision ID must start dec-")
    if any(x["id"].startswith("mis-") is False for x in handoff["misconceptions"]):
        raise Invalid("Misconception ID must start mis-")


def event_files():
    if not EVENTS.exists():
        return []
    return sorted(EVENTS.glob("*.json"), key=lambda path: (timestamp(read_json(path)["timestamp"]), path.name))


def replay(events, known):
    tracks, comps, milestones = known
    state = {"schema_version": 1, "last_event_id": None,
             "entities": {"program": {}, "milestone": {}, "competency": {}},
             "context": {"last_handoff_id": None, "summary": "", "next_action": "", "open_issues": [], "decisions": [], "misconceptions": []}}
    seen_events, seen_handoffs, seen_payloads, seen_evidence, seen_notes = set(), set(), set(), set(), set()
    previous_time = None
    for event in events:
        schema_check(event, read_json(SCHEMAS / "event.schema.json"), base="event.schema.json")
        event_time = timestamp(event["timestamp"])
        if previous_time is not None and event_time < previous_time:
            raise Invalid(f"Events out of time order: {event['event_id']}")
        previous_time = event_time
        event_id = event["event_id"]
        if event_id in seen_events:
            raise Invalid(f"Duplicate event ID {event_id}")
        seen_events.add(event_id)
        if event["verification"] not in VERIFICATIONS:
            raise Invalid(f"Invalid verification in {event_id}")
        if event["type"] == "TUTOR_SYNC":
            handoff_id = event["handoff_id"]
            if handoff_id in seen_handoffs:
                raise Invalid(f"Duplicate handoff ID {handoff_id}")
            seen_handoffs.add(handoff_id)
            if event["payload_sha256"] in seen_payloads:
                raise Invalid(f"Duplicate handoff payload {handoff_id}")
            seen_payloads.add(event["payload_sha256"])
            if event["verification"] != "CLAIMED":
                raise Invalid(f"Tutor handoff cannot self-verify: {event_id}")
        elif event["verification"] not in ("CLAIMED", "BLOCKED") and not event["evidence"]:
            raise Invalid(f"Verified event needs evidence: {event_id}")
        if event["type"] == "CORRECTION":
            if event.get("corrects_event_id") not in seen_events or not event.get("reason"):
                raise Invalid(f"Correction needs previous event and reason: {event_id}")
        if event["type"] == "BASELINE" and (event["handoff_id"] is not None or event["payload_sha256"] is not None):
            raise Invalid("Baseline must not reference a handoff")
        actual_ids = [x["id"] for x in event["changes"]]
        if actual_ids != event["affected_entity_ids"] or len(actual_ids) != len(set(actual_ids)):
            raise Invalid(f"Affected IDs disagree or duplicate: {event_id}")
        for evidence in event["evidence"]:
            ident = evidence["id"]
            if ident in seen_evidence:
                raise Invalid(f"Duplicate evidence ID {ident}")
            seen_evidence.add(ident)
        for section in ("decisions", "misconceptions"):
            for note in event["context"].get(section, []):
                if note["id"] in seen_notes:
                    raise Invalid(f"Duplicate note ID {note['id']}")
                seen_notes.add(note["id"])
                state["context"][section].append(note)
        for change in event["changes"]:
            kind, ident = change["kind"], change["id"]
            if kind == "milestone" and ident not in milestones or kind == "competency" and ident not in comps or kind == "program" and ident != "program-devops":
                raise Invalid(f"Unknown entity {kind}/{ident}")
            current = state["entities"][kind].get(ident)
            if change["previous"] != current:
                raise Invalid(f"Previous state mismatch for {ident} in {event_id}")
            new = change["new"]
            if new.get("status") not in STATUSES or new.get("verification") not in VERIFICATIONS:
                raise Invalid(f"Invalid status/verification for {ident}")
            if event["type"] == "TUTOR_SYNC" and new["verification"] != "CLAIMED":
                raise Invalid(f"Tutor handoff cannot self-verify {ident}")
            if current and current["status"] == "COMPLETED" and new["status"] != "COMPLETED" and event["type"] != "CORRECTION":
                raise Invalid(f"Completed milestone/competency downgrade needs correction: {ident}")
            if any(eid not in seen_evidence for eid in new.get("evidence_ids", [])):
                raise Invalid(f"Unknown evidence for {ident}")
            state["entities"][kind][ident] = new
        if event["type"] == "TUTOR_SYNC":
            context = event["context"]
            state["context"].update({"last_handoff_id": event["handoff_id"],
                "summary": context["summary"], "next_action": context["next_action"],
                "open_issues": context["open_issues"]})
        elif event["type"] == "BASELINE":
            state["context"].update({"summary": event["context"]["summary"],
                "next_action": event["context"]["next_action"],
                "open_issues": event["context"]["open_issues"]})
        state["last_event_id"] = event_id
    return state


def render_current(state):
    lines = ["# Trạng thái hiện tại", "", "Bản dựng tự động từ `history/events/`; không sửa tay. `status` và `verification` là hai trục riêng.", "",
             f"Sự kiện cuối: `{state['last_event_id'] or 'none'}`. Handoff cuối: `{state['context']['last_handoff_id'] or 'none'}`.", "",
             "## Tóm tắt", "", state["context"]["summary"] or "Chưa có checkpoint.", ""]
    for kind, label in (("program", "Chương trình"), ("milestone", "Milestones"), ("competency", "Competencies")):
        lines.extend([f"## {label}", ""])
        items = state["entities"][kind]
        if not items:
            lines.append("Chưa có trạng thái được ghi nhận.")
        for ident, item in sorted(items.items()):
            lines.append(f"- `{ident}`: **{item['status']}**, xác minh **{item['verification']}** — {item['summary']}")
            if item.get("details"):
                for key, value in sorted(item["details"].items()):
                    lines.append(f"  - {key}: {value}")
        lines.append("")
    lines.extend(["## Vấn đề mở", ""])
    lines.extend([f"- {x}" for x in state["context"]["open_issues"]] or ["Chưa ghi nhận."])
    lines.extend(["", "## Quyết định sư phạm/kiến trúc đang ghi nhận", ""])
    lines.extend([f"- `{x['id']}`: {x['summary']} — Lý do: {x['rationale']}; đánh đổi: {x['tradeoffs']}" for x in state["context"]["decisions"]] or ["Chưa ghi nhận."])
    lines.extend(["", "## Sai lầm cần tránh lặp lại", ""])
    lines.extend([f"- `{x['id']}`: {x['summary']} — Nguyên nhân: {x['root_cause']}; cách khắc phục: {x['remedy']}" for x in state["context"]["misconceptions"]] or ["Chưa ghi nhận."])
    lines.extend(["", "## Bước tiếp theo", "", state["context"]["next_action"] or "Chọn năng lực kế tiếp cùng người học.", ""])
    return "\n".join(lines)


def render_next(state):
    return "# Bước tiếp theo\n\n" + (state["context"]["next_action"] or "Chọn năng lực kế tiếp cùng người học.") + "\n\nXem [CURRENT.md](CURRENT.md) để biết trạng thái và mức xác minh.\n"


def write_atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, prefix=".agenttutor-", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def rebuild(check=False):
    known = catalogs()
    events = [read_json(p) for p in event_files()]
    state = replay(events, known)
    outputs = {SNAPSHOT: pretty(state), CURRENT: render_current(state), NEXT: render_next(state)}
    if check:
        for path, expected in outputs.items():
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise Invalid(f"Snapshot drift: {path.relative_to(ROOT)}")
    else:
        for path, expected in outputs.items():
            write_atomic(path, expected)
    return state


def ingest(path: Path):
    known = catalogs()
    handoff = read_json(path)
    check_handoff(handoff, known)
    existing = [read_json(p) for p in event_files()]
    state = replay(existing, known)
    hid = handoff["handoff_id"]
    if (ACCEPTED / f"{hid}.json").exists() or any(x.get("handoff_id") == hid for x in existing):
        raise Invalid(f"Handoff ID already accepted: {hid}")
    semantic = {k: v for k, v in handoff.items() if k not in ("handoff_id", "timestamp")}
    for accepted_path in ACCEPTED.glob("*.json"):
        old = read_json(accepted_path)
        if semantic == {k: v for k, v in old.items() if k not in ("handoff_id", "timestamp")}:
            raise Invalid(f"Duplicate content of {accepted_path.stem}")
    used_ids = {item["id"] for event in existing for item in event["evidence"]}
    used_ids |= {item["id"] for event in existing for key in ("decisions", "misconceptions") for item in event["context"].get(key, [])}
    new_ids = {item["id"] for key in ("evidence", "decisions", "misconceptions") for item in handoff[key]}
    if used_ids & new_ids:
        raise Invalid(f"Previously used IDs: {sorted(used_ids & new_ids)}")
    event_id = "evt-" + hid.removeprefix("ho-")
    if any(x["event_id"] == event_id for x in existing):
        raise Invalid(f"Event ID exists: {event_id}")
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    evidence_ids = [x["id"] for x in handoff["evidence"]]
    changes = []
    entries = [("milestone", handoff["milestone_id"], handoff["status"], handoff["summary"])]
    entries += [("competency", x["id"], x["status"], x["summary"]) for x in handoff["competencies"]["updated"]]
    for kind, ident, status, summary in entries:
        previous = state["entities"][kind].get(ident)
        if previous and previous["status"] == "COMPLETED" and status != "COMPLETED":
            raise Invalid(f"Downgrade of completed {ident} needs CORRECTION")
        changes.append({"kind": kind, "id": ident, "previous": previous,
                        "new": {"status": status, "verification": "CLAIMED", "summary": summary,
                                "evidence_ids": evidence_ids, "updated_at": now}})
    event = {"schema_version": 1, "event_id": event_id, "timestamp": now,
             "source": "chatgpt-primary-tutor", "type": "TUTOR_SYNC", "handoff_id": hid,
             "payload_sha256": digest(handoff), "affected_entity_ids": [x["id"] for x in changes],
             "changes": changes, "evidence": handoff["evidence"], "verification": "CLAIMED",
             "outcome": "accepted-as-claim", "context": {"summary": handoff["summary"],
                 "next_action": handoff["next_action"], "open_issues": handoff["open_issues"],
                 "decisions": handoff["decisions"], "misconceptions": handoff["misconceptions"],
                 "source_timestamp": handoff["timestamp"]}}
    replay(existing + [event], known)
    accepted_path, event_path = ACCEPTED / f"{hid}.json", EVENTS / f"{event_id}.json"
    try:
        write_atomic(accepted_path, pretty(handoff))
        write_atomic(event_path, pretty(event))
        rebuild()
        validate()
    except Exception:
        accepted_path.unlink(missing_ok=True)
        event_path.unlink(missing_ok=True)
        rebuild()
        raise
    print(f"Accepted {hid}; event {event_id}; verification CLAIMED")


def validate():
    known = catalogs()
    for schema_path in SCHEMAS.glob("*.json"):
        schema = read_json(schema_path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise Invalid(f"Invalid schema declaration: {schema_path}")
    events = [read_json(p) for p in event_files()]
    for path, event in zip(event_files(), events):
        if path.stem != event["event_id"]:
            raise Invalid(f"Event filename disagrees with ID: {path}")
    replay(events, known)
    event_handoffs = {x["handoff_id"]: x for x in events if x["type"] == "TUTOR_SYNC"}
    accepted_ids = set()
    for path in ACCEPTED.glob("*.json"):
        handoff = read_json(path)
        check_handoff(handoff, known)
        ident = handoff["handoff_id"]
        if path.stem != ident or ident not in event_handoffs:
            raise Invalid(f"Orphan/misnamed accepted handoff: {path}")
        if digest(handoff) != event_handoffs[ident]["payload_sha256"]:
            raise Invalid(f"Handoff payload changed after acceptance: {ident}")
        accepted_ids.add(ident)
    if accepted_ids != set(event_handoffs):
        raise Invalid("Some event handoffs lack accepted payloads")
    semantic_hashes = set()
    for path in ACCEPTED.glob("*.json"):
        payload = read_json(path)
        semantic_hash = digest({k: v for k, v in payload.items() if k not in ("handoff_id", "timestamp")})
        if semantic_hash in semantic_hashes:
            raise Invalid("Duplicate accepted handoff content")
        semantic_hashes.add(semantic_hash)
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        body = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", body):
            if target.startswith(("http://", "https://", "#")):
                continue
            local = target.split("#", 1)[0]
            if local and not (path.parent / local).exists():
                raise Invalid(f"Broken Markdown link in {path.relative_to(ROOT)}: {target}")
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "inbox" in path.parts or path.suffix not in (".md", ".json", ".py", ".txt"):
            continue
        body = path.read_text(encoding="utf-8")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}", body):
            raise Invalid(f"Possible secret in {path.relative_to(ROOT)}")
    rebuild(check=True)
    print(f"OK: {len(events)} events, {len(accepted_ids)} handoffs; schemas, IDs, references, links, secrets and snapshot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("rebuild", help="Regenerate current state")
    command.add_argument("--check", action="store_true", help="Fail on drift without writing")
    command = sub.add_parser("ingest", help="Accept one TUTOR_SYNC JSON")
    command.add_argument("path", type=Path)
    sub.add_parser("validate", help="Validate repository and snapshot")
    args = parser.parse_args()
    try:
        if args.command == "rebuild":
            rebuild(check=args.check)
            print("Snapshot matches events" if args.check else "Snapshot rebuilt")
        elif args.command == "ingest":
            ingest(args.path)
        else:
            validate()
    except Invalid as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
