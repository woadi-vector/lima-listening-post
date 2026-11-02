import tempfile
import unittest
from pathlib import Path

from lima_next.interpret import analyze_document, propose_candidates
from lima_next.workspace import Workspace


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.temp.name)/'attribution.db')
        self.project = self.ws.create_project('Source identity')

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def record(self, text):
        return self.ws.import_text([self.project],kind='transcript',external_id='source',content=text)

    def candidate(self, quote):
        return {'quote':quote,'kind':'commitment','subject':'Video','value':'Prepare video',
                'attribution':'user','owner':'user'}

    def test_unlabeled_first_person_is_not_assigned_to_the_wearer(self):
        text='I built a video and spoke at the panel.'
        source=self.record(text)
        propose_candidates(self.ws,self.project,source,[self.candidate(text)])
        claim=self.ws.claims()[0]
        self.assertEqual(claim['attribution'],'uncertain')
        self.assertEqual(claim['owner'],'unknown')

    def test_explicit_user_label_supports_the_named_import_convention(self):
        text='USER: I will prepare the video.'
        source=self.record(text)
        propose_candidates(self.ws,self.project,source,[self.candidate('I will prepare the video.')])
        self.assertEqual(self.ws.claims()[0]['attribution'],'user')

    def test_old_model_guess_is_blocked_at_review_without_rewriting_history(self):
        text='I spoke at a panel.'
        source=self.record(text)
        cid=self.ws.propose_claim(self.project,source,start=0,end=len(text),kind='commitment',
            subject='Panel',value='Spoke at a panel',attribution='user',owner='user',proposer='ollama:llama3.1:8b')
        self.assertTrue(self.ws.claims()[0]['review_block_reason'])
        with self.assertRaisesRegex(ValueError,'speaker'):
            self.ws.review_claim(cid,decision='accepted',actor='user')
        self.assertEqual(self.ws.claims()[0]['review'],'pending')

    def test_lima_report_excludes_generated_summary_but_preserves_offsets(self):
        text='---\nsession_id: sample\nmode: meeting\n---\n## Executive Summary\nInvented old summary.\n## Full Transcript\nUSER: I will prepare the video.'
        source=self.record(text)
        seen=[]
        def extractor(section, project, mode):
            seen.append(section)
            return [self.candidate('I will prepare the video.')]
        result=analyze_document(self.ws,self.project,source,extractor=extractor)
        self.assertNotIn('Invented old summary.', ''.join(seen))
        self.assertEqual(result['evidence_scope'],'transcript_only')
        self.assertEqual(self.ws.claims()[0]['start_offset'],text.index('I will prepare'))

    def test_output_limit_retries_smaller_sections(self):
        source=self.record('A sentence.\n'*2000)
        lengths=[]
        def extractor(section, project, mode):
            lengths.append(len(section))
            if len(section)>9000:raise ValueError('Ollama reached its output limit')
            return []
        result=analyze_document(self.ws,self.project,source,extractor=extractor)
        self.assertTrue(any(n>9000 for n in lengths))
        self.assertTrue(any(n<=9000 for n in lengths))
        self.assertEqual(result['section_errors'],[])


if __name__=='__main__':unittest.main()
