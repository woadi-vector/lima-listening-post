import json
import tempfile
import threading
import unittest
from pathlib import Path

from lima_next.bee_delivery import BeeInbox
from lima_next.context_suggestions import ContextSuggestions, aggregate_context, validate_context
from lima_next.interpret import document_sections
from lima_next.workspace import Workspace


class ContextSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'context.db'
        ws=Workspace(self.path)
        ws.create_project('Context test')
        ws.close()
        self.inbox=BeeInbox(self.path)
        self.text='[Bee speaker speaker_1 | 0–5] The project launch needs testing before Friday.'
        with self.inbox.connect() as db:
            db.execute('INSERT INTO bee_inbox VALUES (?,?,?,?,?,NULL,?)',
                ('item','1',self.text,'2026-11-01T12:00:00Z',None,json.dumps([{'speaker':'speaker_1','text':'The project launch needs testing before Friday.'}])))
        self.worker=ContextSuggestions.__new__(ContextSuggestions)
        self.worker.inbox=self.inbox
        self.worker.stop=threading.Event()
        self.calls=[]
        def extract(text):
            self.calls.append(text)
            return {'relevance':'work','explanation':'Project coordination.',
                    'quotes':['The project launch needs testing before Friday.']}
        self.worker.extractor=extract

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_worker_does_not_contact_model(self):
        self.assertFalse(self.worker.step())
        self.assertEqual(self.calls,[])

    def test_model_context_remains_separate_from_human_assessment_and_claims(self):
        self.inbox.review_context('item','ambient','reference','Human test label')
        self.inbox.context_enabled(True)
        self.assertTrue(self.worker.step())
        item=self.inbox.item('item')
        self.assertEqual(item['context_suggestion']['relevance'],'work')
        self.assertEqual(item['context_suggestion']['participation'],'uncertain')
        self.assertEqual(item['context_review']['relevance'],'reference')
        self.assertEqual(item['content'],self.text)
        ws=Workspace(self.path)
        try:
            self.assertEqual(ws.claims(),[])
            self.assertEqual(ws.snapshot()['records'],[])
        finally:
            ws.close()

    def test_exact_quotes_are_required_and_offsets_are_preserved(self):
        candidate={'relevance':'work','explanation':'Coordination','quotes':['project launch']}
        result=validate_context(candidate,self.text,0,len(self.text))
        evidence=result['evidence'][0]
        self.assertEqual(self.text[evidence['start']:evidence['end']],evidence['quote'])
        candidate['quotes']=['fabricated text']
        with self.assertRaises(ValueError):
            validate_context(candidate,self.text,0,len(self.text))
        candidate['quotes']=['yes']
        with self.assertRaises(ValueError):
            validate_context(candidate,'yes yes',0,7)

    def test_invalid_model_output_is_partial_not_success_and_retry_is_explicit(self):
        self.inbox.context_enabled(True)
        self.worker.extractor=lambda text:{'relevance':'work','explanation':'Unsupported','quotes':['invented']}
        self.worker.step()
        suggestion=self.inbox.item('item')['context_suggestion']
        self.assertEqual(suggestion['status'],'partial')
        self.assertEqual(suggestion['relevance'],'uncertain')
        self.assertFalse(self.worker.step())
        self.inbox.retry_context('item')
        self.assertEqual(self.inbox.item('item')['context_suggestion']['status'],'queued')

    def test_only_explicit_known_speaker_confirmation_establishes_participation(self):
        self.inbox.context_enabled(True)
        self.worker.step()
        with self.assertRaises(ValueError):
            self.inbox.confirm_speaker('item','not-in-transcript')
        self.inbox.confirm_speaker('item','speaker_1')
        self.assertEqual(self.inbox.item('item')['context_suggestion']['participation'],'participant')
        self.inbox.confirm_speaker('item',None)
        self.assertEqual(self.inbox.item('item')['context_suggestion']['participation'],'uncertain')

    def test_uncertain_sections_and_gaps_do_not_become_whole_source_certainty(self):
        self.assertEqual(aggregate_context([{'relevance':'work'},{'relevance':'personal'}],2,None)['relevance'],'mixed')
        for sections,total in [([{'relevance':'work'}],2),([{'relevance':'work'},{'error':'failed'}],2),
                               ([{'relevance':'work'},{'relevance':'uncertain'}],2)]:
            self.assertEqual(aggregate_context(sections,total,None)['relevance'],'uncertain')

    def test_restart_keeps_completed_suggestion_and_does_not_reread(self):
        self.inbox.context_enabled(True)
        self.worker.step()
        self.worker.inbox=BeeInbox(self.path)
        self.assertFalse(self.worker.step())
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.worker.inbox.item('item')['context_suggestion']['status'],'completed')

    def test_interrupted_long_read_resumes_at_saved_section(self):
        content='\n'.join(f'Sentence {n} describes project work and follow-up.' for n in range(700))
        windows=list(document_sections(content))
        first=validate_context({'relevance':'work','explanation':'Project work',
                                'quotes':[content[windows[0][0]:windows[0][0]+90]]},content,*windows[0])
        with self.inbox.connect() as db:
            db.execute('UPDATE bee_inbox SET content=? WHERE id=\'item\'',(content,))
            db.execute('INSERT INTO bee_context_suggestions(item_id,status,payload,processed,total) VALUES (?,?,?,?,?)',
                       ('item','running',json.dumps([first]),1,len(windows)))
        self.inbox.context_enabled(True)
        calls=[]
        def extract(section):
            calls.append(section)
            return {'relevance':'work','explanation':'Work','quotes':[section[:90]]}
        self.worker.extractor=extract
        self.worker.step()
        self.assertEqual(len(calls),len(windows)-1)
        self.assertEqual(self.inbox.item('item')['context_suggestion']['status'],'completed')
