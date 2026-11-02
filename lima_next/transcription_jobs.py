"""Durable local transcription drafts. Import into memory requires a separate action."""

import hashlib
import json
import math
import threading
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .recordings import decode_excerpt, transcribe_samples
from .workspace import Workspace


EXTENSIONS = {'.mp3', '.wav', '.m4a', '.mp4', '.webm', '.wma', '.mov', '.flac', '.ogg'}


def desktop_recordings():
    directory = Path.home()/'Desktop'
    if not directory.is_dir():
        return []
    return [{'path': str(p), 'name': p.name, 'bytes': p.stat().st_size}
            for p in sorted(directory.iterdir(), key=lambda p: p.name.casefold())
            if p.is_file() and p.suffix.lower() in EXTENSIONS]


def probe_duration(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('This recording has no audio stream')
        stream = container.streams.audio[0]
        duration = float(stream.duration*stream.time_base) if stream.duration else (
            container.duration/av.time_base if container.duration else None)
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Could not determine this recording’s duration')
    return duration


class TranscriptionJobs:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.root = self.db_path.parent/'recording-drafts'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='lima-transcribing')
        self.jobs, self.stops = {}, {}
        for folder in self.root.iterdir():
            manifest = folder/'draft.json'
            if folder.is_dir() and manifest.is_file():
                try:
                    job = json.loads(manifest.read_text(encoding='utf-8'))
                    if job['id'] != folder.name or len(folder.name) != 32:
                        continue
                    self.jobs[job['id']] = job
                    self.stops[job['id']] = threading.Event()
                    if job['status'] in {'queued', 'running'}:
                        job.update(status='interrupted', stage='Service restarted. Resume to continue.')
                        self._save(job)
                except (ValueError, KeyError, OSError):
                    continue

    def _save(self, job):
        folder = self.root/job['id']
        folder.mkdir(exist_ok=True)
        temporary = folder/'draft.tmp'
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        temporary.replace(folder/'draft.json')

    def _public(self, job):
        return {k: v for k, v in job.items() if k != 'segments'}

    def recent(self):
        with self.lock:
            return [self._public(job) for job in reversed(list(self.jobs.values()))]

    def get(self, job_id):
        with self.lock:
            return self._public(self.jobs[job_id])

    def start(self, path):
        try:
            path = Path(path.strip().strip('"')).expanduser().resolve(strict=True)
        except OSError as error:
            raise ValueError('Recording not found. Choose a Desktop file or paste its complete path.') from error
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError('Choose a supported audio or video recording')
        with self.lock:
            if any(j['status'] in {'queued', 'running'} for j in self.jobs.values()):
                raise ValueError('A recording is already being transcribed. Finish or stop it first.')
            stat = path.stat()
            job = {'id': uuid.uuid4().hex, 'path': str(path), 'name': path.name,
                   'bytes': stat.st_size, 'modified_ns': stat.st_mtime_ns,
                   'status': 'queued', 'stage': 'Preparing recording', 'processed': 0,
                   'total': 0, 'model': 'distil-large-v3', 'device': 'cpu', 'compute_type': 'int8',
                   'segments': [], 'has_preview': False}
            self.jobs[job['id']] = job
            self.stops[job['id']] = threading.Event()
            self._save(job)
            self.pool.submit(self._run, job['id'])
            return self._public(job)

    def resume(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] not in {'interrupted', 'stopped', 'failed'}:
                raise ValueError('This draft does not need resuming')
            if any(j['status'] in {'queued', 'running'} for j in self.jobs.values()):
                raise ValueError('Another recording is running')
            self.stops[job_id].clear()
            job.update(status='queued', stage='Resuming from saved progress')
            job.pop('error', None)
            self._save(job)
            self.pool.submit(self._run, job_id)
            return self._public(job)

    def stop(self, job_id):
        with self.lock:
            self.stops[job_id].set()

    def _stage(self, job_id, text):
        with self.lock:
            self.jobs[job_id]['stage'] = text
            self._save(self.jobs[job_id])

    def _run(self, job_id):
        try:
            with self.lock:
                job = self.jobs[job_id]
                job['status'] = 'running'
                self._save(job)
            path = Path(job['path'])
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (job['bytes'], job['modified_ns']):
                raise ValueError('The recording changed. Start a new draft to avoid mixing versions.')
            duration = job.get('duration') or probe_duration(path)
            if duration > 12*3600:
                raise ValueError('Choose a recording shorter than twelve hours')
            with self.lock:
                job.update(duration=duration, total=math.ceil(duration/116))
                self._save(job)
            self._stage(job_id, 'Loading cached local transcription model')
            if self.stops[job_id].is_set():
                with self.lock:
                    job.update(status='stopped', stage='Stopped. Saved progress can be resumed.')
                    self._save(job)
                return
            from faster_whisper import WhisperModel
            engine = WhisperModel(job['model'], device='cpu', compute_type='int8', local_files_only=True)
            for index in range(job['processed'], job['total']):
                if self.stops[job_id].is_set():
                    break
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (job['bytes'], job['modified_ns']):
                    raise ValueError('Recording changed while transcribing; saved progress was retained.')
                core_start, core_end = index*116, min((index+1)*116, duration)
                start, end = max(0, core_start-2), min(duration, core_end+2)
                self._stage(job_id, f'Transcribing part {index+1} of {job["total"]}')
                # Tiny final windows are decoded with one-second minimum, then clipped.
                samples = decode_excerpt(path, start, max(1, end-start))
                if len(samples)/16000 < core_end-start-0.25:
                    raise ValueError('Decoded audio ended before the expected window; progress retained.')
                segments = transcribe_samples(engine, samples, start, keep_start=core_start, keep_end=core_end)
                if index == 0:
                    import numpy as np
                    with wave.open(str(self.root/job_id/'preview.wav'), 'wb') as audio:
                        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                        audio.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
                with self.lock:
                    job['segments'].extend(segments)
                    job.update(processed=index+1, has_preview=True)
                    self._save(job)
            with self.lock:
                complete = job['processed'] == job['total']
                job.update(status='completed' if complete else 'stopped',
                           stage='Ready to review' if complete else 'Stopped. Saved progress can be resumed.')
                self._save(job)
        except Exception as error:
            with self.lock:
                self.jobs[job_id].update(status='failed', stage='Transcription stopped',
                    error=f'{type(error).__name__}: {error}. Saved progress remains; no transcript was imported.')
                self._save(self.jobs[job_id])

    def transcript(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            def clock(seconds):
                whole = int(seconds)
                return f'{whole//3600:02}:{whole//60%60:02}:{whole%60:02}'
            return '\n'.join(f'[{clock(s["start"])}] {s["text"]}' for s in job['segments'])

    def preview(self, job_id):
        with self.lock:
            if not self.jobs[job_id]['has_preview']:
                raise ValueError('Preview audio is not ready')
            return (self.root/job_id/'preview.wav').read_bytes()

    def import_transcript(self, job_id, project_id, mode, reviewed_text=None):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] != 'completed':
                raise ValueError('Finish transcription before importing a draft')
            raw = self.transcript(job_id)
            text = raw if reviewed_text is None else reviewed_text
            if not isinstance(text, str):
                raise ValueError('Reviewed transcript must be text')
            if not text.strip():
                raise ValueError('No speech was returned; there is no transcript to import')
            if mode not in {'mixed', 'work', 'reference'}:
                raise ValueError('Choose a source reading mode')
            source_uri = Path(job['path']).as_uri()
            identity = f'local-recording:{job["path"]}:{job["bytes"]}:{job["modified_ns"]}:{job["model"]}'
            # The stable external ID is metadata-derived, not a claim of byte identity.
            external_id = f'{job["name"]} · {hashlib.sha256(identity.encode()).hexdigest()[:12]}'
            if text != raw:
                external_id += ' · reviewed correction'
        ws = Workspace(self.db_path)
        try:
            record = ws.import_text([project_id], kind='transcript', external_id=external_id,
                                    content=text, source_uri=source_uri)
            ws.source_mode(project_id, record, mode)
            return record
        finally:
            ws.close()

    def close(self):
        with self.lock:
            for stop in self.stops.values():
                stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
