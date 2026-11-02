import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lima_next.workspace import Workspace
from lima_next import outgoing_actions as actions
from lima_next.google_connection import GoogleAPIError


class FakeGoogle:
    def __init__(self):
        self.writes=[];self.events_data={};self.busy=[];self.fail_after=False;self.account_id='account-one'
    def account(self):return {'account_id':self.account_id,'email':'owner@example.com','connected':True}
    def calendars(self):return {'calendars':[{'id':'owned','name':'Personal','timezone':'America/Chicago'}],'more':False}
    def request(self, service, method, path, data=None, headers=None):
        if method=='GET' and '/events?' in path:return {'items':copy.deepcopy(self.busy)}
        if method=='GET' and '/events/' in path:return copy.deepcopy(self.events_data[path.split('/events/')[1].split('?')[0]])
        self.writes.append((service,method,path,copy.deepcopy(data),headers))
        if service=='gmail':result={'id':'google-mail-id'}
        elif method=='POST':
            self.events_data[data['id']]={**copy.deepcopy(data),'etag':'version-1'};result=self.events_data[data['id']]
        else:
            identity=path.split('/events/')[1].split('?')[0]
            if self.events_data[identity]['etag']!=headers['If-Match']:raise ValueError('ETag changed')
            self.events_data[identity].update(copy.deepcopy(data));self.events_data[identity]['etag']='version-2';result=self.events_data[identity]
        if self.fail_after:raise ValueError('Synthetic timeout after accepting write')
        return result


class OutgoingActionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.folder.name)/'actions.db');self.client=FakeGoogle()
        self.project=self.ws.create_project('Synthetic day')
        self.text='USER: Draft an email to alex@example.com about the demo. Block 2026-11-03 from 14:00 to 15:00 for preparation.'
        self.record=self.ws.import_text([self.project],kind='text',external_id='Synthetic instructions',content=self.text)
    def tearDown(self):self.ws.close();self.folder.cleanup()
    def create(self, kind='email', **changes):
        value={'kind':kind,'subject':'Demo follow-up','body':'Please confirm the demonstration details.',
            'quote':self.text,'to':['alex@example.com'],'start':'2026-11-03T14:00','end':'2026-11-03T15:00','timezone':'America/Chicago',**changes}
        result=actions.propose(self.ws,self.project,self.record,value)
        if kind!='email':
            payload={key:result[key] for key in actions.clean(result)};payload.update(calendar_id='owned',event_id='existing' if kind=='calendar_update' else '')
            result=actions.edit(self.ws,result['id'],result['version_id'],payload)
        return result
    def preview(self, item, operation='gmail_send'):return actions.preview(self.ws,item['id'],item['version_id'],operation,client=self.client)
    def execute(self, plan, **kwargs):return actions.execute(self.ws,plan['id'],confirmed=True,client=self.client,**kwargs)

    def test_unknown_recipient_is_held_and_header_injection_rejected(self):
        item=self.create(to=['invented@example.com'])
        self.assertEqual(item['to'],[])
        with self.assertRaisesRegex(ValueError,'recipient'):self.preview(item)
        with self.assertRaises(ValueError):actions.addresses(['alex@example.com\r\nBcc: other@example.com'])
        with self.assertRaises(ValueError):self.create(subject='subject\r\nBcc: other@example.com')
        self.assertEqual(self.client.writes,[])

    def test_send_requires_exact_confirmation_and_deduplicates_other_previews(self):
        item=self.create();first=self.preview(item);second=self.preview(item)
        with self.assertRaisesRegex(ValueError,'Confirm'):actions.execute(self.ws,first['id'],client=self.client)
        receipt=self.execute(first);self.assertEqual(receipt['status'],'completed')
        self.assertEqual(self.execute(first)['result'],receipt['result'])
        with self.assertRaisesRegex(ValueError,'already'):self.execute(second)
        self.assertEqual(len(self.client.writes),1)
        self.assertEqual(self.client.writes[0][2],'/users/me/messages/send')

    def test_gmail_draft_is_unsent_and_cannot_also_send_same_version(self):
        item=self.create();preview=self.preview(item,'gmail_draft');self.execute(preview)
        self.assertEqual(self.client.writes[0][2],'/users/me/drafts')
        with self.assertRaisesRegex(ValueError,'already'):self.preview(item)

    def test_changed_content_account_and_project_block_writes(self):
        item=self.create();plan=self.preview(item);self.client.account_id='another-account'
        with self.assertRaisesRegex(ValueError,'account changed'):self.execute(plan)
        self.client.account_id='account-one'
        payload={key:item[key] for key in actions.clean(item)};payload['body']='Amended body.'
        actions.edit(self.ws,item['id'],item['version_id'],payload)
        with self.assertRaisesRegex(ValueError,'changed'):self.execute(plan)
        self.assertEqual(self.client.writes,[])

    def test_timeout_is_frozen_without_automatic_resend(self):
        plan=self.preview(self.create());self.client.fail_after=True
        with self.assertRaisesRegex(ValueError,'unconfirmed'):self.execute(plan)
        with self.assertRaisesRegex(ValueError,'already'):self.execute(plan)
        self.assertEqual(len(self.client.writes),1)

    def test_calendar_conflicts_need_acknowledgment_and_create_is_verified(self):
        self.client.busy=[{'id':'busy','summary':'Existing personal event','start':{'dateTime':'2026-11-03T14:00:00-06:00'},'end':{'dateTime':'2026-11-03T15:00:00-06:00'}}]
        item=self.create('calendar_create');plan=self.preview(item,'calendar_create')
        with self.assertRaisesRegex(ValueError,'conflicts'):self.execute(plan)
        result=self.execute(plan,acknowledge_conflicts=True)
        self.assertEqual(result['status'],'completed');self.assertEqual(len(self.client.writes),1)
        self.assertFalse(self.client.writes[0][3].get('attendees'))
        self.assertIn('sendUpdates=none',self.client.writes[0][2])

    def test_update_uses_etag_and_refuses_shared_meeting(self):
        self.client.events_data['existing']={'id':'existing','etag':'v1','summary':'Old event','description':'Original text',
            'start':{'dateTime':'2026-11-03T13:00:00-06:00'},'end':{'dateTime':'2026-11-03T14:00:00-06:00'}}
        item=self.create('calendar_update');plan=self.preview(item,'calendar_update')
        self.client.events_data['existing']['etag']='v2'
        with self.assertRaisesRegex(ValueError,'changed'):self.execute(plan)
        self.client.events_data['existing']['attendees']=[{'email':'other@example.com'}]
        with self.assertRaisesRegex(ValueError,'personal'):self.preview(item,'calendar_update')
        self.assertEqual(self.client.writes,[])

    def test_timezone_validation_refuses_ambiguous_nonexistent_and_wrong_offset(self):
        for start,end in [('2026-11-01T01:15','2026-11-01T01:45'),('2026-03-08T02:15','2026-03-08T03:15'),
                          ('2026-11-03T14:00:00-05:00','2026-11-03T15:00:00-05:00')]:
            with self.assertRaises(ValueError):actions.time_range(start,end,'America/Chicago')
        start,end=actions.time_range('2026-11-03T14:00','2026-11-03T15:00','America/Chicago')
        self.assertTrue(start.endswith('-06:00'))

    def test_recipient_edit_is_preserved_by_generation_retry_and_dismissal_blocks_preview(self):
        item=self.create(to=[])
        value={key:item[key] for key in actions.clean(item)};value['to']=['confirmed@example.com']
        updated=actions.edit(self.ws,item['id'],item['version_id'],value)
        again=self.create(to=[])
        self.assertEqual(again['version_id'],updated['version_id'])
        actions.dismiss(self.ws,again['id'],again['version_id'])
        with self.assertRaisesRegex(ValueError,'undismissed'):self.preview(again)

    def test_regenerated_followup_requires_acknowledging_prior_delivery(self):
        first=self.create();self.execute(self.preview(first))
        self.ws.propose_claim(self.project,self.record,start=0,end=len(self.text),kind='question',subject='New context',value='Check this context',attribution='user')
        second=self.create();self.assertNotEqual(first['id'],second['id'])
        plan=self.preview(second);self.assertEqual(len(plan['prior_deliveries']),1)
        with self.assertRaisesRegex(ValueError,'Earlier follow-ups'):self.execute(plan)
        self.execute(plan,acknowledge_prior=True);self.assertEqual(len(self.client.writes),2)

    def test_fresh_context_cannot_bypass_unknown_prior_delivery(self):
        first=self.create();self.client.fail_after=True
        with self.assertRaises(ValueError):self.execute(self.preview(first))
        self.ws.propose_claim(self.project,self.record,start=0,end=len(self.text),kind='question',subject='New context',value='Check this context',attribution='user')
        with self.assertRaisesRegex(ValueError,'uncertain delivery'):self.preview(self.create())
        self.assertEqual(len(self.client.writes),1)

    def test_source_address_substrings_are_not_treated_as_exact_recipients(self):
        text='USER: Draft a message to alex@example.com.attacker.net about the demonstration.'
        record=self.ws.import_text([self.project],kind='text',external_id='Address boundary',content=text)
        result=actions.propose(self.ws,self.project,record,{'kind':'email','subject':'Demo','body':'Please confirm.','quote':text,'to':['alex@example.com']})
        self.assertEqual(result['to'],[])
        with self.assertRaises(ValueError):actions.time_range('2026-11-03','2026-11-04','America/Chicago')

    def test_personal_event_update_uses_precondition_and_reads_back_content(self):
        self.client.events_data['existing']={'id':'existing','etag':'v1','summary':'Old event','description':'Original notes',
            'start':{'dateTime':'2026-11-03T13:00:00-06:00'},'end':{'dateTime':'2026-11-03T14:00:00-06:00'}}
        item=self.create('calendar_update');result=self.execute(self.preview(item,'calendar_update'))
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.client.writes[0][1],'PATCH');self.assertEqual(self.client.writes[0][4],{'If-Match':'v1'})

    def test_definite_google_rejection_allows_fresh_preview_after_fix(self):
        item=self.create();plan=self.preview(item)
        with patch.object(self.client,'request',side_effect=GoogleAPIError('Google denied this action.',403)):
            with self.assertRaisesRegex(ValueError,'fresh preview'):self.execute(plan)
        self.assertEqual(actions.plan(self.ws,plan['id'])['status'],'rejected')
        self.execute(self.preview(item));self.assertEqual(len(self.client.writes),1)

    def test_error_during_readback_after_acknowledged_write_remains_unknown(self):
        item=self.create('calendar_create');plan=self.preview(item,'calendar_create')
        real_request=self.client.request
        def request(service,method,path,data=None,headers=None):
            if method=='GET' and '/events/' in path:raise GoogleAPIError('Read-back failed.',404)
            return real_request(service,method,path,data,headers)
        with patch.object(self.client,'request',side_effect=request):
            with self.assertRaisesRegex(ValueError,'unconfirmed'):self.execute(plan)
        self.assertEqual(actions.plan(self.ws,plan['id'])['status'],'unknown');self.assertEqual(len(self.client.writes),1)

    def test_personal_calendar_description_can_be_empty(self):
        item=self.create('calendar_create',body='')
        result=self.execute(self.preview(item,'calendar_create'))
        self.assertEqual(result['status'],'completed')
