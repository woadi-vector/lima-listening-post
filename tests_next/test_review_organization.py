import tempfile
import unittest
from pathlib import Path
from lima_next.workspace import Workspace
from lima_next import review_organization as organization
from lima_next.interpret import propose_candidates


class ReviewOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.folder.name)/'review.db')
        self.project=self.ws.create_project('Class day')
        self.text='LECTURER: In this class we study cultural history. USER: I will prepare the demo.'
        self.record=self.ws.import_text([self.project],kind='transcript',external_id='Mixed day',content=self.text)
        self.quote='In this class we study cultural history.'
        self.ref=propose_candidates(self.ws,self.project,self.record,[{'quote':self.quote,'kind':'reference','subject':'History','value':'Study cultural history','source_context':'class'}])['pending_ids'][0]
        q='USER: I will prepare the demo.';start=self.text.index(q)
        self.work=self.ws.propose_claim(self.project,self.record,start=start,end=start+len(q),kind='commitment',subject='Demo',value='Prepare the demo',attribution='user',owner='user')

    def tearDown(self):self.ws.close();self.folder.cleanup()

    def test_context_is_metadata_and_never_accepts_work_or_establishes_identity(self):
        c=next(c for c in self.ws.claims() if c['id']==self.ref)
        self.assertEqual(c['context_category'],'class');self.assertEqual(c['review'],'pending')
        self.assertEqual(c['attribution'],'uncertain')
        with self.assertRaises(ValueError):organization.organize(self.ws,self.project,self.record)
        result=organization.organize(self.ws,self.project,self.record,cloud_consent=True,extractor=lambda p:{'items':[{'id':self.work,'category':'conversation','quote':'I will prepare the demo.'}]})
        self.assertEqual(result['organized'],1)
        self.assertTrue(all(c['review']=='pending' for c in self.ws.claims()))

    def test_group_learning_is_atomic_and_refuses_work_stale_or_cross_source_ids(self):
        with self.assertRaises(ValueError):organization.keep_learning(self.ws,[self.ref,self.work])
        self.assertTrue(all(c['review']=='pending' for c in self.ws.claims()))
        result=organization.keep_learning(self.ws,[self.ref]);self.assertEqual(result['kept'],1)
        self.assertFalse(result['work_created'])
        with self.assertRaises(ValueError):organization.keep_learning(self.ws,[self.ref])
        self.assertEqual(next(c for c in self.ws.claims() if c['id']==self.work)['review'],'pending')

    def test_organizer_refuses_foreign_ids_and_invented_evidence(self):
        result=organization.organize(self.ws,self.project,self.record,cloud_consent=True,extractor=lambda p:{'items':[
            {'id':'foreign','category':'class','quote':self.quote},
            {'id':self.work,'category':'meeting','quote':'An invented supporting quotation.'}]})
        self.assertEqual(result['organized'],0);self.assertEqual(len(result['errors']),2)
        self.assertIsNone(next(c for c in self.ws.claims() if c['id']==self.work)['context_category'])
