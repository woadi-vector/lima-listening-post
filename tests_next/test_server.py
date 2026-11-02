import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from lima_next.server import MissionServer, load_demo
from lima_next.workspace import Workspace


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        self.server = MissionServer(("127.0.0.1", 0), self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, payload=None, token=True, origin=True, headers=None):
        auth = {"X-Lima-Token": self.server.token} if token else {}
        if origin:
            auth["Origin"] = self.server.origin
        auth.update(headers or {})
        body = None if payload is None else json.dumps(payload).encode()
        if body:
            auth["Content-Type"] = "application/json"
        return self.opener.open(Request(self.server.origin + path, data=body, headers=auth))

    def test_import_review_and_restart_persist_real_http_workflow(self):
        with self.request("/api/projects", {"name": "HTTP project"}) as response:
            project = json.load(response)["id"]
        with self.request("/api/import", {"project_ids": [project], "kind": "text",
                                          "external_id": "chat", "content": "USER: I will finish the video."}) as response:
            record = json.load(response)["id"]
        with self.request("/api/claims", {"project_id": project, "record_id": record,
                                          "start": 0, "end": 30, "kind": "deliverable", "subject": "Video",
                                          "value": "Finish video", "attribution": "user", "owner": "user"}) as response:
            claim = json.load(response)["id"]
        with self.request("/api/review", {"claim_id": claim, "decision": "accepted"}):
            pass
        with self.request("/api/state") as response:
            state = json.load(response)
        self.assertEqual(state["projects"][0]["work"][0]["subject"], "Video")
        ws = Workspace(self.path)
        try:
            self.assertEqual(ws.snapshot()["projects"][0]["work"][0]["subject"], "Video")
        finally:
            ws.close()

    def test_cross_origin_and_missing_token_requests_are_denied(self):
        for options in ({"token": False}, {"origin": False},
                        {"headers": {"Origin": "https://example.com"}},
                        {"headers": {"Host": "example.com"}}):
            with self.assertRaises(HTTPError) as error:
                self.request("/api/projects", {"name": "Unauthorized"}, **options)
            self.assertEqual(error.exception.code, 403)

    def test_cross_site_session_fetch_is_denied(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/session", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(error.exception.code, 403)

    def test_brief_requires_session_and_returns_saved_snapshot(self):
        with self.assertRaises(HTTPError):
            self.request('/api/brief',token=False)
        with self.request('/api/brief') as response:
            self.assertIsNone(json.load(response))
        with self.request('/api/brief',{'as_of':'2026-10-30'}) as response:
            prepared=json.load(response)
        with self.request('/api/brief') as response:
            saved=json.load(response)
        self.assertEqual(prepared['id'],saved['id'])
        self.assertFalse(saved['external_execution'])

    def test_nightly_schedule_requires_access_and_saves_settings(self):
        with self.assertRaises(HTTPError):
            self.request('/api/brief-schedule',token=False)
        with self.request('/api/brief-schedule',{'enabled':False,'at_time':'21:30'}) as response:
            saved=json.load(response)
        self.assertEqual(saved['at_time'],'21:30')
        self.assertEqual(saved['timezone'],'America/Chicago')
        with self.request('/api/brief-schedule') as response:
            self.assertEqual(json.load(response)['at_time'],'21:30')
        with self.assertRaises(HTTPError) as error:
            self.request('/api/brief-schedule',{'enabled':True,'at_time':'25:00'})
        self.assertEqual(error.exception.code,400)

    def test_local_draft_routes_require_access_and_review_exact_version(self):
        with self.assertRaises(HTTPError):
            self.request('/api/drafts',token=False)
        with self.request('/api/demo',{}):pass
        with self.request('/api/state') as response:
            project=json.load(response)['projects'][0]['id']
        with self.request('/api/drafts',{'project_id':project,'kind':'update','as_of':'2026-11-01'}) as response:
            draft=json.load(response)
        with self.request('/api/draft-review',{'draft_id':draft['id'],'version_id':draft['version_id'],'decision':'approved'}) as response:
            approved=json.load(response)
        self.assertEqual(approved['status'],'approved')
        self.assertFalse(approved['external_execution'])
        with self.request('/api/drafts/'+draft['id']) as response:
            self.assertEqual(json.load(response)['version_id'],draft['version_id'])

    def test_draft_batch_retains_existing_drafts_on_repeat(self):
        with self.request('/api/demo',{}):pass
        with self.request('/api/draft-batch',{'as_of':'2026-11-01'}) as response:
            first=json.load(response)
        with self.request('/api/draft-batch',{'as_of':'2026-11-01'}) as response:
            repeated=json.load(response)
        self.assertEqual(first['created'],2)
        self.assertEqual(repeated['created'],0)
        self.assertEqual(repeated['retained'],2)
        with self.request('/api/draft-batch') as response:
            self.assertEqual(json.load(response)['draft_ids'],first['draft_ids'])

    def test_memory_search_requires_session_and_labels_evidence(self):
        with self.assertRaises(HTTPError):
            self.request('/api/memory-search',{'query':'video'},token=False)
        with self.request('/api/demo',{}):pass
        with self.request('/api/memory-search',{'query':'video'}) as response:
            result=json.load(response)
        self.assertTrue(result['results'])
        self.assertTrue(all('status' in hit for hit in result['results']))

    def test_parallel_dashboard_reads_do_not_lock_the_workspace(self):
        def read(route):
            with self.request(route) as response:
                return response.status
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(read, ['/api/state','/api/bee','/api/analysis']*4))
        self.assertEqual(results,[200]*12)

    def test_backups_require_session_access_and_download_as_a_database(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/backup", token=False)
        self.assertEqual(error.exception.code, 403)
        with self.request("/api/demo", {}):
            pass
        with self.request("/api/backup") as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertEqual(response.read(16), b"SQLite format 3\x00")

    def test_recording_routes_require_local_session_access(self):
        for route in ('/api/recordings','/api/transcriptions'):
            with self.assertRaises(HTTPError) as error:
                self.request(route,token=False)
            self.assertEqual(error.exception.code,403)
        with self.request('/api/transcriptions') as response:
            self.assertEqual(json.load(response),[])

    def test_bee_import_can_queue_reading_without_accepting_claims(self):
        with self.request('/api/projects', {'name':'Bee HTTP test'}) as response:
            project=json.load(response)['id']
        with self.server.bee.inbox.connect() as db:
            db.execute('INSERT INTO bee_inbox VALUES (?,?,?,?,?,NULL,?)',
                       ('bee-test','123','[Bee speaker speaker_1 | 0–1] A useful learning point.',
                        '2026-10-30T00:00:00Z',None,'[]'))
        payload={'item_id':'bee-test','project_id':project,'mode':'reference'}
        with patch.object(self.server.analysis,'start',return_value={'id':'job','status':'queued'}) as start:
            with self.request('/api/bee-import',payload) as response:
                self.assertNotIn('analysis_job',json.load(response))
            start.assert_not_called()
            with self.request('/api/bee-import',{**payload,'analyze':True}) as response:
                result=json.load(response)
            start.assert_called_once_with(project,result['record_id'],'reference')
            self.assertEqual(result['analysis_job']['status'],'queued')
        with patch.object(self.server.analysis,'start',side_effect=ValueError('Queue full')):
            with self.request('/api/bee-import',{**payload,'analyze':True}) as response:
                failed=json.load(response)
            self.assertEqual(failed['analysis_error'],'Queue full')
            self.assertEqual(failed['record_id'],result['record_id'])
        ws=Workspace(self.path)
        try:
            self.assertEqual(ws.claims(),[])
            self.assertEqual(len(ws.snapshot()['records']),1)
        finally:
            ws.close()

    def test_static_ui_and_demo_are_available_without_execution_routes(self):
        with self.request("/") as response:
            self.assertIn(b"Mission Control", response.read())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        for _ in range(2):
            with self.request("/api/demo", {}):
                pass
        with self.request("/api/state") as response:
            state = json.load(response)
        self.assertEqual(len(state["records"]), 2)
        self.assertEqual(len(state["projects"]), 1)
        self.assertEqual(len(state["projects"][0]["work"]), 1)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/send", {})
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
