"""Core behavior tests; run with python -m unittest discover -s tests_next -v."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from lima_next.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "lima.db"
        self.store = Store(self.path)
        self.project = self.store.create_project("Lima")
        self.other = self.store.create_project("Separate project")
        self.source = self.store.add_source(
            self.project, kind="manual", external_id="note-1", content="Follow up Friday")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def proposal(self):
        return self.store.propose_action(
            self.project, action="email", destination="example@example.com",
            content="Draft for review", source_ids=[self.source])

    def test_memory_survives_reopen_with_provenance_and_project_isolation(self):
        self.store.add_memory(self.project, kind="note", content="Follow up Friday",
                              source_ids=[self.source])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.list_memories(self.other), [])
        memory = self.store.list_memories(self.project)[0]
        self.assertEqual(memory["content"], "Follow up Friday")
        self.assertEqual(memory["source_ids"], [self.source])

    def test_source_retries_deduplicate_and_changed_evidence_is_rejected(self):
        same = self.store.add_source(self.project, kind="manual", external_id="note-1",
                                     content="Follow up Friday")
        self.assertEqual(same, self.source)
        with self.assertRaises(ValueError):
            self.store.add_source(self.project, kind="manual", external_id="note-1",
                                  content="Changed")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)

    def test_cross_project_evidence_rolls_back_entire_memory(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_memory(self.other, kind="note", content="Wrong project",
                                  source_ids=[self.source])
        self.assertEqual(self.store.list_memories(self.other), [])

    def test_cross_project_proposal_evidence_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.propose_action(self.other, action="email", destination="recipient",
                                      content="Wrong project", source_ids=[self.source])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0], 0)

    def test_review_requires_exact_payload_and_is_single_use(self):
        proposal = self.proposal()
        self.assertEqual(proposal["status"], "pending")
        with self.assertRaises(ValueError):
            self.store.review_action(self.project, proposal["id"], expected_hash="stale",
                                      decision="approved", actor="user")
        reviewed = self.store.review_action(
            self.project, proposal["id"], expected_hash=proposal["payload_hash"],
            decision="approved", actor="user")
        self.assertEqual(reviewed["status"], "approved")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.review_action(
                self.project, proposal["id"], expected_hash=proposal["payload_hash"],
                decision="rejected", actor="user")

    def test_other_project_cannot_review_or_read_proposal(self):
        proposal = self.proposal()
        with self.assertRaises(KeyError):
            self.store.get_proposal(self.other, proposal["id"])
        with self.assertRaises(KeyError):
            self.store.review_action(self.other, proposal["id"],
                                      expected_hash=proposal["payload_hash"],
                                      decision="approved", actor="user")

    def test_unknown_participation_is_default_and_evidence_is_required(self):
        self.assertEqual(self.store.db.execute(
            "SELECT participation FROM sources WHERE id=?", (self.source,)
        ).fetchone()[0], "uncertain")
        with self.assertRaises(ValueError):
            self.store.add_memory(self.project, kind="decision", content="No evidence",
                                  source_ids=[])
        with self.assertRaises(ValueError):
            self.store.propose_action(self.project, action="email", destination="recipient",
                                      content="No evidence", source_ids=[])

    def test_provisional_api_blocks_uncertain_personal_commitments(self):
        with self.assertRaises(ValueError):
            self.store.add_memory(self.project, kind="commitment", content="Unsupported",
                                  source_ids=[self.source])


if __name__ == "__main__":
    unittest.main()
