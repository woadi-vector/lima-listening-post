import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lima_next.workspace import Workspace
from lima_next import drafts, muse_reconciliation as recon


class MuseReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.folder.name)/'recon.db')
        self.project=self.ws.create_project('Synthetic launch project')
        text='USER: We agreed to launch on Friday.'
        record=self.ws.import_text([self.project],kind='text',external_id='Earlier agreement',content=text)
        self.old=self.ws.propose_claim(self.project,record,start=0,end=len(text),kind='decision',subject='Launch',value='Launch on Friday',attribution='user')
        self.ws.review_claim(self.old,decision='accepted',actor='synthetic')
        self.text='Alex: Friday depends on testing being complete; nobody has confirmed testing yet.'
        self.record=self.ws.import_text([self.project],kind='transcript',external_id='New condition',content=self.text)

    def tearDown(self):self.ws.close();self.folder.cleanup()
    def candidate(self, **overrides):
        return {'kind':'conditional','title':'Launch depends on testing','interpretation':'Friday may depend on unconfirmed testing.',
                'quote':self.text,'memory_ids':[self.old],'question':'Is testing complete?',
                'follow_up':'Ask whether testing is complete before confirming Friday.',**overrides}
    def run_recon(self, candidates):
        return recon.analyze(self.ws,self.project,self.record,cloud_consent=True,memory_consent=True,
                             extractor=lambda payload:{'comparisons':candidates})

    def test_consent_precedes_network_or_context_extraction(self):
        extract=Mock()
        with self.assertRaisesRegex(ValueError,'Confirm'):
            recon.analyze(self.ws,self.project,self.record,cloud_consent=True,extractor=extract)
        extract.assert_not_called()

    def test_conditional_comparison_preserves_work_and_prepares_unapproved_cited_note(self):
        before=self.ws.claims(self.project)
        result=self.run_recon([self.candidate()]);report=recon.get(self.ws,result['report_id'])
        self.assertTrue(report['complete']);self.assertFalse(report['stale'])
        self.assertEqual(self.ws.claims(self.project),before)
        note=recon.prepare_note(self.ws,report['id'])
        self.assertEqual(note['status'],'prepared');self.assertIn('Proposed next step:',note['body'])
        self.assertIn(self.text,note['body']);self.assertIn('We agreed to launch on Friday',note['body'])
        self.assertEqual(len(note['evidence']),2)
        self.assertEqual(recon.prepare_note(self.ws,report['id'])['version_id'],note['version_id'])

    def test_bad_quotes_foreign_ids_and_uncited_changes_are_rejected(self):
        other=self.ws.create_project('Private unrelated project')
        text='Secret plan for another project.'
        rid=self.ws.import_text([other],kind='text',external_id='Private',content=text)
        foreign=self.ws.propose_claim(other,rid,start=0,end=len(text),kind='decision',subject='Other',value='Private plan',attribution='user')
        self.ws.review_claim(foreign,decision='accepted',actor='synthetic')
        for candidate in [self.candidate(quote='A fabricated sentence that is not in this transcript.'),
                          self.candidate(memory_ids=[foreign]),self.candidate(kind='possible_change',memory_ids=[])]:
            result=self.run_recon([candidate]);self.assertTrue(result['section_errors'])
            self.assertFalse(recon.get(self.ws,result['report_id'])['complete'])
        def inspect(payload):
            self.assertNotIn('Secret plan',str(payload));self.assertEqual([m['id'] for m in payload['reviewed_memory']],[self.old])
            return {'comparisons':[]}
        recon.analyze(self.ws,self.project,self.record,cloud_consent=True,memory_consent=True,extractor=inspect)

    def test_completed_checkpoint_does_not_repeat_cloud_calls_and_stale_context_blocks_notes(self):
        result=self.run_recon([self.candidate()]);extract=Mock(side_effect=AssertionError('should reuse completed section'))
        recon.analyze(self.ws,self.project,self.record,cloud_consent=True,memory_consent=True,extractor=extract)
        extract.assert_not_called()
        self.ws.propose_claim(self.project,self.record,start=0,end=len(self.text),kind='question',subject='Testing',value='Is testing complete?',attribution='other')
        self.assertTrue(recon.get(self.ws,result['report_id'])['stale'])
        with self.assertRaisesRegex(ValueError,'current'):recon.prepare_note(self.ws,result['report_id'])

    def test_cancelled_report_cannot_prepare_note_and_can_resume(self):
        result=recon.analyze(self.ws,self.project,self.record,cloud_consent=True,memory_consent=True,cancelled=lambda:True)
        self.assertTrue(result['cancelled'])
        with self.assertRaisesRegex(ValueError,'Complete'):recon.prepare_note(self.ws,result['report_id'])
        resumed=self.run_recon([self.candidate()]);self.assertFalse(resumed['cancelled'])

    def test_legacy_generated_summary_is_not_sent(self):
        report='---\nsession_id: example\nmode: meeting\n---\nAI NOTES: secret invented commitment\n## Full Transcript\n'+self.text
        rid=self.ws.import_text([self.project],kind='text',external_id='Legacy report',content=report)
        def extract(payload):
            self.assertNotIn('AI NOTES',payload['source_text'])
            return {'comparisons':[self.candidate()]}
        result=recon.analyze(self.ws,self.project,rid,cloud_consent=True,memory_consent=True,extractor=extract)
        self.assertFalse(result['section_errors'])
        item=recon.get(self.ws,result['report_id'])['sections'][0]['items'][0]
        self.assertEqual(report[item['start_offset']:item['end_offset']],self.text)

    def test_background_job_requires_memory_consent_and_dispatches_separate_purpose(self):
        from lima_next.analysis_jobs import AnalysisJobs
        path=Path(self.folder.name)/'jobs.db'
        jobs=AnalysisJobs(path)
        try:
            with self.assertRaisesRegex(ValueError,'Confirm'):
                jobs.start('project','record','mixed',provider='meta',purpose='reconciliation',cloud_consent=True)
            with patch('lima_next.meta_provider.ready',return_value=True), patch('lima_next.muse_reconciliation.analyze',return_value={'cancelled':False,'section_errors':[]}) as analyze:
                job=jobs.start('project','record','mixed',provider='meta',purpose='reconciliation',cloud_consent=True,memory_consent=True)
                jobs.pool.shutdown(wait=True)
                self.assertEqual(jobs.get(job['id'])['status'],'completed')
                self.assertTrue(analyze.call_args.kwargs['memory_consent'])
                self.assertTrue(analyze.call_args.kwargs['cloud_consent'])
        finally:jobs.close()


    def test_source_is_not_compared_against_its_own_reviewed_claims(self):
        claim=self.ws.propose_claim(self.project,self.record,start=0,end=len(self.text),kind='reference',subject='Condition',value='Testing condition',attribution='other')
        self.ws.review_claim(claim,decision='accepted',actor='synthetic')
        seen=[]
        recon.analyze(self.ws,self.project,self.record,cloud_consent=True,memory_consent=True,extractor=lambda p:seen.extend(p['reviewed_memory']) or {'comparisons':[]})
        self.assertEqual([c['id'] for c in seen],[self.old])
