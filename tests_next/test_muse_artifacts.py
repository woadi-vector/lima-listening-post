import json
import tempfile
import unittest
from pathlib import Path
from lima_next.workspace import Workspace
from lima_next import process_day,daily_artifacts,drafts,outgoing_actions as actions


class ContactClient:
    def __init__(self):self.people=[];self.writes=[];self.saved={};self.fail=False
    def account(self):return {'account_id':'test-account','email':'owner@example.com'}
    def request(self,service,method,path,data=None,headers=None):
        if method=='GET' and 'connections?' in path:return {'connections':self.people}
        if method=='GET':return self.saved
        self.writes.append(data);self.saved={**data,'resourceName':'people/test-contact'}
        if self.fail:raise ValueError('Synthetic uncertain write')
        return self.saved


class MuseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.temp.name)/'day.db')
        self.project=self.ws.create_project('Synthetic day')
        self.text='USER: Please save Alex Rivera, alex@example.com, +15551234567, and draft a text to confirm our meeting.'
        self.record=self.ws.import_text([self.project],kind='transcript',external_id='Synthetic contact exchange',content=self.text)
        self.claim=self.ws.propose_claim(self.project,self.record,start=0,end=len(self.text),kind='reference',subject='Follow-up',value='Contact exchange',attribution='user')
        process_day.schema(self.ws)
        self.job={'id':'synthetic-job','project_id':self.project,'project':'Synthetic day','day':'2026-11-02','records':{'source':self.record},'action_ids':[]}
        self.save_job()

    def tearDown(self):self.ws.close();self.temp.cleanup()
    def save_job(self):
        with self.ws.db:self.ws.db.execute('INSERT OR REPLACE INTO day_jobs VALUES (?,?)',(self.job['id'],json.dumps(self.job)))
    def contact(self,**changes):return actions.propose(self.ws,self.project,self.record,{'kind':'contact','subject':'Save Alex contact','body':'','quote':self.text,'contact_name':'Alex Rivera','contact_email':'alex@example.com','phone':'+15551234567',**changes})
    def note(self,section='proposed',**changes):
        return daily_artifacts.prepare(self.ws,self.job,cloud_consent=True,extractor=lambda p:{'items':[{'section':section,'text':'A contact exchange needs review.','evidence_ids':[self.claim],**changes}]})

    def test_contact_details_need_literal_evidence_and_text_cannot_send(self):
        item=self.contact(contact_email='invented@example.com',contact_name='Invented Person',phone='+15557654321')
        self.assertEqual((item['contact_name'],item['contact_email'],item['phone']),('','',''))
        text=actions.propose(self.ws,self.project,self.record,{'kind':'text','subject':'Confirm meeting','body':'Could you confirm our meeting?','quote':self.text,'phone':'+15551234567'})
        with self.assertRaises(ValueError):actions.preview(self.ws,text['id'],text['version_id'],'gmail_send',client=ContactClient())

    def test_country_code_is_not_inferred_from_a_local_phone_number(self):
        item=self.contact(phone='5551234567')
        self.assertEqual(item['phone'],'')
        self.assertEqual(item['contact_email'],'alex@example.com')
        payload={k:item[k] for k in actions.clean(item)};payload['phone']='5551234567'
        with self.assertRaises(ValueError):actions.edit(self.ws,item['id'],item['version_id'],payload)

    def test_partial_manual_daily_note_is_labeled_incomplete(self):
        self.job['status']='partial';self.job['errors']=[{'reason':'Synthetic missing comparison'}];self.save_job()
        note=self.note();self.assertIn('Coverage warning',note['body']);self.assertEqual(note['status'],'prepared')

    def test_contact_requires_approval_creates_once_and_is_read_back(self):
        client=ContactClient();item=self.contact();plan=actions.preview(self.ws,item['id'],item['version_id'],'contact_create',client=client)
        with self.assertRaises(ValueError):actions.execute(self.ws,plan['id'],client=client)
        receipt=actions.execute(self.ws,plan['id'],confirmed=True,client=client)
        self.assertEqual(receipt['status'],'completed');self.assertEqual(len(client.writes),1)
        self.assertEqual(actions.execute(self.ws,plan['id'],confirmed=True,client=client)['status'],'completed')
        self.assertEqual(len(client.writes),1)

    def test_duplicate_or_uncertain_contact_write_is_not_retried(self):
        client=ContactClient();item=self.contact();client.people=[{'emailAddresses':[{'value':'alex@example.com'}]}]
        with self.assertRaisesRegex(ValueError,'matching'):actions.preview(self.ws,item['id'],item['version_id'],'contact_create',client=client)
        client.people=[];plan=actions.preview(self.ws,item['id'],item['version_id'],'contact_create',client=client);client.fail=True
        with self.assertRaisesRegex(ValueError,'unconfirmed'):actions.execute(self.ws,plan['id'],confirmed=True,client=client)
        with self.assertRaises(ValueError):actions.execute(self.ws,plan['id'],confirmed=True,client=client)
        self.assertEqual(len(client.writes),1)

    def test_daily_note_cannot_promote_pending_or_use_unknown_citations(self):
        with self.assertRaisesRegex(ValueError,'Pending'):self.note(section='reviewed')
        with self.assertRaisesRegex(ValueError,'citations'):self.note(evidence_ids=['invented'])
        self.assertFalse(drafts.listing(self.ws))

    def test_daily_repository_contains_destinations_and_holds_after_followup_edits(self):
        item=self.contact();self.job['action_ids']=[item['id']];self.save_job();note=self.note()
        self.assertIn('Google Contacts: Alex Rivera',note['body']);self.assertIn('proposed, not delivered',note['body'])
        self.assertEqual(note['status'],'prepared');self.assertFalse(note['stale'])
        payload={k:item[k] for k in actions.clean(item)};payload['contact_name']='Alex R.'
        actions.edit(self.ws,item['id'],item['version_id'],payload)
        self.assertTrue(drafts.get(self.ws,note['id'])['stale'])
        with self.assertRaisesRegex(ValueError,'Follow-ups'):drafts.review(self.ws,note['id'],note['version_id'],'approved')

    def test_repeated_note_preparation_preserves_amendments(self):
        note=self.note();edited=drafts.edit(self.ws,note['id'],note['version_id'],note['subject'],'My amended daily review.')
        again=self.note();self.assertEqual(again['version_id'],edited['version_id']);self.assertEqual(again['body'],'My amended daily review.')
