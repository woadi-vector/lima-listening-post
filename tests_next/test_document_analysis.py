import tempfile
import unittest
from pathlib import Path

from lima_next.interpret import analyze_document, document_sections, propose_candidates
from lima_next.workspace import Workspace


class DocumentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.temp.name) / "reading.db")
        self.project = self.ws.create_project("Long source")

    def tearDown(self):
        self.ws.close()
        self.temp.cleanup()

    def source(self, content):
        return self.ws.import_text([self.project], kind="text", external_id="long", content=content)

    def test_windows_cover_all_characters_including_the_end(self):
        text = ('Sentence with Unicode ✓.\n' * 7000) + 'FINAL UNIQUE PASSAGE'
        ranges = list(document_sections(text))
        self.assertGreater(len(ranges), 1)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], len(text))
        self.assertTrue(all(end-start <= 16000 for start, end in ranges))
        self.assertTrue(all(ranges[i][0] <= ranges[i-1][1] for i in range(1, len(ranges))))

    def test_short_document_is_read_once(self):
        self.assertEqual(list(document_sections('Small source')), [(0, 12)])

    def test_long_source_end_produces_evidence_with_absolute_offsets(self):
        text = 'Filler sentence.\n' * 4000 + 'FINAL USER: I will prepare the video.'
        record = self.source(text)
        calls = []
        def extractor(section, project, mode):
            calls.append(section)
            if 'FINAL USER:' not in section:
                return []
            return [{"quote": 'FINAL USER: I will prepare the video.', "kind": 'commitment',
                     "subject": 'Video', "value": 'Prepare video', "owner": 'user', 'attribution': 'user'}]
        result = analyze_document(self.ws, self.project, record, extractor=extractor)
        self.assertGreater(len(calls), 1)
        self.assertEqual(result['new_count'], 1)
        claim = self.ws.claims()[0]
        self.assertEqual(claim['start_offset'], text.index('FINAL USER:'))
        self.assertEqual(claim['quote'], 'FINAL USER: I will prepare the video.')
        self.assertEqual(claim['review'], 'pending')

    def test_repeated_quote_can_be_located_within_a_server_selected_section(self):
        text = 'Common statement.\n' + 'x' * 20000 + '\nCommon statement.'
        record = self.source(text)
        candidate = {'quote': 'Common statement.', 'kind': 'reference', 'subject': 'Topic', 'value': 'Source claim'}
        result = propose_candidates(self.ws, self.project, record, [candidate],
                                     evidence_range=(20018, len(text)), mode='reference')
        self.assertEqual(result['new_count'], 1)
        self.assertEqual(self.ws.claims()[0]['start_offset'], text.rindex('Common statement.'))

    def test_quote_from_another_section_is_rejected(self):
        record = self.source('FIRST PASSAGE.\nSECOND PASSAGE.')
        result = propose_candidates(self.ws, self.project, record,
            [{'quote': 'FIRST PASSAGE.', 'kind': 'reference', 'subject': 'Topic', 'value': 'Claim'}],
            evidence_range=(15, 29))
        self.assertEqual(result['new_count'], 0)
        self.assertEqual(len(result['errors']), 1)

    def test_section_failure_is_reported_and_other_results_survive(self):
        record = self.source('a' * 40000)
        count = 0
        def extractor(section, project, mode):
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError('Synthetic provider failure')
            return []
        result = analyze_document(self.ws, self.project, record, extractor=extractor)
        self.assertEqual(len(result['section_errors']), 1)
        self.assertEqual(result['sections_processed'], result['sections_total'])

    def test_cancellation_stops_before_next_section(self):
        record = self.source('a' * 40000)
        result = analyze_document(self.ws, self.project, record, extractor=lambda *a, **k: [],
                                  cancelled=lambda: True)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['sections_processed'], 0)


if __name__ == '__main__':
    unittest.main()
