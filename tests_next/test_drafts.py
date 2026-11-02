import tempfile
import unittest
from pathlib import Path

from lima_next import drafts
from lima_next.workspace import Workspace


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'drafts.db'
        self.ws=Workspace(self.path)
        self.project=self.ws.create_project('Draft project')

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def claim(self,value,accept=True,project=None,**kwargs):
        project=project or self.project
        text='USER: '+value
        record=self.ws.import_text([project],kind='text',external_id=value,content=text)
        fields=dict(start=0,end=len(text),kind='commitment',subject='Video',value=value,attribution='user',owner='user')
        fields.update(kwargs)
        cid=self.ws.propose_claim(project,record,**fields)
        if accept:self.ws.review_claim(cid,decision='accepted',actor='user')
        return cid

    def prepare(self,kind='update'):
        return drafts.prepare(self.ws,self.project,kind,'2026-11-01')

    def test_only_reviewed_evidence_enters_draft_and_approval_does_not_execute(self):
        self.claim('Prepare video',due_date='2026-11-04',date_basis='tentative')
        self.claim('Unreviewed secret proposal',accept=False)
        draft=self.prepare()
        self.assertNotIn('Unreviewed secret proposal',draft['body'])
        self.assertIn('tentative deadline',draft['body'])
        self.assertEqual(draft['evidence'][0]['quote'],'USER: Prepare video')
        reviewed=drafts.review(self.ws,draft['id'],draft['version_id'],'approved')
        self.assertEqual(reviewed['status'],'approved')
        self.assertFalse(reviewed['external_execution'])
        self.assertEqual(len(self.ws.claims()),2)

    def test_empty_project_or_reference_only_cannot_generate_work_update(self):
        with self.assertRaises(ValueError):self.prepare()
        self.claim('Learn about connectors',kind='reference',owner='unknown',attribution='ambient')
        with self.assertRaises(ValueError):self.prepare()
        note=self.prepare('notes')
        self.assertIn('Reference and learning',note['body'])
        self.assertIn('No open work established',note['body'])

    def test_project_evidence_change_blocks_stale_approval(self):
        self.claim('Prepare video')
        old=self.prepare()
        self.claim('New pending detail',accept=False)
        self.assertTrue(drafts.get(self.ws,old['id'])['stale'])
        with self.assertRaisesRegex(ValueError,'evidence changed'):
            drafts.review(self.ws,old['id'],old['version_id'],'approved')
        fresh=self.prepare()
        self.assertNotEqual(old['id'],fresh['id'])

    def test_other_project_changes_do_not_invalidate_draft(self):
        self.claim('Prepare video')
        draft=self.prepare()
        other=self.ws.create_project('Other project')
        self.claim('Other work',project=other)
        self.assertFalse(drafts.get(self.ws,draft['id'])['stale'])

    def test_edits_create_new_version_and_clear_approval(self):
        self.claim('Prepare video')
        draft=self.prepare()
        drafts.review(self.ws,draft['id'],draft['version_id'],'approved')
        edited=drafts.edit(self.ws,draft['id'],draft['version_id'],'Edited subject','User supplied wording.')
        self.assertNotEqual(edited['version_id'],draft['version_id'])
        self.assertEqual(edited['status'],'prepared')
        with self.assertRaisesRegex(ValueError,'changed'):
            drafts.review(self.ws,draft['id'],draft['version_id'],'approved')
        with self.assertRaisesRegex(ValueError,'changed'):
            drafts.edit(self.ws,draft['id'],draft['version_id'],'Stale edit','Old view')

    def test_repeated_preparation_preserves_user_edits_and_persistence(self):
        self.claim('Prepare video')
        draft=self.prepare()
        edited=drafts.edit(self.ws,draft['id'],draft['version_id'],'User subject','My edited wording')
        again=self.prepare()
        self.assertEqual(again['version_id'],edited['version_id'])
        self.ws.close()
        self.ws=Workspace(self.path)
        self.assertEqual(drafts.get(self.ws,draft['id'])['body'],'My edited wording')
        self.assertEqual(len(drafts.listing(self.ws)),1)

    def test_conflicts_do_not_become_current_work_in_draft(self):
        self.claim('Prepare video')
        self.claim('Do not prepare video')
        draft=self.prepare()
        self.assertIn('withheld from current work',draft['body'])
        self.assertIn('No open work established',draft['body'])

    def test_unchanged_save_does_not_reset_review(self):
        self.claim('Prepare video')
        draft=self.prepare()
        approved=drafts.review(self.ws,draft['id'],draft['version_id'],'approved')
        same=drafts.edit(self.ws,draft['id'],draft['version_id'],approved['subject'],approved['body'])
        self.assertEqual(same['version_id'],draft['version_id'])
        self.assertEqual(same['status'],'approved')

    def test_batch_separates_work_updates_from_reference_notes_and_skips_pending_only(self):
        self.claim('Prepare video')
        reference=self.ws.create_project('Reference project')
        self.claim('Learning point',project=reference,kind='reference',owner='unknown',attribution='ambient')
        pending=self.ws.create_project('Pending-only project')
        self.claim('Unreviewed secret',project=pending,accept=False)
        result=drafts.prepare_all(self.ws,'2026-11-01')
        self.assertEqual(result['created'],3)
        self.assertEqual(len(result['skipped']),1)
        self.assertEqual(result['skipped'][0]['project_id'],pending)
        prepared=[drafts.get(self.ws,key) for key in result['draft_ids']]
        self.assertEqual([d['kind'] for d in prepared if d['project_id']==reference],['notes'])
        self.assertTrue(all('Unreviewed secret' not in d['body'] for d in prepared))

    def test_batch_retries_preserve_edits_and_approvals_without_duplicates(self):
        self.claim('Prepare video')
        first=drafts.prepare_all(self.ws,'2026-11-01')
        draft=drafts.get(self.ws,first['draft_ids'][0])
        edited=drafts.edit(self.ws,draft['id'],draft['version_id'],'My subject','My wording')
        drafts.review(self.ws,edited['id'],edited['version_id'],'approved')
        second=drafts.prepare_all(self.ws,'2026-11-01')
        self.assertEqual(second['created'],0)
        self.assertEqual(second['retained'],2)
        self.assertEqual(second['draft_ids'],first['draft_ids'])
        current=drafts.get(self.ws,edited['id'])
        self.assertEqual((current['body'],current['status']),('My wording','approved'))
        self.assertEqual(drafts.latest_batch(self.ws)['as_of'],'2026-11-01')
