"""A single local inference worker, with reconnectable progress for browser tabs."""

import threading
import uuid
import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

from .interpret import analyze_document
from .workspace import Workspace


class AnalysisJobs:
    def __init__(self, db_path):
        self.path = db_path
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lima-reading")
        self.jobs = {}
        self.stops = {}
        self.closing = False
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS analysis_jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            saved = db.execute('SELECT payload FROM analysis_jobs ORDER BY rowid DESC LIMIT 30').fetchall()
            db.commit()
        for (payload,) in reversed(saved):
            job = json.loads(payload)
            self.jobs[job['id']] = job
            self.stops[job['id']] = threading.Event()
        for job in self.jobs.values():
            if job['status'] in {'running', 'queued'}:
                job.update(status='queued', processed=0, total=0, restarted=True)
                self._save(job['id'])
                self.pool.submit(self._run, job['id'])

    def _save(self, job_id):
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.execute('INSERT INTO analysis_jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (job_id, json.dumps(self.jobs[job_id])))
            db.commit()

    def start(self, project_id, record_id, mode, *, provider='ollama', cloud_consent=False, purpose='updates', memory_consent=False):
        if purpose not in {'updates','ideas','reconciliation'}:
            raise ValueError('Choose updates, ideas or reconciliation')
        if purpose in {'ideas','reconciliation'} and (provider != 'meta' or cloud_consent is not True or memory_consent is not True):
            raise ValueError('Confirm sharing the selected source and reviewed project context with Meta first.')
        if provider not in {'ollama', 'meta'}:
            raise ValueError('Choose a supported interpretation provider')
        if provider == 'meta':
            from .meta_provider import ready
            if cloud_consent is not True:
                raise ValueError('Confirm sending this selected source and project name to Meta first.')
            if not ready():
                raise ValueError('Meta Model API key is unavailable to Lima.')
        with self.lock:
            if self.closing:
                raise ValueError('Lima is shutting down. Retry when it is running again.')
            active = [j for j in self.jobs.values() if j["status"] in {"queued", "running"}]
            for job in active:
                if (job["project_id"], job["record_id"], job["mode"], job.get('provider','ollama'), job.get('purpose','updates')) == (project_id, record_id, mode, provider, purpose):
                    return dict(job)
            if len(active) >= 3:
                raise ValueError("Three sources are already queued. Wait for one to finish.")
            for key in list(self.jobs):
                if len(self.jobs) < 30:
                    break
                if self.jobs[key]["status"] not in {"queued", "running"}:
                    self.jobs.pop(key)
                    self.stops.pop(key)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "project_id": project_id, "record_id": record_id,
                   "mode": mode, "status": "queued", "processed": 0, "total": 0,
                   'purpose':purpose, 'memory_consent':memory_consent is True, 'provider': provider, 'cloud_consent': cloud_consent is True and provider == 'meta'}
            self.jobs[job_id] = job
            self.stops[job_id] = threading.Event()
            self._save(job_id)
            self.pool.submit(self._run, job_id)
            return dict(job)

    def _run(self, job_id):
        ws = None
        try:
            with self.lock:
                job = self.jobs[job_id]
                job["status"] = "running"
                self._save(job_id)
                project, record, mode = job["project_id"], job["record_id"], job["mode"]
            ws = Workspace(self.path)
            def update(processed, total):
                with self.lock:
                    self.jobs[job_id].update(processed=processed, total=total)
                    self._save(job_id)
            options = ({'provider':'meta','cloud_consent':job.get('cloud_consent',False)}
                       if job.get('provider') == 'meta' else {})
            if job.get('purpose') == 'reconciliation':
                from .muse_reconciliation import analyze
                result = analyze(ws, project, record, cloud_consent=job.get('cloud_consent'), memory_consent=job.get('memory_consent'), progress=update, cancelled=self.stops[job_id].is_set)
            elif job.get('purpose') == 'ideas':
                from .ideas import analyze
                result = analyze(ws, project, record, cloud_consent=job.get('cloud_consent'), memory_consent=job.get('memory_consent'), progress=update, cancelled=self.stops[job_id].is_set)
            else:
                result = analyze_document(ws, project, record, mode=mode, progress=update,
                                          cancelled=self.stops[job_id].is_set, **options)
            with self.lock:
                status = "cancelled" if result["cancelled"] else "partial" if result["section_errors"] else "completed"
                self.jobs[job_id].update(status=status, result=result)
                if self.closing and result['cancelled'] and not job.get('user_cancelled'):
                    self.jobs[job_id]['status'] = 'queued'
                self._save(job_id)
        except Exception:
            with self.lock:
                self.jobs[job_id].update(status="failed", error="Reading stopped unexpectedly. Saved suggestions remain available; retry this source.")
                self._save(job_id)
        finally:
            if ws:
                ws.close()

    def get(self, job_id):
        with self.lock:
            return dict(self.jobs[job_id])

    def recent(self):
        with self.lock:
            return [dict(j) for j in self.jobs.values()]

    def cancel(self, job_id):
        with self.lock:
            self.stops[job_id].set()
            self.jobs[job_id]['user_cancelled'] = True
            self.jobs[job_id]['status'] = 'cancelled'
            self._save(job_id)

    def close(self):
        with self.lock:
            self.closing = True
            for event in self.stops.values():
                event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
