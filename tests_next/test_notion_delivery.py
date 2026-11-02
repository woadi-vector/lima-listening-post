import copy
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from lima_next.workspace import Workspace
from lima_next import drafts, notion_delivery as notion


class FakeNotion:
    def __init__(self):
        self.parent=str(uuid.uuid4());self.pages={self.parent:{'id':self.parent,'properties':{'title':{'type':'title','title':[{'plain_text':'Daily notes'}]}}}}
        self.blocks={self.parent:[]};self.writes=0;self.timeout=False

    def page(self, identity):return self.pages[identity]
    def children(self, identity):return self.blocks.get(identity,[])
    def add(self, page, blocks):
        for block in copy.deepcopy(blocks):
            block['id']=str(uuid.uuid4())
            if block['type']=='toggle':self.blocks[block['id']]=block['toggle'].pop('children')
            self.blocks.setdefault(page,[]).append(block)
    def request(self, method, path, data=None):
        if path=='/users/me':return {'name':'Lima'}
        self.writes+=1
        if method=='POST':
            identity=str(uuid.uuid4());self.pages[identity]={'id':identity,'parent':data['parent'],'properties':data['properties']}
            self.blocks[self.parent].append({'id':identity,'type':'child_page','child_page':{'title':data['properties']['title']['title'][0]['text']['content']}})
            self.add(identity,data['children']);result=self.pages[identity]
        else:
            identity=path.split('/')[2];self.add(identity,data['children']);result={'results':[]}
        if self.timeout:raise ValueError('Synthetic timeout after server accepted write')
        return result


class NotionDeliveryTests(unittest.TestCase):
    def test_changed_followups_after_preview_block_repository_publication(self):
        draft=drafts.prepare(self.ws,self.project,'notes','2026-11-02')
        drafts.review(self.ws,draft['id'],draft['version_id'],'approved')
        plan=notion.prepare(self.ws,draft['id'],draft['version_id'],client=self.client)
        before=self.client.writes
        with patch('lima_next.daily_artifacts.is_stale',return_value=True):
            with self.assertRaisesRegex(ValueError,'Follow-ups'):
                notion.publish(self.ws,plan['id'],confirmed=True,client=self.client)
        self.assertEqual(self.client.writes,before)

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.folder.name)/'test.db');self.client=FakeNotion()
        self.project=self.ws.create_project('Synthetic project');text='USER: We decided to use the courtyard for the demo.'
        record=self.ws.import_text([self.project],kind='text',external_id='Synthetic meeting',content=text)
        claim=self.ws.propose_claim(self.project,record,start=0,end=len(text),kind='decision',subject='Demo venue',value='Use the courtyard',attribution='user')
        self.ws.review_claim(claim,decision='accepted',actor='test-user')
        self.draft=drafts.prepare(self.ws,self.project,'notes','2026-11-03')
        self.draft=drafts.review(self.ws,self.draft['id'],self.draft['version_id'],'approved')
        notion.setup(self.ws,self.client.parent,client=self.client)
        self.now=datetime(2026,11,3,15,tzinfo=timezone.utc)

    def tearDown(self):self.ws.close();self.folder.cleanup()
    def preview(self, now=None):return notion.prepare(self.ws,self.draft['id'],self.draft['version_id'],client=self.client,now=now or self.now)
    def publish(self, plan):return notion.publish(self.ws,plan['id'],confirmed=True,client=self.client,now=self.now)

    def test_exact_approval_required_and_single_page_per_central_day(self):
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'Confirm'):notion.publish(self.ws,plan['id'],client=self.client)
        self.assertEqual(self.client.writes,0)
        first=self.publish(plan);self.assertEqual(first['status'],'completed')
        self.assertEqual(self.publish(plan)['page_id'],first['page_id'])
        self.assertEqual(self.publish(self.preview())['page_id'],first['page_id'])
        self.assertEqual(self.client.writes,1)
        tomorrow=self.now+timedelta(days=1);second=self.preview(tomorrow)
        result=notion.publish(self.ws,second['id'],confirmed=True,client=self.client,now=tomorrow)
        self.assertNotEqual(result['page_id'],first['page_id'])
        self.assertEqual(self.client.writes,2)

    def test_changed_draft_and_expiry_block_before_writes(self):
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'expired'):
            notion.publish(self.ws,plan['id'],confirmed=True,client=self.client,now=self.now+timedelta(hours=1))
        drafts.edit(self.ws,self.draft['id'],self.draft['version_id'],'Updated notes','Changed draft text')
        with self.assertRaisesRegex(ValueError,'changed'):self.publish(plan)
        self.assertEqual(self.client.writes,0)

    def test_timeout_does_not_resend_and_can_verify_receipt(self):
        plan=self.preview();self.client.timeout=True
        with self.assertRaisesRegex(ValueError,'unconfirmed'):self.publish(plan)
        with self.assertRaisesRegex(ValueError,'already'):self.publish(plan)
        self.assertEqual(self.client.writes,1)
        result=notion.publish(self.ws,plan['id'],recover_only=True,client=self.client)
        self.assertEqual(result['status'],'completed');self.assertEqual(self.client.writes,1)

    def test_user_edits_are_not_overwritten_or_duplicated(self):
        result=self.publish(self.preview());page=result['page_id']
        toggle=self.client.blocks[page][0]
        self.client.blocks[toggle['id']][1]['paragraph']['rich_text'][0]['text']['content']='User edited this note'
        with self.assertRaisesRegex(ValueError,'unconfirmed'):self.publish(self.preview())
        self.assertEqual(self.client.writes,1)

    def test_new_version_appends_on_same_day_and_evidence_change_blocks_old_preview(self):
        first=self.publish(self.preview())
        self.draft=drafts.edit(self.ws,self.draft['id'],self.draft['version_id'],'Follow-up note','Draft the email for review. Do not send it.')
        self.draft=drafts.review(self.ws,self.draft['id'],self.draft['version_id'],'approved')
        second=self.publish(self.preview())
        self.assertEqual(first['page_id'],second['page_id'])
        self.assertEqual(len(self.client.blocks[first['page_id']]),2)
        plan=self.preview()
        self.ws.import_text([self.project],kind='text',external_id='New context',content='USER: We may need a different venue.')
        # Import alone does not change reviewed work. A new interpretation does change the draft stamp.
        record=self.ws.import_text([self.project],kind='text',external_id='New work',content='USER: I will check the venue.')
        self.ws.propose_claim(self.project,record,start=0,end=29,kind='commitment',subject='Check venue',value='Check the venue',attribution='user',owner='user')
        with self.assertRaisesRegex(ValueError,'changed'):self.publish(plan)
        self.assertEqual(self.client.writes,2)

    def test_only_dedicated_token_and_fixed_notion_host(self):
        with patch.dict('os.environ',{'NOTION_TOKEN':'unrelated-secret'},clear=True):
            with self.assertRaisesRegex(ValueError,'dedicated'):notion.token(self.ws)
        for bad in ['https://example.com/01234567890123456789012345678901','file:///private','not-a-page']:
            with self.assertRaises(ValueError):notion.page_id(bad)
        self.assertEqual(notion.page_id('https://app.notion.com/p/'+self.client.parent.replace('-','')),self.client.parent)
