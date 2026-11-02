"""Evidence-backed work state. Model interpretations never change state unreviewed."""

import hashlib
import json
import sqlite3
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .store import Store, _canonical, _now, _required
from .attribution import model_attribution_block
from .evidence_quality import model_evidence_block


ATTRIBUTIONS = {"user", "involved", "other", "ambient", "uncertain"}
KINDS = {"decision", "commitment", "deliverable", "question", "reference"}


def fingerprint(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class Workspace(Store):
    """Local single-user workspace, not a commercial tenant/authentication boundary."""

    def __init__(self, path):
        super().__init__(path)
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS claim_contexts (claim_id TEXT PRIMARY KEY REFERENCES claims(id), category TEXT NOT NULL, basis TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS project_settings (
                project_id TEXT PRIMARY KEY REFERENCES projects(id),
                priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5)
            );
            CREATE TABLE IF NOT EXISTS evidence_records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, external_id TEXT NOT NULL,
                content TEXT NOT NULL, content_hash TEXT NOT NULL,
                captured_at TEXT, source_uri TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(kind, external_id, content_hash)
            );
            CREATE TABLE IF NOT EXISTS project_records (
                project_id TEXT NOT NULL REFERENCES projects(id),
                record_id TEXT NOT NULL REFERENCES evidence_records(id),
                PRIMARY KEY(project_id, record_id)
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                record_id TEXT NOT NULL REFERENCES evidence_records(id),
                start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                payload TEXT NOT NULL, proposer TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(project_id, record_id) REFERENCES project_records(project_id, record_id)
            );
            CREATE TABLE IF NOT EXISTS claim_reviews (
                claim_id TEXT PRIMARY KEY REFERENCES claims(id),
                decision TEXT NOT NULL CHECK(decision IN ('accepted', 'rejected')),
                supersedes TEXT REFERENCES claims(id),
                actor TEXT NOT NULL, reviewed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id TEXT PRIMARY KEY, as_of TEXT NOT NULL, report TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dependencies (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                blocked_key TEXT NOT NULL, prerequisite_key TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                CHECK(blocked_key != prerequisite_key),
                UNIQUE(project_id, blocked_key, prerequisite_key)
            );
            CREATE TABLE IF NOT EXISTS dependency_events (
                id TEXT PRIMARY KEY, dependency_id TEXT NOT NULL REFERENCES dependencies(id),
                record_id TEXT NOT NULL REFERENCES evidence_records(id),
                operation TEXT NOT NULL CHECK(operation IN ('add', 'remove')),
                actor TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interpretation_modes (
                project_id TEXT NOT NULL, record_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('mixed', 'reference', 'work')),
                PRIMARY KEY(project_id, record_id),
                FOREIGN KEY(project_id, record_id) REFERENCES project_records(project_id, record_id)
            );
            PRAGMA user_version = 4;
            COMMIT;
        """)

    def create_project(self, name: str, priority: int = 3) -> str:
        if type(priority) is not int or not 1 <= priority <= 5:
            raise ValueError("Priority must be between 1 (highest) and 5")
        project_id = fingerprint({"name": _required(name).strip().casefold()})
        with self.db:
            self.db.execute("INSERT INTO projects VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                            (project_id, name.strip(), _now()))
            self.db.execute("INSERT INTO project_settings VALUES (?, ?) "
                            "ON CONFLICT(project_id) DO NOTHING", (project_id, priority))
        return project_id

    def set_priority(self, project_id: str, priority: int):
        if type(priority) is not int or not 1 <= priority <= 5:
            raise ValueError("Priority must be between 1 and 5")
        if not self.db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise KeyError(project_id)
        with self.db:
            self.db.execute("INSERT INTO project_settings VALUES (?, ?) "
                            "ON CONFLICT(project_id) DO UPDATE SET priority=excluded.priority",
                            (project_id, priority))

    def import_text(self, project_ids: list[str], *, kind: str, external_id: str,
                    content: str, captured_at: str | None = None, source_uri: str = "") -> str:
        if not project_ids:
            raise ValueError("Choose at least one project")
        if kind not in {"text", "chatgpt", "claude", "transcript", "bee_export", "email_export"}:
            raise ValueError("Unsupported import kind")
        _required(external_id)
        _required(content)
        if len(content) > 200_000:
            raise ValueError("Import up to 200,000 characters per record")
        if captured_at:
            stamp = datetime.fromisoformat(captured_at)
            if stamp.tzinfo is None:
                raise ValueError("Capture time must include a timezone")
            captured_at = stamp.astimezone(timezone.utc).isoformat()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        record_id = fingerprint({"kind": kind, "external_id": external_id, "hash": digest})
        with self.db:
            previous = self.db.execute("SELECT * FROM evidence_records WHERE id=?",
                                       (record_id,)).fetchone()
            if previous and (previous["captured_at"] != captured_at or
                             previous["source_uri"] != source_uri):
                raise ValueError("Existing record has different metadata; use a new source ID")
            self.db.execute("INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(id) DO NOTHING",
                            (record_id, kind, external_id, content, digest,
                             captured_at, source_uri, _now()))
            for project_id in set(project_ids):
                self.db.execute("INSERT INTO project_records VALUES (?, ?) "
                                "ON CONFLICT DO NOTHING", (project_id, record_id))
        return record_id

    def record(self, record_id: str) -> dict:
        row = self.db.execute("SELECT * FROM evidence_records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        result = dict(row)
        result["interpretation_modes"] = {r[0]: r[1] for r in self.db.execute(
            "SELECT project_id, mode FROM interpretation_modes WHERE record_id=?", (record_id,))}
        return result

    def source_mode(self, project_id: str, record_id: str, mode: str | None = None) -> str:
        if mode is not None:
            if mode not in {"mixed", "reference", "work"}:
                raise ValueError("Choose a source interpretation mode")
            with self.db:
                self.db.execute("INSERT INTO interpretation_modes VALUES (?, ?, ?) "
                                "ON CONFLICT(project_id, record_id) DO UPDATE SET mode=excluded.mode",
                                (project_id, record_id, mode))
        row = self.db.execute("SELECT mode FROM interpretation_modes WHERE project_id=? AND record_id=?",
                              (project_id, record_id)).fetchone()
        return row[0] if row else "mixed"

    def propose_claim(self, project_id: str, record_id: str, *, start: int, end: int,
                      kind: str, subject: str, value: str, attribution: str,
                      owner: str = "unknown", state: str = "planned",
                      due_date: str | None = None, date_basis: str = "unknown",
                      confidence: float | None = None, proposer: str = "manual") -> str:
        record = self.record(record_id)
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(record["content"]):
            raise ValueError("Select an exact, nonempty evidence span")
        if kind not in KINDS or attribution not in ATTRIBUTIONS:
            raise ValueError("Invalid claim kind or attribution")
        if state not in {"planned", "in_progress", "blocked", "done"}:
            raise ValueError("Invalid work state")
        if date_basis not in {"unknown", "tentative", "verified"}:
            raise ValueError("Invalid date basis")
        if due_date:
            if date.fromisoformat(due_date).isoformat() != due_date:
                raise ValueError("Use YYYY-MM-DD for dates")
            if date_basis == "unknown":
                raise ValueError("A supplied date must be tentative or verified")
        elif date_basis != "unknown":
            raise ValueError("A date basis requires a date")
        if confidence is not None and (type(confidence) not in (int, float) or
                                       not 0 <= confidence <= 1):
            raise ValueError("Confidence must be between zero and one")
        payload = {"kind": kind, "subject": _required(subject).strip(),
                   "value": _required(value).strip(), "attribution": attribution,
                   "owner": _required(owner).strip(), "state": state, "due_date": due_date,
                   "date_basis": date_basis, "confidence": confidence}
        if kind == "reference" and (owner != "unknown" or state != "planned" or due_date):
            raise ValueError("Reference material has no work owner, status, or deadline")
        claim_id = fingerprint({"project": project_id, "record": record_id,
                                "start": start, "end": end, "payload": payload})
        with self.db:
            self.db.execute("INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(id) DO NOTHING",
                            (claim_id, project_id, record_id, start, end,
                             _canonical(payload), _required(proposer), _now()))
        return claim_id

    def claims(self, project_id: str | None = None) -> list[dict]:
        sql = ("SELECT c.*, r.decision, r.supersedes, r.actor, r.reviewed_at, "
               "e.content, e.external_id, e.captured_at, x.category context_category, x.basis context_basis FROM claims c "
               "JOIN evidence_records e ON e.id=c.record_id "
               "LEFT JOIN claim_reviews r ON r.claim_id=c.id LEFT JOIN claim_contexts x ON x.claim_id=c.id")
        args = ()
        if project_id is not None:
            sql += " WHERE c.project_id=?"
            args = (project_id,)
        result = []
        for row in self.db.execute(sql + " ORDER BY c.created_at, c.id", args):
            item = dict(row)
            item.update(json.loads(item.pop("payload")))
            content = item.pop("content")
            item["quote"] = content[item["start_offset"]:item["end_offset"]]
            item["review_block_reason"] = model_attribution_block(
                item, item['proposer'], content, item['start_offset'], item['end_offset'])
            item["reference_block_reason"] = model_evidence_block(
                {**item, 'kind': 'reference'}, item['proposer'], item['quote'])
            item["review"] = item.pop("decision") or "pending"
            result.append(item)
        return result

    def review_claim(self, claim_id: str, *, decision: str, actor: str,
                      supersedes: str | None = None):
        if decision not in {"accepted", "rejected"}:
            raise ValueError("Choose accepted or rejected")
        _required(actor)
        # IMMEDIATE serializes competing reviews and replacement decisions.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            payload = json.loads(row["payload"])
            if supersedes and decision != "accepted":
                raise ValueError("Only an accepted claim may supersede a prior claim")
            if decision == "accepted":
                source = self.record(row['record_id'])
                block = model_attribution_block(payload, row['proposer'], source['content'],
                                                row['start_offset'], row['end_offset'])
                if block:
                    raise ValueError(block)
                if payload["kind"] != "reference" and payload["attribution"] in {"ambient", "uncertain"}:
                    raise ValueError("Ambient or uncertain attribution cannot establish work state")
                if payload["kind"] != "reference" and payload["owner"].casefold() == "user" and payload["attribution"] != "user":
                    raise ValueError("A personal commitment needs explicit user attribution")
                if payload["kind"] in {"commitment", "deliverable"} and payload["owner"].casefold() == "unknown":
                    raise ValueError("Identify the owner before accepting a work item")
                if supersedes:
                    old = self.db.execute(
                        "SELECT c.*, r.decision FROM claims c JOIN claim_reviews r ON r.claim_id=c.id "
                        "WHERE c.id=?", (supersedes,)).fetchone()
                    if old is None or old["decision"] != "accepted" or old["project_id"] != row["project_id"]:
                        raise ValueError("Replacement must reference accepted evidence in this project")
                    old_payload = json.loads(old["payload"])
                    if any(old_payload[k].casefold() != payload[k].casefold() for k in ("kind", "subject")):
                        raise ValueError("Replacement must describe the same kind and subject")
                    if self.db.execute("SELECT 1 FROM claim_reviews WHERE supersedes=?",
                                       (supersedes,)).fetchone():
                        raise ValueError("That claim was already replaced; inspect the current state")
            self.db.execute("INSERT INTO claim_reviews VALUES (?, ?, ?, ?, ?)",
                            (claim_id, decision, supersedes, actor, _now()))

    def keep_as_reference(self, claim_id: str, *, actor: str = "local-user") -> str:
        """Save source material without asserting a personal fact or work obligation.

        Conversion and rejection of the original pending interpretation are atomic.
        Attribution, exact source span, and the original interpretation are retained.
        """
        _required(actor)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT c.*, r.decision FROM claims c LEFT JOIN claim_reviews r "
                                  "ON r.claim_id=c.id WHERE c.id=?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            payload = json.loads(row["payload"])
            payload.update(kind="reference", owner="unknown", state="planned",
                           due_date=None, date_basis="unknown")
            block = model_evidence_block(payload, row['proposer'],
                                         self.record(row['record_id'])['content'][row['start_offset']:row['end_offset']])
            if block:
                raise ValueError(block)
            reference_id = fingerprint({"project": row["project_id"], "record": row["record_id"],
                                        "start": row["start_offset"], "end": row["end_offset"],
                                        "payload": payload})
            reviewed = self.db.execute("SELECT decision FROM claim_reviews WHERE claim_id=?",
                                       (reference_id,)).fetchone()
            if row["decision"] is not None:
                if reviewed is not None and reviewed[0] == "accepted" and row["decision"] == "rejected":
                    return reference_id
                raise ValueError("Only pending interpretations can be kept as reference")
            if reviewed is not None and reviewed[0] != "accepted":
                raise ValueError("This reference was already rejected; create a corrected interpretation")
            stamp = _now()
            self.db.execute("INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                            (reference_id, row["project_id"], row["record_id"],
                             row["start_offset"], row["end_offset"], _canonical(payload),
                             "user-reference-review", stamp))
            self.db.execute('INSERT OR IGNORE INTO claim_contexts SELECT ?,category,basis FROM claim_contexts WHERE claim_id=?', (reference_id,claim_id))
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='subject_members'").fetchone():
                self.db.execute('INSERT OR IGNORE INTO subject_members SELECT ?,folder_id,basis FROM subject_members WHERE claim_id=?',(reference_id,claim_id))
            if reference_id != claim_id:
                self.db.execute("INSERT INTO claim_reviews VALUES (?, ?, ?, ?, ?)",
                                (claim_id, "rejected", None, actor, stamp))
            if reviewed is None:
                self.db.execute("INSERT INTO claim_reviews VALUES (?, ?, ?, ?, ?)",
                                (reference_id, "accepted", None, actor, stamp))
        return reference_id

    @staticmethod
    def work_key(claim: dict) -> str:
        return _canonical({"kind": claim["kind"], "subject": claim["subject"].strip().casefold()})

    @staticmethod
    def current_state(claims: list[dict]) -> tuple[list, list]:
        accepted = [c for c in claims if c["review"] == "accepted"]
        superseded = {c["supersedes"] for c in accepted if c["supersedes"]}
        grouped = {}
        for claim in accepted:
            if claim["id"] not in superseded:
                if claim["kind"] == "reference":
                    # Independent learning notes on one topic are not competing decisions.
                    continue
                grouped.setdefault((claim["kind"], claim["subject"].casefold()), []).append(claim)
        current = [c for c in accepted if c["kind"] == "reference" and c["id"] not in superseded]
        conflicts = []
        for (kind, subject), candidates in grouped.items():
            meanings = {fingerprint({k: c[k] for k in
                        ("value", "owner", "state", "due_date", "date_basis")}) for c in candidates}
            if len(meanings) > 1:
                conflicts.append({"kind": kind, "subject": subject, "claims": candidates})
            else:
                current.append(candidates[-1])
        return current, conflicts

    def set_dependency(self, project_id: str, blocked_claim_id: str,
                       prerequisite_claim_id: str, *, active: bool = True,
                       reason: str, actor: str = "local-user") -> str:
        """Record a deliberate user instruction, including an auditable source record.

        Stable work keys follow later claim supersession; cycles and stale targets
        are rejected. A dependency does not auto-complete either deliverable.
        """
        _required(reason)
        _required(actor)
        if type(active) is not bool:
            raise ValueError("Dependency active state must be true or false")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            current, _ = self.current_state(self.claims(project_id))
            by_id = {c["id"]: c for c in current if c["kind"] in {"commitment", "deliverable"}}
            if blocked_claim_id not in by_id or prerequisite_claim_id not in by_id:
                raise ValueError("Choose current, reviewed work items from the same project")
            blocked, prerequisite = by_id[blocked_claim_id], by_id[prerequisite_claim_id]
            blocked_key, prerequisite_key = self.work_key(blocked), self.work_key(prerequisite)
            if blocked_key == prerequisite_key:
                raise ValueError("A work item cannot depend on itself")
            edge_id = fingerprint({"project": project_id, "blocked": blocked_key,
                                   "prerequisite": prerequisite_key})
            existing = self.db.execute("SELECT active FROM dependencies WHERE id=?", (edge_id,)).fetchone()
            if existing is not None and bool(existing[0]) == active:
                return edge_id
            if existing is None and not active:
                raise ValueError("This dependency does not exist")
            if active:
                graph = {}
                for row in self.db.execute(
                        "SELECT * FROM dependencies WHERE project_id=? AND active=1", (project_id,)):
                    graph.setdefault(row["blocked_key"], []).append(row["prerequisite_key"])
                stack, seen = [prerequisite_key], set()
                while stack:
                    node = stack.pop()
                    if node == blocked_key:
                        raise ValueError("That dependency would create a cycle")
                    if node not in seen:
                        seen.add(node)
                        stack.extend(graph.get(node, []))
            self.db.execute("INSERT INTO dependencies VALUES (?, ?, ?, ?, ?) "
                            "ON CONFLICT(id) DO UPDATE SET active=excluded.active",
                            (edge_id, project_id, blocked_key, prerequisite_key, int(active)))
            self._dependency_event(edge_id, project_id, blocked["subject"], prerequisite["subject"],
                                   "add" if active else "remove", reason, actor)
        return edge_id

    def _dependency_event(self, edge_id, project_id, blocked, prerequisite, operation, reason, actor):
        content = (f'User instruction: {operation} dependency. {blocked} '
                   f'{"must wait for" if operation == "add" else "no longer waits for"} '
                   f'{prerequisite}. Reason: {reason.strip()}')
        record_id = uuid.uuid4().hex
        stamp = _now()
        self.db.execute("INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (record_id, "text", f"Dependency update · {stamp} · {record_id[:6]}", content,
                         hashlib.sha256(content.encode()).hexdigest(), stamp, "", stamp))
        self.db.execute("INSERT INTO project_records VALUES (?, ?)", (project_id, record_id))
        self.db.execute("INSERT INTO dependency_events VALUES (?, ?, ?, ?, ?, ?)",
                        (uuid.uuid4().hex, edge_id, record_id, operation, actor, stamp))

    def remove_dependency(self, dependency_id: str, *, reason: str, actor: str = "local-user"):
        """Allow removal even if a prerequisite's current state is now conflicted."""
        _required(reason)
        _required(actor)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            edge = self.db.execute("SELECT * FROM dependencies WHERE id=?", (dependency_id,)).fetchone()
            if edge is None:
                raise KeyError(dependency_id)
            if not edge["active"]:
                return
            self.db.execute("UPDATE dependencies SET active=0 WHERE id=?", (dependency_id,))
            self._dependency_event(dependency_id, edge["project_id"],
                                   json.loads(edge["blocked_key"])["subject"],
                                   json.loads(edge["prerequisite_key"])["subject"],
                                   "remove", reason, actor)

    def backup_bytes(self) -> bytes:
        """A consistent SQLite backup, including evidence. It is not device sync."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lima-workspace.sqlite3"
            destination = sqlite3.connect(path)
            try:
                self.db.backup(destination)
            finally:
                destination.close()
            return path.read_bytes()

    def update_work(self, claim_id: str, *, state: str, reason: str,
                    actor: str = "local-user") -> str:
        """An explicit user status update is evidence, never a silent row overwrite."""
        if state not in {"planned", "in_progress", "blocked", "done"}:
            raise ValueError("Invalid work state")
        _required(reason)
        _required(actor)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT project_id FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            project_id = row["project_id"]
            current, _ = self.current_state(self.claims(project_id))
            old = next((c for c in current if c["id"] == claim_id and
                        c["kind"] in {"deliverable", "commitment"}), None)
            if old is None:
                raise ValueError("This work item changed; refresh and review the current state")
            if old["state"] == state:
                return old["id"]
            record_id = uuid.uuid4().hex
            stamp = _now()
            content = f'User status update: {old["subject"]} is {state}. Reason: {reason.strip()}'
            payload = {k: old[k] for k in ("kind", "subject", "value", "owner", "due_date", "date_basis")}
            payload.update(state=state, attribution="user", confidence=None)
            new_id = fingerprint({"project": project_id, "record": record_id,
                                  "start": 0, "end": len(content), "payload": payload})
            self.db.execute("INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (record_id, "text", f"Work status · {old['subject']} · {stamp}", content,
                             hashlib.sha256(content.encode()).hexdigest(), stamp, "", stamp))
            self.db.execute("INSERT INTO project_records VALUES (?, ?)", (project_id, record_id))
            self.db.execute("INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (new_id, project_id, record_id, 0, len(content), _canonical(payload),
                             "user-status-update", stamp))
            self.db.execute("INSERT INTO claim_reviews VALUES (?, ?, ?, ?, ?)",
                            (new_id, "accepted", claim_id, actor, stamp))
        return new_id

    def reconcile(self, *, as_of: str | None = None, persist: bool = True) -> dict:
        """Purely derived work state; repeated inputs/date produce one persisted run."""
        today = date.fromisoformat(as_of) if as_of else datetime.now().astimezone().date()
        all_claims = self.claims()
        projects = [dict(row) for row in self.db.execute(
            "SELECT p.*, COALESCE(s.priority, 3) priority FROM projects p "
            "LEFT JOIN project_settings s ON s.project_id=p.id ORDER BY priority, name")]
        result = {"as_of": today.isoformat(), "projects": [], "collisions": []}
        deadlines = {}
        for project in projects:
            claims = [c for c in all_claims if c["project_id"] == project["id"]]
            accepted = [c for c in claims if c["review"] == "accepted"]
            current, conflicts = self.current_state(claims)
            work = [c for c in current if c["kind"] in {"commitment", "deliverable"} and c["state"] != "done"]
            dependencies = [dict(row) for row in self.db.execute(
                "SELECT * FROM dependencies WHERE project_id=? AND active=1 ORDER BY id", (project["id"],))]
            work_by_key = {self.work_key(c): c for c in current if c["kind"] in {"commitment", "deliverable"}}
            for item in work:
                item["waiting_on"] = []
                for edge in dependencies:
                    if edge["blocked_key"] == self.work_key(item):
                        prerequisite = work_by_key.get(edge["prerequisite_key"])
                        if prerequisite is None or prerequisite["state"] != "done":
                            key_data = json.loads(edge["prerequisite_key"])
                            item["waiting_on"].append({"dependency_id": edge["id"],
                                "subject": prerequisite["subject"] if prerequisite else key_data["subject"],
                                "unresolved": prerequisite is None})
                item["ready"] = not item["waiting_on"] and item["state"] != "blocked"
            def rank(claim):
                verified = claim["date_basis"] == "verified"
                return (not claim["ready"], claim["due_date"] if verified else "9999-12-31",
                        claim["subject"].casefold())
            work.sort(key=rank)
            questions = [f'Resolve conflicting {c["kind"]}: {c["subject"]}.' for c in conflicts]
            questions.extend(c["value"] for c in current if c["kind"] == "question" and c["state"] != "done")
            for item in work:
                if item["date_basis"] != "verified":
                    questions.append(f'Confirm a deadline for {item["subject"]}.')
                else:
                    deadlines.setdefault(item["due_date"], []).append(
                        {"project_id": project["id"], "project": project["name"], "subject": item["subject"]})
                if item["state"] == "blocked":
                    questions.append(f'Unblock {item["subject"]}: {item["value"]}')
                if item["waiting_on"]:
                    names = ", ".join(p["subject"] for p in item["waiting_on"])
                    questions.append(f'{item["subject"]} is waiting for {names}.')
            overdue = [c for c in work if c["date_basis"] == "verified" and c["due_date"] < today.isoformat()]
            stale = bool(work) and bool(accepted) and (
                today - max(date.fromisoformat(c["reviewed_at"][:10]) for c in accepted)).days >= 7
            if stale:
                questions.append("No reviewed work update for at least seven days; confirm project status.")
            checklist = [{"claim_id": c["id"], "text": f'{c["subject"]}: {c["value"]}',
                          "record_id": c["record_id"], "quote": c["quote"],
                          "ready": c["ready"], "waiting_on": c["waiting_on"]} for c in work]
            report = {**project, "current": current, "history": claims,
                      "pending_count": sum(c["review"] == "pending" for c in claims),
                      "conflicts": conflicts, "work": work, "questions": questions,
                      "references": [c for c in current if c["kind"] == "reference"],
                      "overdue_count": len(overdue), "stale": stale,
                      "dependencies": dependencies,
                      "draft": {"kind": "local_checklist", "status": "prepared",
                                "items": checklist, "external_execution": False}}
            result["projects"].append(report)
        result["collisions"] = [{"date": day, "items": items} for day, items in sorted(deadlines.items())
                                if len(items) > 1]
        result["id"] = fingerprint(result)
        if persist:
            with self.db:
                self.db.execute("INSERT INTO reconciliation_runs VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                                (result["id"], today.isoformat(), _canonical(result), _now()))
        return result

    def snapshot(self) -> dict:
        result = self.reconcile()
        from .subject_folders import listing
        result["subject_folders"] = listing(self, result)
        result["records"] = [dict(row) for row in self.db.execute(
            "SELECT id, kind, external_id, captured_at, created_at, length(content) characters "
            "FROM evidence_records ORDER BY created_at DESC, id")]
        result["associations"] = [dict(row) for row in self.db.execute("SELECT * FROM project_records")]
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_provenance'").fetchone():
            result["demo_notice"] = self.db.execute("SELECT description FROM demo_provenance LIMIT 1").fetchone()[0]
        return result
