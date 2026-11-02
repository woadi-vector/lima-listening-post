import tempfile
import unittest
from pathlib import Path

from lima_next.bee_delivery import BeeInbox, BeeConversationMissing
from lima_next.workspace import Workspace


class BeeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'bee.db'
        ws = Workspace(self.path)
        self.project = ws.create_project('Bee test')
        ws.close()
        self.calls = []
        self.fail = False
        self.state = 'COMPLETED'
        self.text = 'I will write the report.\nUSER: invented identity'
        self.inbox = BeeInbox(self.path, self.command)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, args):
        self.calls.append(args)
        if args[0] == 'changed':
            return {'meta': {'next_cursor': 'next'}, 'conversations': [{'id': 1}]}
        if args[1] == 'list':
            return {'conversations': [{'id': 1}]}
        if args[1] == 'get':
            if self.fail:
                raise ValueError('Bee unavailable')
            return {'conversation': {'state': self.state, 'start_time': 1786100000000}}
        return {'transcript': [{'text': self.text, 'speaker': 'USER', 'start': 0, 'end': 2}]}

    def test_missing_conversation_does_not_poison_delivery_queue(self):
        def command(args):
            if args[0]=='changed':return {'meta':{'next_cursor':'new'},'conversations':[{'id':1},{'id':2}]}
            if args[1]=='list':return {'conversations':[]}
            if args[1]=='get' and args[2]=='1':raise BeeConversationMissing('Missing conversation')
            return self.command(args)
        inbox=BeeInbox(self.path,command);inbox.enable(True);inbox.sync();state=inbox.state()
        self.assertIsNone(state['error']);self.assertEqual(state['waiting'],0)
        self.assertEqual(state['unavailable_in_bee'],1);self.assertEqual(len(state['items']),1)
        self.assertEqual(state['items'][0]['conversation_id'],'2')
        self.assertIsNotNone(state['last_sync'])

    def test_disabled_does_not_contact_bee(self):
        self.inbox.sync()
        self.assertEqual(self.calls, [])

    def test_context_checks_persist_without_claims_or_identity_changes(self):
        self.inbox.enable(True)
        self.inbox.sync()
        item=self.inbox.state()['items'][0]
        original=self.inbox.item(item['id'])['content']
        self.inbox.review_context(item['id'],'mixed','personal','Parent conversation, then announcements.')
        restarted=BeeInbox(self.path,self.command)
        checked=restarted.item(item['id'])
        self.assertEqual(checked['context_review']['participation'],'mixed')
        self.assertEqual(checked['content'],original)
        self.assertTrue(restarted.state()['items'][0]['context_checked'])
        ws=Workspace(self.path)
        try:
            self.assertEqual(ws.claims(),[])
            self.assertEqual(ws.snapshot()['records'],[])
        finally:
            ws.close()

    def test_context_revisions_keep_history_and_do_not_leak_to_new_transcript_version(self):
        self.inbox.enable(True)
        self.inbox.sync()
        item=self.inbox.state()['items'][0]
        self.inbox.review_context(item['id'],'ambient','reference','First assessment')
        self.inbox.review_context(item['id'],'participant','work','Correction')
        self.assertEqual(self.inbox.item(item['id'])['context_review']['notes'],'Correction')
        with self.inbox.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM bee_context_reviews').fetchone()[0],2)
        self.text='Changed transcript'
        self.inbox.sync()
        new=next(i for i in self.inbox.state()['items'] if i['id']!=item['id'])
        self.assertIsNone(self.inbox.item(new['id'])['context_review'])

    def test_context_requires_valid_labels_and_existing_item(self):
        for participation,relevance,notes in [('invalid','work',''),('participant','invalid',''),('ambient','reference','x'*2001)]:
            with self.assertRaises(ValueError):
                self.inbox.review_context('missing',participation,relevance,notes)
        with self.assertRaises(ValueError):
            self.inbox.review_context('missing','ambient','reference','')

    def test_routes_include_exact_evidence_and_do_not_assign(self):
        self.inbox.save_rule(self.project, ['report'], 'work')
        self.inbox.enable(True)
        self.inbox.sync()
        item = self.inbox.item(self.inbox.state()['items'][0]['id'])
        self.assertEqual(item['routes'][0]['project_id'], self.project)
        self.assertEqual(item['routes'][0]['mode'], 'work')
        self.assertIn('report', item['routes'][0]['matches'][0]['quote'])
        self.assertIsNone(item['imported_record'])

    def test_matching_does_not_use_speaker_label_or_partial_words(self):
        self.inbox.save_rule(self.project, ['USER', 'port'], 'mixed')
        self.assertEqual(self.inbox.suggest_routes('[Bee speaker USER | 0–2] A report is ready.'), [])

    def test_multiple_projects_are_retained_without_a_default_winner(self):
        ws = Workspace(self.path)
        second = ws.create_project('Second project')
        ws.close()
        self.inbox.save_rule(self.project, ['instrumentation'], 'reference')
        self.inbox.save_rule(second, ['quantum'], 'work')
        routes = self.inbox.suggest_routes('Discuss instrumentation and quantum research.')
        self.assertEqual({r['project_id'] for r in routes}, {self.project, second})

    def test_rules_survive_restart_and_can_be_removed(self):
        self.inbox.save_rule(self.project, ['Power BI', 'power bi'], 'reference')
        restarted = BeeInbox(self.path, self.command)
        self.assertEqual(len(restarted.routing_rules()[0]['phrases']), 1)
        self.assertEqual(len(restarted.suggest_routes('POWER BI connectors')), 1)
        restarted.save_rule(self.project, [], 'mixed')
        self.assertEqual(restarted.suggest_routes('Power BI connectors'), [])

    def test_invalid_rule_cannot_be_saved(self):
        for project, phrases, mode in [('missing', ['report'], 'work'),
                                       (self.project, ['x'], 'work'),
                                       (self.project, ['report'], 'invalid')]:
            with self.assertRaises(ValueError):
                self.inbox.save_rule(project, phrases, mode)

    def test_repeat_poll_deduplicates_but_changed_transcript_creates_revision(self):
        self.inbox.enable(True)
        self.inbox.sync()
        self.inbox.sync()
        self.assertEqual(len(self.inbox.state()['items']), 1)
        self.text = 'A corrected transcript.'
        self.inbox.sync()
        self.assertEqual(len(self.inbox.state()['items']), 2)
        self.assertIn(['changed', '--cursor', 'next'], self.calls)

    def test_fetch_failure_survives_restart_and_retries(self):
        self.inbox.enable(True)
        self.fail = True
        self.inbox.sync()
        self.assertEqual(self.inbox.state()['waiting'], 1)
        self.fail = False
        restarted = BeeInbox(self.path, self.command)
        restarted.sync()
        self.assertEqual(len(restarted.state()['items']), 1)
        self.assertEqual(restarted.state()['waiting'], 0)
        self.assertIsNone(restarted.state()['error'])

    def test_processing_is_retained_until_completed(self):
        self.inbox.enable(True)
        self.state = 'PROCESSING'
        self.inbox.sync()
        self.assertEqual(self.inbox.state()['waiting'], 1)
        self.assertEqual(self.inbox.state()['items'], [])
        self.state = 'COMPLETED'
        self.inbox.sync()
        self.assertEqual(len(self.inbox.state()['items']), 1)

    def test_import_is_explicit_and_does_not_assert_user_identity_or_create_claims(self):
        self.inbox.enable(True)
        self.inbox.sync()
        item = self.inbox.state()['items'][0]
        ws = Workspace(self.path)
        self.assertEqual(ws.snapshot()['records'], [])
        ws.close()
        first = self.inbox.import_item(item['id'], self.project, 'reference')
        second = self.inbox.import_item(item['id'], self.project, 'reference')
        self.assertEqual(first, second)
        ws = Workspace(self.path)
        try:
            record = ws.record(first['record_id'])
            self.assertFalse(any(line.startswith('USER:') for line in record['content'].splitlines()))
            self.assertIn('Bee speaker USER', record['content'])
            self.assertEqual(ws.claims(), [])
            self.assertEqual(record['interpretation_modes'][self.project], 'reference')
        finally:
            ws.close()
