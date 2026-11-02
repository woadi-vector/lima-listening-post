import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from lima_next.workspace import Workspace
from lima_next import ideas


class IdeasTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.ws=Workspace(Path(self.folder.name)/'ideas.db')
        self.project=self.ws.create_project('Demo')
        self.text='USER: I keep wondering whether an audio notebook could connect these experiments.'
        self.record=self.ws.import_text([self.project],kind='text',external_id='synthetic',content=self.text)

    def tearDown(self):
        self.ws.close()
        self.folder.cleanup()

    def candidate(self, **changes):
        return {'title':'Audio notebook','description':'Explore an audio notebook.',
                'quote':self.text,'why_relevant':'Could organize experiments.',
                'next_step':'Sketch one example.','related_claim_ids':[],**changes}

    def run_ideas(self, candidates):
        return ideas.analyze(self.ws,self.project,self.record,cloud_consent=True,
                             memory_consent=True,extractor=lambda payload:{'ideas':candidates})

    def test_explicit_memory_consent_before_any_extraction(self):
        extract=Mock()
        with self.assertRaisesRegex(ValueError,'Confirm'):
            ideas.analyze(self.ws,self.project,self.record,cloud_consent=True,extractor=extract)
        extract.assert_not_called()

    def test_keep_idea_never_establishes_work_and_retries_preserve_review(self):
        self.assertEqual(self.run_ideas([self.candidate()])['new_count'],1)
        row=ideas.listing(self.ws)[0]
        ideas.review(self.ws,row['id'],'kept')
        self.assertEqual(self.run_ideas([self.candidate()])['new_count'],0)
        self.assertEqual(ideas.listing(self.ws)[0]['review'],'kept')
        self.assertEqual(self.ws.claims(self.project),[])
        self.assertEqual(self.ws.reconcile()['projects'][0]['work'],[])

    def test_invalid_quote_or_cross_project_memory_is_rejected(self):
        for candidate in [self.candidate(quote='A fabricated passage that never appeared.'),
                          self.candidate(related_claim_ids=['another-project-claim'])]:
            result=self.run_ideas([candidate])
            self.assertTrue(result['section_errors'])
        self.assertEqual(ideas.listing(self.ws),[])

    def test_unknown_identity_stays_uncertain(self):
        self.run_ideas([self.candidate(attribution='user')])
        self.assertEqual(ideas.listing(self.ws)[0]['attribution'],'uncertain')
