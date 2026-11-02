import tempfile
import unittest
from pathlib import Path

from lima_next.briefing import prepare_brief, latest_brief
from lima_next.workspace import Workspace


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'brief.db'
        self.ws = Workspace(self.path)
        self.project = self.ws.create_project('Reviewed project')

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def claim(self, value, *, accept=True, **kwargs):
        record = self.ws.import_text([self.project],kind='text',external_id=value,content='USER: '+value)
        args = dict(start=0,end=len('USER: '+value),kind='commitment',subject='Deliverable',
                    value=value,attribution='user',owner='user')
        args.update(kwargs)
        claim = self.ws.propose_claim(self.project,record,**args)
        if accept:
            self.ws.review_claim(claim,decision='accepted',actor='user')
        return claim

    def test_unreviewed_interpretations_never_appear_as_brief_content(self):
        self.claim('Unreviewed secret content',accept=False)
        brief=prepare_brief(self.ws,'2026-10-30')
        self.assertNotIn('Unreviewed secret content',brief['text'])
        self.assertEqual(brief['projects'][0]['pending_count'],1)
        self.assertEqual(brief['projects'][0]['work'],[])
        self.assertFalse(brief['external_execution'])

    def test_reference_and_deadline_uncertainty_stay_separate_from_work(self):
        self.claim('Prepare video',due_date='2026-10-29',date_basis='tentative')
        self.claim('Course learning',kind='reference',subject='Learning',owner='unknown',attribution='ambient')
        brief=prepare_brief(self.ws,'2026-10-30')
        project=brief['projects'][0]
        self.assertEqual(len(project['work']),1)
        self.assertFalse(project['work'][0]['overdue'])
        self.assertEqual(len(project['references']),1)
        self.assertIn('tentative deadline',brief['text'])
        self.assertIn('REFERENCE / LEARNING',brief['text'])
        self.assertIn('Evidence: USER: Prepare video',brief['text'])

    def test_conflicting_work_is_not_promoted_to_current_assignments(self):
        self.claim('Prepare video')
        self.claim('Skip video')
        brief=prepare_brief(self.ws,'2026-10-30')
        self.assertEqual(brief['projects'][0]['work'],[])
        self.assertEqual(len(brief['projects'][0]['conflicts']),1)
        self.assertIn('withheld from current work',brief['text'])

    def test_repeat_preparation_is_idempotent_and_snapshot_survives_restart(self):
        self.claim('Prepare video',due_date='2026-10-29',date_basis='verified')
        first=prepare_brief(self.ws,'2026-10-30')
        second=prepare_brief(self.ws,'2026-10-30')
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['created_at'],second['created_at'])
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM prepared_briefs').fetchone()[0],1)
        self.ws.close()
        self.ws=Workspace(self.path)
        restored=latest_brief(self.ws)
        self.assertEqual(restored['text'],first['text'])
        self.assertFalse(restored['stale'])
        self.assertIn('OVERDUE',restored['text'])

    def test_review_change_marks_saved_brief_stale_without_rewriting_it(self):
        claim=self.claim('Prepare video',accept=False)
        old=prepare_brief(self.ws,'2026-10-30')
        self.ws.review_claim(claim,decision='accepted',actor='user')
        saved=latest_brief(self.ws)
        self.assertTrue(saved['stale'])
        self.assertEqual(saved['text'],old['text'])
        self.assertNotEqual(prepare_brief(self.ws,'2026-10-30')['id'],old['id'])

    def test_invalid_date_is_rejected(self):
        for value in (None,'2026-02-30','bad','20261030'):
            with self.assertRaises(ValueError):
                prepare_brief(self.ws,value)
