import tempfile
import unittest
from pathlib import Path

from lima_next.interpret import propose_candidates
from lima_next.workspace import Workspace


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.temp.name) / "references.db")
        self.project = self.ws.create_project("Course")
        self.text = "LECTURER: Conduct due diligence before investing."
        self.record = self.ws.import_text([self.project], kind="text", external_id="lecture", content=self.text)

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def candidate(self, **kwargs):
        payload = dict(start=0, end=len(self.text), kind="commitment", subject="Due diligence",
                       value="Conduct due diligence before investing", attribution="ambient", owner="unknown")
        payload.update(kwargs)
        return self.ws.propose_claim(self.project, self.record, **payload)

    def test_course_material_can_be_kept_without_creating_work_or_personal_fact(self):
        original = self.candidate()
        reference = self.ws.keep_as_reference(original)
        report = self.ws.reconcile()["projects"][0]
        self.assertEqual(report["work"], [])
        self.assertEqual(report["questions"], [])
        self.assertEqual(report["draft"]["items"], [])
        self.assertEqual(report["references"][0]["id"], reference)
        self.assertEqual(report["references"][0]["attribution"], "ambient")
        self.assertEqual(report["references"][0]["quote"], self.text)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(len(report["history"]), 2)
        self.assertEqual(self.ws.keep_as_reference(original), reference)

    def test_direct_reference_can_keep_uncertain_attribution(self):
        reference = self.candidate(kind="reference", attribution="uncertain")
        self.ws.review_claim(reference, decision="accepted", actor="user")
        self.assertEqual(self.ws.reconcile()["projects"][0]["references"][0]["owner"], "unknown")

    def test_existing_accepted_commitment_is_not_silently_downgraded(self):
        claim = self.candidate(attribution="user", owner="user")
        self.ws.review_claim(claim, decision="accepted", actor="user")
        with self.assertRaises(ValueError):
            self.ws.keep_as_reference(claim)
        self.assertEqual(len(self.ws.reconcile()["projects"][0]["work"]), 1)

    def test_references_on_same_topic_do_not_create_work_conflicts(self):
        for value in ("Check finances", "Check governance"):
            self.ws.keep_as_reference(self.candidate(value=value))
        report = self.ws.reconcile()["projects"][0]
        self.assertEqual(len(report["references"]), 2)
        self.assertEqual(report["conflicts"], [])

    def test_ai_reference_stays_pending_and_cannot_carry_task_fields(self):
        result = propose_candidates(self.ws, self.project, self.record, [{
            "quote": self.text, "kind": "reference", "subject": "Due diligence", "value": "Course advice",
            "attribution": "ambient", "owner": "user", "state": "done", "due_date": "2026-12-01"}])
        self.assertEqual(result["errors"], [])
        claim = self.ws.claims()[0]
        self.assertEqual(claim["owner"], "unknown")
        self.assertIsNone(claim["due_date"])
        self.assertEqual(claim["review"], "pending")
        self.assertEqual(self.ws.reconcile()["projects"][0]["references"], [])

    def test_reference_api_rejects_a_work_owner_or_deadline(self):
        for values in ({"owner": "user"}, {"state": "done"},
                       {"due_date": "2026-11-01", "date_basis": "verified"}):
            with self.assertRaises(ValueError):
                self.candidate(kind="reference", **values)

    def test_explicit_course_mode_cannot_create_work_even_if_model_calls_it_commitment(self):
        result = propose_candidates(self.ws, self.project, self.record, [{
            "quote": self.text, "kind": "commitment", "subject": "Due diligence", "value": "Course advice",
            "attribution": "user", "owner": "user", "state": "done", "due_date": "2026-12-01"}], mode="reference")
        self.assertEqual(result["new_count"], 1)
        claim = self.ws.claims()[0]
        self.assertEqual(claim["kind"], "reference")
        self.assertEqual(claim["attribution"], "uncertain")
        self.assertEqual(claim["owner"], "unknown")
        self.assertIsNone(claim["due_date"])

    def test_zero_new_suggestions_does_not_hide_existing_pending_claims(self):
        self.candidate()
        result = propose_candidates(self.ws, self.project, self.record, [])
        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["pending_source_count"], 1)
        self.assertEqual(result["pending_total_count"], 1)

    def test_source_reading_mode_persists_without_rewriting_prior_claims(self):
        claim = self.candidate()
        self.ws.source_mode(self.project, self.record, "reference")
        self.assertEqual(self.ws.record(self.record)["interpretation_modes"][self.project], "reference")
        self.assertEqual(self.ws.claims()[0]["id"], claim)
        self.assertEqual(self.ws.claims()[0]["kind"], "commitment")

    def test_repeat_suggestions_are_counted_as_existing_not_new(self):
        candidate = {"quote": self.text, "kind": "reference", "subject": "Topic", "value": "Learning"}
        first = propose_candidates(self.ws, self.project, self.record, [candidate])
        second = propose_candidates(self.ws, self.project, self.record, [candidate])
        self.assertEqual(first["new_count"], 1)
        self.assertEqual(second["new_count"], 0)
        self.assertEqual(second["existing_count"], 1)


if __name__ == "__main__":
    unittest.main()
