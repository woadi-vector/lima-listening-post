import tempfile
import unittest
from pathlib import Path
from lima_next.workspace import Workspace
from lima_next import subject_folders as folders


class SubjectFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.temp.name)/'folders.db')
        self.project=self.ws.create_project('Lima');self.other=self.ws.create_project('Other project')

    def tearDown(self):self.ws.close();self.temp.cleanup()

    def add(self,subject='Demo',value='Use slides for the demonstration.',captured='2026-10-20T12:00:00+00:00',accepted=False,project=None,kind='reference',supersedes=None):
        project=project or self.project
        record=self.ws.import_text([project],kind='transcript',external_id=value,content=value,captured_at=captured)
        claim=self.ws.propose_claim(project,record,start=0,end=len(value),kind=kind,subject=subject,value=value,attribution='other')
        if accepted:self.ws.review_claim(claim,decision='accepted',actor='test',supersedes=supersedes)
        return claim

    def listing(self):return folders.listing(self.ws,self.ws.reconcile(as_of='2026-11-02'),as_of='2026-11-02')

    def test_normalized_subjects_reuse_folders_and_projects_remain_separate(self):
        self.add('Demo');self.add(' demo ',value='A second point about the demo.')
        self.add('Demo',project=self.other)
        rows=self.listing();self.assertEqual(len(rows),2)
        self.assertEqual(len(next(f for f in rows if f['project_id']==self.project)['pending']),2)
        self.assertEqual(len({f['id'] for f in rows}),2)
        self.assertEqual(len(self.listing()),2)

    def test_pending_information_does_not_refresh_or_replace_reviewed_overview(self):
        old=self.add(accepted=True);self.add(value='Consider a live demo instead.',captured='2026-11-02T12:00:00+00:00')
        folder=self.listing()[0]
        self.assertEqual([c['id'] for c in folder['current']],[old]);self.assertEqual(len(folder['pending']),1)
        self.assertTrue(folder['latest_reviewed_source_at'].startswith('2026-10-20'))
        self.assertTrue(folder['latest_source_at'].startswith('2026-11-02'))

    def test_recent_review_does_not_make_old_or_undated_sources_new(self):
        self.add(accepted=True);folder=self.listing()[0]
        self.assertEqual(folder['source_age_days'],13);self.assertTrue(folder['needs_fresh_check'])
        self.add('Unknown source',value='A source without a capture date.',captured=None)
        unknown=next(f for f in self.listing() if f['name']=='Unknown source')
        self.assertIsNone(unknown['source_age_days']);self.assertTrue(unknown['freshness_incomplete'])

    def test_manual_filing_survives_sync_and_cannot_cross_projects(self):
        claim=self.add();self.listing()
        with self.assertRaises(ValueError):folders.file_claim(self.ws,self.other,claim,'Elsewhere')
        folders.file_claim(self.ws,self.project,claim,'Presentation planning')
        rows=self.listing();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'Presentation planning')
        self.assertEqual(rows[0]['pending'][0]['review'],'pending')

    def test_manual_filing_is_retained_when_kept_as_reference(self):
        claim=self.add();self.listing();folders.file_claim(self.ws,self.project,claim,'My course')
        self.ws.keep_as_reference(claim)
        rows=self.listing();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'My course')
        self.assertEqual(len(rows[0]['current']),1)

    def test_conflicts_are_visible_until_explicit_reviewed_replacement(self):
        old=self.add(kind='decision',accepted=True)
        new=self.add(kind='decision',value='Use a live demonstration.',captured='2026-11-02T12:00:00+00:00',accepted=True)
        folder=self.listing()[0];self.assertEqual(len(folder['conflicts']),1);self.assertFalse(folder['overview'])
        self.assertEqual(len(folder['history']),2)

    def test_latest_source_compares_instants_not_iso_string_order(self):
        self.assertEqual(folders.latest_stamp(['2026-11-02T20:00:00+12:00','2026-11-02T10:00:00+00:00']), '2026-11-02T10:00:00+00:00')
