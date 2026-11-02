import sqlite3
import tempfile
import unittest
from pathlib import Path

from lima_next.workspace import Workspace


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.temp.name) / "workspace.db")
        self.project = self.ws.create_project("Submission")
        self.record = self.ws.import_text([self.project], kind="text", external_id="plan",
                                          content="USER: Finish video, then upload the submission.")
        self.video = self.make_work("Video")
        self.upload = self.make_work("Upload")

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def make_work(self, subject, **kwargs):
        claim = self.ws.propose_claim(self.project, self.record, start=0, end=46,
            kind="deliverable", subject=subject, value=f"Finish {subject}",
            attribution="user", owner="user", **kwargs)
        self.ws.review_claim(claim, decision="accepted", actor="test-user")
        return claim

    def report(self):
        return self.ws.reconcile()["projects"][0]

    def depend(self, blocked=None, prerequisite=None):
        return self.ws.set_dependency(self.project, blocked or self.upload,
            prerequisite or self.video, reason="Submission needs the video")

    def test_dependency_changes_readiness_and_next_step_order(self):
        self.depend()
        work = self.report()["work"]
        self.assertEqual([c["subject"] for c in work], ["Video", "Upload"])
        self.assertTrue(work[0]["ready"])
        self.assertFalse(work[1]["ready"])
        self.assertEqual(work[1]["waiting_on"][0]["subject"], "Video")

    def test_completion_releases_dependency_and_preserves_status_evidence(self):
        self.depend()
        new_id = self.ws.update_work(self.video, state="done", reason="Video recorded and checked")
        report = self.report()
        self.assertEqual(len(report["work"]), 1)
        self.assertEqual(report["work"][0]["subject"], "Upload")
        self.assertTrue(report["work"][0]["ready"])
        update = next(c for c in report["history"] if c["id"] == new_id)
        self.assertEqual(update["supersedes"], self.video)
        self.assertIn("Video recorded and checked", update["quote"])

    def test_reopening_prerequisite_blocks_dependent_again(self):
        self.depend()
        done = self.ws.update_work(self.video, state="done", reason="Finished")
        self.ws.update_work(done, state="planned", reason="Video requires a correction")
        upload = next(c for c in self.report()["work"] if c["subject"] == "Upload")
        self.assertFalse(upload["ready"])

    def test_cycles_are_rejected_without_creating_evidence(self):
        self.depend()
        before = self.ws.db.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.depend(self.video, self.upload)
        after = self.ws.db.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
        self.assertEqual(before, after)

    def test_retry_add_and_remove_are_idempotent_and_keep_history(self):
        edge = self.depend()
        self.assertEqual(self.depend(), edge)
        self.ws.remove_dependency(edge, reason="Uploads can proceed independently")
        self.ws.remove_dependency(edge, reason="Retry")
        self.assertEqual(self.ws.db.execute("SELECT COUNT(*) FROM dependency_events").fetchone()[0], 2)
        self.assertTrue(all(c["ready"] for c in self.report()["work"]))

    def test_conflicted_prerequisite_remains_unresolved_not_complete(self):
        edge = self.depend()
        self.make_work("Video", state="done")  # accepted without superseding: conflict
        upload = self.report()["work"][0]
        self.assertFalse(upload["ready"])
        self.assertTrue(upload["waiting_on"][0]["unresolved"])
        self.ws.remove_dependency(edge, reason="Remove incorrect relationship")
        self.assertTrue(self.report()["work"][0]["ready"])

    def test_old_status_update_cannot_overwrite_newer_state(self):
        self.ws.update_work(self.video, state="done", reason="Finished")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.ws.update_work(self.video, state="planned", reason="Stale browser tab")

    def test_cross_project_dependency_is_rejected(self):
        other = self.ws.create_project("Other")
        with self.assertRaises(ValueError):
            self.ws.set_dependency(other, self.upload, self.video, reason="Wrong project")

    def test_live_backup_is_consistent_and_can_be_opened_as_a_separate_workspace(self):
        self.depend()
        self.ws.update_work(self.video, state="done", reason="Finished")
        expected = self.ws.snapshot()
        backup = Path(self.temp.name) / "backup.sqlite3"
        backup.write_bytes(self.ws.backup_bytes())
        copy = Workspace(backup)
        try:
            self.assertEqual(copy.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(copy.snapshot(), expected)
            copy.update_work(self.upload, state="done", reason="Finished on the copy")
            self.assertEqual(len(self.report()["work"]), 1)
        finally:
            copy.close()


if __name__ == "__main__":
    unittest.main()
