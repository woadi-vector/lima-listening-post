import tempfile
import unittest
from pathlib import Path

from lima_next.interpret import propose_candidates
from lima_next.workspace import Workspace


class EvidenceQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.temp.name) / 'quality.db')
        self.project = self.ws.create_project('Evidence')

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def source(self, text):
        return self.ws.import_text([self.project], kind='transcript', external_id='test', content=text)

    def test_program_guidance_becomes_reference_in_mixed_mode(self):
        quote = "We're not looking for teams composed of primarily many different subcontractors under a single lead organization."
        record = self.source(quote)
        result = propose_candidates(self.ws, self.project, record, [dict(
            quote=quote, kind='commitment', subject='Team structure', value='Program team guidance',
            attribution='other', owner='NSF', state='done', due_date='2026-12-01')])
        self.assertEqual(result['new_count'], 1)
        claim = self.ws.claims()[0]
        self.assertEqual((claim['kind'], claim['owner'], claim['state'], claim['due_date']),
                         ('reference', 'unknown', 'planned', None))
        self.assertEqual(claim['review'], 'pending')

    def test_vague_quote_cannot_support_detailed_reference(self):
        quote = "We're going to learn that today."
        record = self.source(quote)
        result = propose_candidates(self.ws, self.project, record, [dict(
            quote=quote, kind='reference', subject='Power BI', value='Power BI supports more than visualization')])
        self.assertEqual(result['new_count'], 0)
        self.assertIn('too vague', result['errors'][0]['reason'])

    def test_older_vague_candidate_cannot_bypass_guard_as_reference(self):
        quote = "We're going to learn that today."
        record = self.source(quote)
        claim = self.ws.propose_claim(self.project, record, start=0, end=len(quote),
            kind='reference', subject='Power BI', value='Detailed unsupported statement',
            attribution='ambient', proposer='ollama:llama3.1:8b')
        self.assertTrue(self.ws.claims()[0]['reference_block_reason'])
        for action in (lambda: self.ws.review_claim(claim, decision='accepted', actor='user'),
                       lambda: self.ws.keep_as_reference(claim)):
            with self.assertRaisesRegex(ValueError, 'too vague'):
                action()
        self.assertEqual(self.ws.claims()[0]['review'], 'pending')

    def test_old_guidance_requires_reference_conversion(self):
        quote = "We're looking for foundational platform technologies in sensing and imaging."
        record = self.source(quote)
        claim = self.ws.propose_claim(self.project, record, start=0, end=len(quote),
            kind='commitment', subject='Requirements', value='Program technology requirements',
            attribution='other', owner='NSF', proposer='ollama:llama3.1:8b')
        with self.assertRaisesRegex(ValueError, 'program guidance'):
            self.ws.review_claim(claim, decision='accepted', actor='user')
        self.ws.keep_as_reference(claim)
        self.assertEqual(len(self.ws.reconcile()['projects'][0]['references']), 1)

    def test_real_promise_and_specific_learning_survive(self):
        for quote, kind in [('USER: I will prepare the proposal by Friday.', 'commitment'),
                            ('Power BI has hundreds of built-in data connectors.', 'reference')]:
            record = self.source(quote)
            result = propose_candidates(self.ws, self.project, record, [dict(
                quote=quote, kind=kind, subject='Topic', value=quote,
                attribution='user' if kind == 'commitment' else 'ambient', owner='user')])
            self.assertEqual(result['new_count'], 1)
            self.assertEqual(next(c for c in self.ws.claims() if c['id'] == result['pending_ids'][0])['kind'], kind)
