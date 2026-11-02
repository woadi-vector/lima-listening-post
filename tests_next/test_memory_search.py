import tempfile
import unittest
from pathlib import Path

from lima_next.memory_search import search
from lima_next.workspace import Workspace


class MemorySearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ws=Workspace(Path(self.temp.name)/'search.db')
        self.project=self.ws.create_project('Search project')

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def claim(self,value,decision='accepted',supersedes=None):
        text='USER: '+value
        record=self.ws.import_text([self.project],kind='chatgpt',external_id=value,content=text)
        cid=self.ws.propose_claim(self.project,record,start=0,end=len(text),kind='decision',
            subject='Launch',value=value,attribution='user',owner='user')
        if decision:self.ws.review_claim(cid,decision=decision,actor='user',supersedes=supersedes)
        return cid

    def test_search_preserves_current_vs_superseded_history(self):
        old=self.claim('Launch in January')
        latest=self.claim('Launch in February',supersedes=old)
        hits={h['id']:h for h in search(self.ws,'launch')['results'] if h['type']=='claim'}
        self.assertEqual(hits[old]['status'],'superseded')
        self.assertEqual(hits[latest]['status'],'current')

    def test_conflicts_pending_and_rejected_are_not_presented_as_current(self):
        a=self.claim('Launch in January')
        b=self.claim('Launch in February')
        pending=self.claim('Launch in March',decision=None)
        rejected=self.claim('Launch in April',decision='rejected')
        hits={h['id']:h['status'] for h in search(self.ws,'launch')['results'] if h['type']=='claim'}
        self.assertEqual(hits,{a:'conflicted',b:'conflicted',pending:'pending',rejected:'rejected'})

    def test_project_filter_and_many_project_source_links_are_explicit(self):
        other=self.ws.create_project('Other project')
        shared=self.ws.import_text([self.project,other],kind='transcript',external_id='Shared meeting',content='Quantum instrumentation discussion')
        private=self.ws.import_text([other],kind='text',external_id='Other meeting',content='Quantum budget')
        hits=search(self.ws,'quantum',self.project)['results']
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['record_id'],shared)
        self.assertEqual(len(hits[0]['projects']),2)
        self.assertNotEqual(hits[0]['record_id'],private)

    def test_unicode_excerpt_offsets_and_literal_search(self):
        text='Intro. '*100+'Straße project notes and café review.'
        record=self.ws.import_text([self.project],kind='text',external_id='Unicode',content=text)
        result=search(self.ws,'STRASSE')['results'][0]
        self.assertFalse(result['title_match'])
        self.assertIn('Straße',result['quote'])
        self.assertEqual(text[result['start_offset']:result['end_offset']],result['quote'])
        self.assertEqual(result['record_id'],record)

    def test_limits_are_visible_and_search_changes_no_claims(self):
        self.claim('Launch plan')
        before=len(self.ws.claims())
        result=search(self.ws,'launch',limit=1)
        self.assertTrue(result['more'])
        self.assertEqual(result['total'],2)
        self.assertEqual(len(self.ws.claims()),before)
        for query in ('','a','!!!'):
            with self.assertRaises(ValueError):search(self.ws,query)
