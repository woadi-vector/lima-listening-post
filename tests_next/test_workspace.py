import tempfile
import unittest
from pathlib import Path

from lima_next.interpret import propose_candidates
from lima_next.workspace import Workspace
from lima_next.store import Store


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "workspace.db"
        self.ws = Workspace(self.path)
        self.project = self.ws.create_project("Sample", 1)
        self.other = self.ws.create_project("Other", 2)
        self.content = "USER: I will finish the demo video.\nTV: I am moving to Chicago."
        self.record = self.ws.import_text([self.project], kind="text", external_id="chat-1",
                                          content=self.content)

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def claim(self, *, project=None, record=None, **kwargs):
        values = dict(start=0, end=34, kind="deliverable", subject="Demo video",
                      value="Prepare the demo", attribution="user", owner="user")
        values.update(kwargs)
        return self.ws.propose_claim(project or self.project, record or self.record, **values)

    def accept(self, claim, supersedes=None):
        self.ws.review_claim(claim, decision="accepted", actor="local-user", supersedes=supersedes)

    def project_report(self):
        report = self.ws.reconcile(as_of="2026-10-30")
        return next(p for p in report["projects"] if p["id"] == self.project)

    def test_pending_claims_do_not_become_work(self):
        self.claim()
        report = self.project_report()
        self.assertEqual(report["work"], [])
        self.assertEqual(report["pending_count"], 1)

    def test_ambient_and_uncertain_cannot_establish_personal_state(self):
        for attribution in ("ambient", "uncertain", "other", "involved"):
            claim = self.claim(attribution=attribution)
            with self.assertRaises(ValueError):
                self.accept(claim)
        self.assertEqual(self.project_report()["current"], [])

    def test_named_other_participant_can_have_their_own_commitment(self):
        claim = self.claim(attribution="other", owner="Alex")
        self.accept(claim)
        self.assertEqual(self.project_report()["work"][0]["owner"], "Alex")

    def test_source_can_be_explicitly_associated_with_multiple_projects(self):
        again = self.ws.import_text([self.project, self.other], kind="text", external_id="chat-1",
                                     content=self.content)
        self.assertEqual(again, self.record)
        self.assertEqual(self.ws.db.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0], 1)
        self.assertEqual(self.ws.db.execute("SELECT COUNT(*) FROM project_records").fetchone()[0], 2)
        self.claim(project=self.other)

    def test_unassociated_source_cannot_leak_into_other_project(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.claim(project=self.other)

    def test_retries_and_reconciliation_are_idempotent(self):
        claim = self.claim()
        self.assertEqual(claim, self.claim())
        self.accept(claim)
        first = self.ws.reconcile(as_of="2026-10-30")
        second = self.ws.reconcile(as_of="2026-10-30")
        self.assertEqual(first, second)
        self.assertEqual(self.ws.db.execute("SELECT COUNT(*) FROM reconciliation_runs").fetchone()[0], 1)
        self.ws.close()
        self.ws = Workspace(self.path)
        self.assertEqual(first, self.ws.reconcile(as_of="2026-10-30"))

    def test_completion_supersedes_work_but_preserves_history(self):
        first = self.claim()
        self.accept(first)
        complete = self.claim(value="Demo submitted", state="done")
        self.accept(complete, supersedes=first)
        report = self.project_report()
        self.assertEqual(report["work"], [])
        self.assertEqual(report["draft"]["items"], [])
        self.assertEqual(len(report["history"]), 2)
        self.assertEqual(report["current"][0]["state"], "done")

    def test_conflicting_decisions_are_not_silently_overwritten(self):
        first = self.claim(kind="decision", subject="Framework", value="Python")
        self.accept(first)
        second = self.claim(kind="decision", subject="Framework", value="Different framework")
        self.accept(second)
        report = self.project_report()
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["current"], [])

    def test_replacement_must_be_same_project_kind_and_subject(self):
        first = self.claim()
        self.accept(first)
        different = self.claim(subject="Submission form")
        with self.assertRaises(ValueError):
            self.accept(different, supersedes=first)

    def test_app_completion_does_not_complete_video_or_submission(self):
        for subject, state in (("App", "done"), ("Demo video", "planned"), ("Final upload", "planned")):
            self.accept(self.claim(subject=subject, state=state))
        self.assertEqual({c["subject"] for c in self.project_report()["work"]},
                         {"Demo video", "Final upload"})

    def test_only_verified_deadlines_drive_collisions_and_overdue(self):
        for subject in ("Video", "Upload"):
            self.accept(self.claim(subject=subject, due_date="2026-10-29", date_basis="verified"))
        self.accept(self.claim(subject="Tentative", due_date="2026-10-20", date_basis="tentative"))
        report = self.ws.reconcile(as_of="2026-10-30")
        project = next(p for p in report["projects"] if p["id"] == self.project)
        self.assertEqual(project["overdue_count"], 2)
        self.assertEqual(len(report["collisions"]), 1)
        self.assertEqual(len(report["collisions"][0]["items"]), 2)
        self.assertTrue(any("Tentative" in q for q in project["questions"]))

    def test_ai_cannot_verify_dates_or_accept_its_own_claims(self):
        output = propose_candidates(self.ws, self.project, self.record, [{
            "quote": "USER: I will finish the demo video.", "kind": "deliverable",
            "subject": "Demo video", "value": "Finish video", "attribution": "user",
            "owner": "user", "due_date": "2026-11-01", "confidence": 0.8}])
        self.assertEqual(output["errors"], [])
        claim = self.ws.claims()[0]
        self.assertEqual(claim["date_basis"], "tentative")
        self.assertEqual(claim["review"], "pending")
        self.assertEqual(self.project_report()["work"], [])

    def test_fabricated_or_ambiguous_ai_quotes_are_rejected(self):
        output = propose_candidates(self.ws, self.project, self.record,
                                     [{"quote": "This never happened"}])
        self.assertEqual(output["pending_ids"], [])
        self.assertEqual(len(output["errors"]), 1)

    def test_invalid_offsets_dates_and_confidence_are_rejected(self):
        for update in ({"start": -1}, {"end": 9999}, {"confidence": float("nan")},
                       {"due_date": "tomorrow", "date_basis": "verified"},
                       {"due_date": None, "date_basis": "verified"}):
            with self.assertRaises(ValueError):
                self.claim(**update)

    def test_priority_is_explicit_and_persistent(self):
        self.ws.set_priority(self.other, 1)
        self.ws.set_priority(self.project, 5)
        self.assertEqual(self.ws.reconcile()["projects"][0]["id"], self.other)

    def test_existing_provisional_database_migrates_without_losing_records(self):
        path = Path(self.temp.name) / "version1.db"
        old = Store(path)
        project = old.create_project("Original")
        source = old.add_source(project, kind="manual", external_id="old", content="Old evidence")
        old.add_memory(project, kind="note", content="Keep this", source_ids=[source])
        old.close()
        migrated = Workspace(path)
        try:
            self.assertEqual(migrated.list_memories(project)[0]["content"], "Keep this")
            self.assertEqual(migrated.db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(migrated.snapshot()["projects"][0]["history"], [])
        finally:
            migrated.close()


if __name__ == "__main__":
    unittest.main()
