"""Deterministic acceptance scenario; not a model accuracy benchmark."""

import tempfile
import unittest
from pathlib import Path

from lima_next.workspace import Workspace
from lima_next.interpret import propose_candidates
from lima_next.memory_search import search
from lima_next.drafts import prepare, review


class DemoLoopTests(unittest.TestCase):
    def test_chat_and_meeting_become_reviewed_memory_search_and_local_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(Path(folder)/'demo.db')
            try:
                project=ws.create_project('Synthetic demo project')
                first='USER: Use a live demo for the presentation.'
                old=ws.import_text([project],kind='chatgpt',external_id='Synthetic chat',content=first)
                result=propose_candidates(ws,project,old,[dict(quote=first,kind='decision',subject='Demo format',
                    value='Use a live demo',attribution='user',owner='user')])
                initial=result['pending_ids'][0]
                self.assertEqual(ws.reconcile()['projects'][0]['current'],[])
                ws.review_claim(initial,decision='accepted',actor='synthetic-reviewer')
                lines=['USER: Replace the live demo with a recorded walkthrough.',
                       'USER: I will record the walkthrough.',
                       'TV: I am moving to Chicago next month.']
                second='\n'.join(lines)
                record=ws.import_text([project],kind='transcript',external_id='Synthetic meeting',content=second)
                candidates=[dict(quote=lines[0],kind='decision',subject='Demo format',value='Use a recorded walkthrough',attribution='user',owner='user'),
                            dict(quote=lines[1],kind='commitment',subject='Walkthrough recording',value='Record the walkthrough',attribution='user',owner='user'),
                            dict(quote=lines[2],kind='reference',subject='Background dialogue',value='Background speaker mentioned moving',attribution='ambient')]
                result=propose_candidates(ws,project,record,candidates)
                ids={c['subject']:c['id'] for c in ws.claims() if c['id'] in result['pending_ids']}
                self.assertEqual(ws.reconcile()['projects'][0]['current'][0]['id'],initial)
                ws.review_claim(ids['Demo format'],decision='accepted',actor='synthetic-reviewer',supersedes=initial)
                ws.review_claim(ids['Walkthrough recording'],decision='accepted',actor='synthetic-reviewer')
                ws.keep_as_reference(ids['Background dialogue'])
                state=ws.reconcile()['projects'][0]
                self.assertEqual(len(state['work']),1)
                self.assertEqual(state['pending_count'],0)
                hits=search(ws,'demo',project)['results']
                self.assertTrue(any(h.get('id')==initial and h['status']=='superseded' for h in hits))
                self.assertTrue(any(h.get('id')==ids['Demo format'] and h['status']=='current' for h in hits))
                draft=prepare(ws,project,'update','2026-11-01')
                self.assertIn('Use a recorded walkthrough',draft['body'])
                self.assertNotIn('Use a live demo for the presentation.',draft['body'])
                self.assertNotIn('moving to Chicago',draft['body'])
                approved=review(ws,draft['id'],draft['version_id'],'approved')
                self.assertEqual(approved['status'],'approved')
                self.assertFalse(approved['external_execution'])
            finally:
                ws.close()
