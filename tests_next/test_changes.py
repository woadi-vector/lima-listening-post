import tempfile
import unittest
from pathlib import Path
from lima_next.workspace import Workspace
from lima_next.changes import project_changes


class ChangeViewTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.ws=Workspace(Path(self.folder.name)/'changes.db')
        self.project=self.ws.create_project('Synthetic project')

    def tearDown(self):
        self.ws.close()
        self.folder.cleanup()

    def claim(self, text, kind='decision', subject='Launch'):
        record=self.ws.import_text([self.project],kind='text',external_id=text,content=text)
        return self.ws.propose_claim(self.project,record,start=0,end=len(text),kind=kind,subject=subject,value=text,attribution='user',owner='unknown' if kind=='reference' else 'user')

    def accept(self, claim, supersedes=None):
        self.ws.review_claim(claim,decision='accepted',actor='test-user',supersedes=supersedes)

    def test_proposal_compares_without_changing_current_position(self):
        old=self.claim('We agreed to launch in May.');self.accept(old)
        new=self.claim('We should perhaps launch in June.')
        rows=project_changes(self.ws.claims(self.project))
        self.assertEqual(rows[0]['status'],'proposed_comparison')
        self.assertEqual(rows[0]['before'][0]['id'],old)
        current,_=self.ws.current_state(self.ws.claims(self.project))
        self.assertEqual([c['id'] for c in current],[old])
        self.accept(new,supersedes=old)
        rows=project_changes(self.ws.claims(self.project))
        self.assertEqual(rows[0]['status'],'reviewed_revision')
        self.assertEqual(rows[0]['after']['id'],new)

    def test_conflicting_acceptance_never_invents_replacement(self):
        a=self.claim('Launch in May.');self.accept(a)
        b=self.claim('Launch in June.');self.accept(b)
        c=self.claim('Possibly launch in July.')
        rows=project_changes(self.ws.claims(self.project))
        self.assertEqual(len(rows),1)
        self.assertEqual({i['id'] for i in rows[0]['before']},{a,b})
        self.assertEqual(rows[0]['status'],'proposed_comparison')

    def test_rejected_and_reference_material_do_not_appear_as_work_changes(self):
        a=self.claim('Useful learning.',kind='reference');self.accept(a)
        b=self.claim('Rejected proposal.')
        self.ws.review_claim(b,decision='rejected',actor='test-user')
        self.assertEqual(project_changes(self.ws.claims(self.project)),[])
        c=self.claim('A fresh topic.',subject='New topic')
        row=project_changes(self.ws.claims(self.project))[0]
        self.assertEqual(row['status'],'proposed_new')
        self.assertEqual(row['before'],[])
