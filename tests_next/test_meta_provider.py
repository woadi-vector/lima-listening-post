import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from lima_next.meta_provider import extract_candidates, PROPOSER
from lima_next.interpret import analyze_document
from lima_next.workspace import Workspace
from lima_next.analysis_jobs import AnalysisJobs


class MetaProviderTests(unittest.TestCase):
    @patch('lima_next.meta_provider.build_opener')
    def test_cloud_requires_explicit_consent_before_network(self, build):
        with self.assertRaisesRegex(ValueError,'Confirm'):
            extract_candidates('private source','private project')
        build.assert_not_called()

    @patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-key'})
    @patch('lima_next.meta_provider.build_opener')
    def test_fixed_endpoint_structured_output_and_no_tools(self, build):
        response=MagicMock()
        response.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"claims":[]}'}}]}).encode()
        build.return_value.open.return_value.__enter__.return_value=response
        self.assertEqual(extract_candidates('synthetic','demo',cloud_consent=True),[])
        request=build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.meta.ai/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer test-only-key')
        payload=json.loads(request.data)
        self.assertEqual(payload['model'],'muse-spark-1.3')
        self.assertEqual(payload['reasoning_effort'],'low')
        self.assertEqual(payload['response_format']['type'],'json_schema')
        self.assertNotIn('tools',payload)
        self.assertNotIn('test-only-key',json.dumps(payload))

    @patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-key'})
    @patch('lima_next.meta_provider.build_opener')
    def test_api_errors_do_not_expose_provider_body_or_credentials(self, build):
        build.return_value.open.side_effect=HTTPError('https://api.meta.ai/v1/chat/completions',401,'secret provider body',{},None)
        with self.assertRaisesRegex(ValueError,'rejected the API key') as error:
            extract_candidates('synthetic','demo',cloud_consent=True)
        self.assertNotIn('secret',str(error.exception))
        self.assertNotIn('test-only-key',str(error.exception))

    @patch.dict(os.environ, {'MODEL_API_KEY': 'test-only-key'})
    @patch('lima_next.meta_provider.build_opener')
    def test_incomplete_or_invalid_meta_output_is_rejected(self, build):
        response=MagicMock()
        build.return_value.open.return_value.__enter__.return_value=response
        for choice in [{'finish_reason':'length','message':{'content':'{}'}},
                       {'finish_reason':'stop','message':{'content':'{"claims":"wrong"}'}},
                       {'finish_reason':'stop','message':{'content':'not json'}}]:
            response.read.return_value=json.dumps({'choices':[choice]}).encode()
            with self.assertRaises(ValueError):extract_candidates('synthetic','demo',cloud_consent=True)

    def test_meta_provenance_and_old_model_identity_guess_are_guarded(self):
        with tempfile.TemporaryDirectory() as folder:
            ws=Workspace(Path(folder)/'meta.db')
            try:
                project=ws.create_project('Synthetic project')
                text='I will record the video.'
                record=ws.import_text([project],kind='text',external_id='synthetic',content=text)
                def extractor(section,name,mode):
                    return [dict(quote=text,kind='commitment',subject='Video',value='Record video',attribution='user',owner='user')]
                result=analyze_document(ws,project,record,provider='meta',cloud_consent=True,extractor=extractor)
                claim=ws.claims()[0]
                self.assertEqual(claim['proposer'],PROPOSER)
                self.assertEqual(claim['attribution'],'uncertain')
                self.assertEqual(result['new_count'],1)
                old=ws.propose_claim(project,record,start=0,end=len(text),kind='commitment',subject='Old guess',
                    value='Record video',attribution='user',owner='user',proposer=PROPOSER)
                with self.assertRaisesRegex(ValueError,'speaker'):
                    ws.review_claim(old,decision='accepted',actor='user')
            finally:ws.close()

    def test_background_meta_job_cannot_queue_without_consent(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs=AnalysisJobs(Path(folder)/'jobs.db')
            try:
                with self.assertRaisesRegex(ValueError,'Confirm'):
                    jobs.start('project','record','mixed',provider='meta')
                self.assertEqual(jobs.recent(),[])
            finally:
                jobs.close()
                jobs.pool.shutdown(wait=True)
