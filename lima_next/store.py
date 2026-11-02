"""Local, project-scoped evidence, memory, and action review storage.

This module makes no network calls and cannot execute an outward action.
Caller identity must be established by a future application authentication layer.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty string is required")
    return value


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    """One connection per thread. All writes commit atomically."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, 4):
            self.db.close()
            raise ValueError(f"Unsupported Lima database version: {version}")
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                kind TEXT NOT NULL, external_id TEXT NOT NULL,
                content TEXT NOT NULL, content_hash TEXT NOT NULL,
                participation TEXT NOT NULL CHECK (
                    participation IN ('participant', 'ambient', 'uncertain')),
                created_at TEXT NOT NULL,
                UNIQUE(project_id, kind, external_id), UNIQUE(id, project_id)
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(id, project_id)
            );
            CREATE TABLE IF NOT EXISTS memory_evidence (
                memory_id TEXT NOT NULL, source_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                PRIMARY KEY(memory_id, source_id),
                FOREIGN KEY(memory_id, project_id) REFERENCES memories(id, project_id),
                FOREIGN KEY(source_id, project_id) REFERENCES sources(id, project_id)
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(id, project_id)
            );
            CREATE TABLE IF NOT EXISTS proposal_evidence (
                proposal_id TEXT NOT NULL, source_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                PRIMARY KEY(proposal_id, source_id),
                FOREIGN KEY(proposal_id, project_id) REFERENCES proposals(id, project_id),
                FOREIGN KEY(source_id, project_id) REFERENCES sources(id, project_id)
            );
            CREATE TABLE IF NOT EXISTS reviews (
                proposal_id TEXT PRIMARY KEY REFERENCES proposals(id),
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                actor TEXT NOT NULL, payload_hash TEXT NOT NULL, reviewed_at TEXT NOT NULL
            );
            COMMIT;
        """)
        if version == 0:
            self.db.execute("PRAGMA user_version = 1")

    def close(self) -> None:
        self.db.close()

    def create_project(self, name: str) -> str:
        project_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO projects VALUES (?, ?, ?)",
                            (project_id, _required(name), _now()))
        return project_id

    def add_source(self, project_id: str, *, kind: str, external_id: str,
                   content: str, participation: str = "uncertain") -> str:
        """Retry-safe ingestion. Changed evidence requires a new revision ID."""
        _required(kind)
        _required(external_id)
        _required(content)
        if participation not in {"participant", "ambient", "uncertain"}:
            raise ValueError("Invalid participation classification")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_id = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, kind, external_id) DO NOTHING",
                (source_id, project_id, kind, external_id, content, digest,
                 participation, _now()))
            row = self.db.execute(
                "SELECT * FROM sources WHERE project_id=? AND kind=? AND external_id=?",
                (project_id, kind, external_id)).fetchone()
            if row["content_hash"] != digest or row["participation"] != participation:
                raise ValueError("Source changed; import with a new revision ID")
            return row["id"]

    def add_memory(self, project_id: str, *, kind: str, content: str,
                   source_ids: list[str]) -> str:
        if kind not in {"note", "decision", "commitment", "question"}:
            raise ValueError("Invalid memory kind")
        if not source_ids:
            raise ValueError("Memory requires source evidence")
        memory_id = uuid.uuid4().hex
        with self.db:
            if kind in {"commitment", "decision"}:
                for source_id in source_ids:
                    source = self.db.execute(
                        "SELECT participation FROM sources WHERE id=? AND project_id=?",
                        (source_id, project_id)).fetchone()
                    if source is not None and source[0] != "participant":
                        raise ValueError("Personal decisions and commitments need participant evidence")
            self.db.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?)",
                            (memory_id, project_id, kind, _required(content), _now()))
            self.db.executemany("INSERT INTO memory_evidence VALUES (?, ?, ?)",
                                [(memory_id, sid, project_id) for sid in set(source_ids)])
        return memory_id

    def list_memories(self, project_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM memories WHERE project_id=? ORDER BY created_at, id",
            (project_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["source_ids"] = [r[0] for r in self.db.execute(
                "SELECT source_id FROM memory_evidence WHERE memory_id=? ORDER BY source_id",
                (row["id"],))]
            result.append(item)
        return result

    def propose_action(self, project_id: str, *, action: str, destination: str,
                       content: str, source_ids: list[str]) -> dict:
        """Record an exact action for review; this is never permission to execute."""
        if not source_ids:
            raise ValueError("Action requires source evidence")
        payload = _canonical({"action": _required(action),
                              "destination": _required(destination),
                              "content": _required(content)})
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        proposal_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO proposals VALUES (?, ?, ?, ?, ?)",
                            (proposal_id, project_id, payload, digest, _now()))
            self.db.executemany("INSERT INTO proposal_evidence VALUES (?, ?, ?)",
                                [(proposal_id, sid, project_id) for sid in set(source_ids)])
        return self.get_proposal(project_id, proposal_id)

    def get_proposal(self, project_id: str, proposal_id: str) -> dict:
        row = self.db.execute(
            "SELECT p.*, r.decision, r.actor, r.reviewed_at FROM proposals p "
            "LEFT JOIN reviews r ON p.id=r.proposal_id WHERE p.project_id=? AND p.id=?",
            (project_id, proposal_id)).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["status"] = item.pop("decision") or "pending"
        item["source_ids"] = [r[0] for r in self.db.execute(
            "SELECT source_id FROM proposal_evidence WHERE proposal_id=? ORDER BY source_id",
            (proposal_id,))]
        return item

    def review_action(self, project_id: str, proposal_id: str, *,
                      expected_hash: str, decision: str, actor: str) -> dict:
        """Bind a single review to the exact payload displayed by the future UI.

        The caller must authenticate the reviewer. This local library is not an
        authorization boundary against another process with database access.
        """
        if decision not in {"approved", "rejected"}:
            raise ValueError("Invalid review decision")
        _required(actor)
        with self.db:
            row = self.db.execute(
                "SELECT payload, payload_hash FROM proposals WHERE project_id=? AND id=?",
                (project_id, proposal_id)).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            actual_hash = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if expected_hash != row["payload_hash"] or actual_hash != expected_hash:
                raise ValueError("Review does not match the proposed action")
            self.db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?)",
                            (proposal_id, decision, actor, expected_hash, _now()))
        return self.get_proposal(project_id, proposal_id)
