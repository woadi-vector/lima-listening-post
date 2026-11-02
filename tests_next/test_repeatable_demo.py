import tempfile
import unittest
from pathlib import Path
from lima_next.demo import build, build_day, evaluate
from lima_next.workspace import Workspace
from lima_next.changes import project_changes
from lima_next import drafts


class RepeatableDemoTests(unittest.TestCase):
    def test_isolated_scripted_demo_has_history_pending_revision_and_unapproved_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'demo.sqlite3'
            result=build(path)
            ws=Workspace(path)
            try:
                claims=ws.claims(result['project_id'])
                changes=project_changes(claims)
                self.assertTrue(any(c['status']=='reviewed_revision' for c in changes))
                self.assertTrue(any(c['status']=='proposed_comparison' for c in changes))
                self.assertFalse(any(c['subject']=='Venue' for c in claims))
                self.assertEqual(drafts.get(ws,result['draft_id'])['status'],'prepared')
                self.assertTrue(all(c['proposer']=='synthetic-fixture' for c in claims))
            finally:ws.close()
            with self.assertRaisesRegex(ValueError,'never reset'):build(path)

    def test_recorded_muse_showcase_is_isolated_and_never_delivers(self):
        from lima_next.demo import build_showcase
        from lima_next import outgoing_actions,process_day,google_connection,notion_delivery
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'showcase.sqlite3';result=build_showcase(path);ws=Workspace(path)
            try:
                items=outgoing_actions.listing(ws)
                self.assertEqual({a['kind'] for a in items},{'email','text','contact','calendar_create'})
                self.assertTrue(all(not a['receipts'] for a in items))
                self.assertEqual(drafts.get(ws,result['draft_id'])['status'],'prepared')
                self.assertIn('RECORDED REPLAY',drafts.get(ws,result['draft_id'])['body'])
                for item in items:self.assertIn(item['id'],drafts.get(ws,result['draft_id'])['body'])
                self.assertFalse(drafts.get(ws,result['draft_id'])['stale'])
                self.assertFalse(google_connection.state(ws)['connected'])
                self.assertFalse(notion_delivery.state(ws)['configured'])
                self.assertEqual(len(ws.claims(result['project_id'])),1)
            finally:ws.close()
            with self.assertRaisesRegex(ValueError,'never reset'):build_showcase(path)

    def test_live_evaluation_needs_explicit_consent(self):
        with self.assertRaisesRegex(ValueError,'consent'):evaluate('unused-synthetic-test.sqlite3')

    def test_day_fixture_contains_sources_without_model_outputs_or_google_writes(self):
        from lima_next import process_day, outgoing_actions
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'day.sqlite3';result=build_day(path);ws=Workspace(path)
            try:
                sources=process_day.preview(ws,result['day'],result['project_id'])['sources']
                self.assertEqual(len(sources),1)
                self.assertEqual(outgoing_actions.listing(ws),[])
                self.assertEqual(len(ws.claims(result['project_id'])),1)
                self.assertEqual(ws.claims(result['project_id'])[0]['proposer'],'synthetic-fixture')
            finally:ws.close()
