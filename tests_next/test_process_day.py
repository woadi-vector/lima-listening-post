import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lima_next.workspace import Workspace
from lima_next import process_day, muse_reconciliation, outgoing_actions, drafts
from lima_next.bee_delivery import BeeInbox


class ProcessDayTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'day.db';self.ws=Workspace(self.path)
        self.project=self.ws.create_project('Synthetic campus day');self.other=self.ws.create_project('Other project')
        self.first='USER: Draft an email to alex@example.com about the campus demonstration.'
        self.second='USER: We should perhaps move our preparation meeting, but no date has been agreed.'
        self.r1=self.ws.import_text([self.project],kind='transcript',external_id='Morning discussion',content=self.first,captured_at='2026-11-03T15:00:00+00:00')
        self.r2=self.ws.import_text([self.project],kind='transcript',external_id='Later suggestion',content=self.second,captured_at='2026-11-03T18:00:00+00:00')
        self.ws.import_text([self.other],kind='transcript',external_id='Private other project',content='Private unrelated conversation.',captured_at='2026-11-03T17:00:00+00:00')
        self.note_patch=patch('lima_next.daily_artifacts.prepare',return_value=None);self.note_patch.start()
        self.addCleanup(self.note_patch.stop)
        self.jobs=process_day.DayJobs(self.path)
    def tearDown(self):self.jobs.close();self.jobs.pool.shutdown(wait=True);self.ws.close();self.folder.cleanup()

    def test_meeting_snapshot_is_exact_and_day_run_reuses_source_manifest(self):
        one=process_day.preview_meeting(self.ws,self.project,'record',self.r1)
        self.assertEqual(one['scope'],'meeting')
        self.assertEqual([x['id'] for x in one['sources']],[self.r1])
        self.assertEqual(one['day'],'2026-11-03')
        with self.assertRaisesRegex(ValueError,'Link'):
            process_day.preview_meeting(self.ws,self.other,'record',self.r1)
        with self.assertRaisesRegex(ValueError,'Select'):
            process_day.preview_meeting(self.ws,self.project,'unknown',self.r1)
        with self.assertRaisesRegex(ValueError,'Confirm'):self.jobs.start(one['id'])
        self.assertEqual(self.jobs.recent(),[])

    def test_snapshot_is_day_project_scoped_and_consent_precedes_processing(self):
        value=process_day.preview(self.ws,'2026-11-03',self.project)
        self.assertEqual({s['id'] for s in value['sources']},{self.r1,self.r2})
        with self.assertRaisesRegex(ValueError,'Confirm'):self.jobs.start(value['id'])
        self.assertEqual(self.jobs.recent(),[])
        self.ws.import_text([self.project],kind='transcript',external_id='New arrival',content='A later arrival after the consented snapshot.',captured_at='2026-11-03T19:00:00+00:00')
        self.assertEqual(len(value['sources']),2)
        self.assertEqual(len(process_day.preview(self.ws,'2026-11-03',self.project)['sources']),3)

    def test_day_phases_prepare_pending_work_and_unsent_actions_without_execution(self):
        actual_reconcile=muse_reconciliation.analyze
        calls=[]
        def updates(ws,pid,rid,**options):
            text=ws.record(rid)['content'];calls.append(('updates',rid))
            claim=ws.propose_claim(pid,rid,start=0,end=len(text),kind='question',subject=rid,value='Clarify this conversation',attribution='user')
            return {'cancelled':False,'section_errors':[],'pending_ids':[claim],'new_count':1}
        def reconciliation(ws,pid,rid,**options):
            # All sources have been interpreted before any comparison snapshot is taken.
            self.assertEqual(len(ws.claims(pid)),2)
            calls.append(('reconcile',rid));text=ws.record(rid)['content']
            return actual_reconcile(ws,pid,rid,**options,extractor=lambda payload:{'comparisons':[{
                'kind':'clarification','title':'Clarify next step','interpretation':'This needs review.','quote':text,
                'memory_ids':[],'question':'What should happen next?','follow_up':'Review the proposed next step.'}]})
        def model(system,payload,schema,name,**options):
            self.assertNotIn('Private unrelated',str(payload))
            return {'actions':[{'kind':'email','subject':'Campus demonstration','body':'Please confirm the demonstration details.',
                'quote':self.first,'to':['alex@example.com'],'start':'','end':'','timezone':'America/Chicago'}]} if self.first in payload['source_text'] else {'actions':[]}
        value=process_day.preview(self.ws,'2026-11-03',self.project)
        with patch('lima_next.meta_provider.ready',return_value=True),patch('lima_next.process_day.analyze_document',side_effect=updates),\
             patch('lima_next.muse_reconciliation.analyze',side_effect=reconciliation),patch('lima_next.meta_provider.structured_object',side_effect=model):
            job=self.jobs.start(value['id'],cloud_consent=True)
            self.jobs.pool.submit(lambda:None).result(timeout=10)
            result=self.jobs.get(job['id'])
            self.assertEqual(result['status'],'completed',result['errors'])
            self.assertEqual([c[0] for c in calls],['updates','updates','reconcile','reconcile'])
            self.assertEqual(len(result['action_ids']),1);self.assertEqual(len(result['draft_ids']),2)
            self.assertTrue(all(c['review']=='pending' for c in self.ws.claims(self.project)))
            self.assertTrue(all(not a['receipts'] for a in outgoing_actions.listing(self.ws)))
            self.assertTrue(all(d['status']=='prepared' for d in drafts.listing(self.ws)))
            repeat=self.jobs.start(value['id'],cloud_consent=True)
            self.assertEqual(repeat['id'],job['id'])
            self.assertEqual(len(calls),4)

    def test_latest_bee_version_only_and_undated_items_are_held(self):
        BeeInbox(self.path)
        with self.ws.db:
            for identity,conversation,captured,received in [('old','same','2026-11-03T15:00:00+00:00','2026-11-03T16:00:00+00:00'),
                ('new','same','2026-11-03T15:00:00+00:00','2026-11-03T17:00:00+00:00'),('undated','unknown',None,'2026-11-03T17:00:00+00:00')]:
                self.ws.db.execute('INSERT INTO bee_inbox VALUES (?,?,?,?,?,?,?)',(identity,conversation,'Synthetic Bee conversation '+identity,received,captured,None,'{}'))
        value=process_day.preview(self.ws,'2026-11-03',self.project,include_bee=True)
        self.assertEqual([s['id'] for s in value['sources'] if s['type']=='bee'],['new'])
        self.assertEqual(value['unknown_date_bee'],1)

    def test_failed_interpretation_holds_second_phase_until_resume(self):
        actual_reconcile=muse_reconciliation.analyze
        snapshot=process_day.preview(self.ws,'2026-11-03',self.project)
        broken={'cancelled':False,'section_errors':[{'section':1,'reason':'Synthetic output limit'}],'pending_ids':[]}
        good={'cancelled':False,'section_errors':[],'pending_ids':[]}
        with patch('lima_next.meta_provider.ready',return_value=True),patch('lima_next.process_day.analyze_document',return_value=broken),patch('lima_next.muse_reconciliation.analyze') as comparison:
            job=self.jobs.start(snapshot['id'],cloud_consent=True);self.jobs.pool.submit(lambda:None).result(timeout=10)
            self.assertEqual(self.jobs.get(job['id'])['status'],'partial');comparison.assert_not_called()
            self.assertEqual(self.jobs.get(job['id'])['action_ids'],[])
        def compare(ws,pid,rid,**options):return actual_reconcile(ws,pid,rid,**options,extractor=lambda payload:{'comparisons':[]})
        with patch('lima_next.process_day.analyze_document',return_value=good),patch('lima_next.muse_reconciliation.analyze',side_effect=compare),patch('lima_next.process_day.propose_actions',return_value={'action_ids':[],'errors':[]}):
            self.jobs.resume(job['id']);self.jobs.pool.submit(lambda:None).result(timeout=10)
            self.assertEqual(self.jobs.get(job['id'])['status'],'completed')

    def test_import_time_fallback_is_explicit_when_capture_time_is_absent(self):
        record=self.ws.import_text([self.project],kind='text',external_id='Undated imported notes',content='An explicitly imported note without capture metadata.')
        day=process_day._local_day(self.ws.record(record)['created_at'])
        result=process_day.preview(self.ws,day,self.project)
        source=next(s for s in result['sources'] if s['id']==record)
        self.assertIn('import time',source['date_basis'])

    def test_existing_course_mode_is_preserved_and_invalidates_prepared_context(self):
        original=drafts.project_stamp(self.ws,self.project)
        self.ws.source_mode(self.project,self.r1,'reference')
        snapshot=process_day.preview(self.ws,'2026-11-03',self.project,mode='work')
        self.assertEqual(next(s for s in snapshot['sources'] if s['id']==self.r1)['mode'],'reference')
        self.assertNotEqual(original,drafts.project_stamp(self.ws,self.project))

    def test_reference_source_never_generates_outgoing_actions(self):
        self.ws.source_mode(self.project,self.r1,'reference')
        muse_reconciliation.analyze(self.ws,self.project,self.r1,cloud_consent=True,memory_consent=True,extractor=lambda payload:{'comparisons':[]})
        with patch('lima_next.meta_provider.structured_object') as model:
            result=process_day.propose_actions(self.ws,self.project,self.r1)
            self.assertEqual(result['action_ids'],[]);model.assert_not_called()
