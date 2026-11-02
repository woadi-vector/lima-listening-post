import tempfile
import threading
import unittest
import sqlite3
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from lima_next.analysis_jobs import AnalysisJobs


class AnalysisJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = AnalysisJobs(Path(self.temp.name) / 'jobs.db')
        self.started = threading.Event()
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.jobs.close()
        self.jobs.pool.shutdown(wait=True)
        self.temp.cleanup()

    def fake_read(self, ws, project, record, mode, progress, cancelled):
        progress(0, 3)
        self.started.set()
        self.release.wait(3)
        return {'cancelled': cancelled(), 'section_errors': []}

    def test_duplicate_start_reconnects_to_same_active_job(self):
        with patch('lima_next.analysis_jobs.analyze_document', side_effect=self.fake_read):
            first = self.jobs.start('project', 'record', 'reference')
            self.assertTrue(self.started.wait(3))
            second = self.jobs.start('project', 'record', 'reference')
            self.assertEqual(first['id'], second['id'])
            self.assertEqual(self.jobs.get(first['id'])['total'], 3)
            self.release.set()
            self.jobs.pool.shutdown(wait=True)
            self.assertEqual(self.jobs.get(first['id'])['status'], 'completed')

    def test_cancel_is_visible_to_worker_and_saved_as_cancelled(self):
        with patch('lima_next.analysis_jobs.analyze_document', side_effect=self.fake_read):
            job = self.jobs.start('project', 'record', 'mixed')
            self.assertTrue(self.started.wait(3))
            self.jobs.cancel(job['id'])
            self.release.set()
            self.jobs.pool.shutdown(wait=True)
            self.assertEqual(self.jobs.get(job['id'])['status'], 'cancelled')

    def test_failed_worker_is_not_reported_as_success(self):
        with patch('lima_next.analysis_jobs.analyze_document', side_effect=RuntimeError('test')):
            job = self.jobs.start('project', 'record', 'mixed')
            self.jobs.pool.shutdown(wait=True)
            self.assertEqual(self.jobs.get(job['id'])['status'], 'failed')

    def test_interrupted_job_is_requeued_after_restart(self):
        self.jobs.close()
        self.jobs.pool.shutdown(wait=True)
        path = Path(self.temp.name)/'jobs.db'
        saved = {'id':'interrupted','project_id':'project','record_id':'record','mode':'reference',
                 'status':'running','processed':2,'total':4}
        with closing(sqlite3.connect(path)) as db:
            db.execute('INSERT INTO analysis_jobs VALUES (?,?)', (saved['id'], json.dumps(saved)))
            db.commit()
        with patch('lima_next.analysis_jobs.analyze_document', side_effect=self.fake_read):
            self.jobs = AnalysisJobs(path)
            self.assertTrue(self.started.wait(3))
            self.assertTrue(self.jobs.get('interrupted')['restarted'])
            self.release.set()
            self.jobs.pool.shutdown(wait=True)
        self.assertEqual(self.jobs.get('interrupted')['status'], 'completed')

    def test_cancelled_job_is_not_resumed_after_restart(self):
        with patch('lima_next.analysis_jobs.analyze_document', side_effect=self.fake_read):
            job = self.jobs.start('project','record','mixed')
            self.assertTrue(self.started.wait(3))
            self.jobs.cancel(job['id'])
            self.release.set()
            self.jobs.pool.shutdown(wait=True)
        self.jobs.close()
        with patch('lima_next.analysis_jobs.analyze_document') as reader:
            self.jobs = AnalysisJobs(Path(self.temp.name)/'jobs.db')
            self.assertEqual(self.jobs.get(job['id'])['status'], 'cancelled')
            reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
