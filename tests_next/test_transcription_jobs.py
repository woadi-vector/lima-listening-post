import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lima_next.recordings import transcribe_samples
from lima_next.transcription_jobs import TranscriptionJobs
from lima_next.workspace import Workspace


class WordBoundaryTests(unittest.TestCase):
    def test_overlap_uses_word_midpoints_to_keep_each_boundary_word_once(self):
        words=[SimpleNamespace(start=0,end=1,word=' first'),SimpleNamespace(start=1,end=2,word=' second')]
        segment=SimpleNamespace(start=0,end=2,text='first second',words=words,avg_logprob=-.1,no_speech_prob=0)
        engine=SimpleNamespace(transcribe=lambda *a,**k:(iter([segment]),None))
        first=transcribe_samples(engine,None,0,keep_start=0,keep_end=1)
        second=transcribe_samples(engine,None,0,keep_start=1,keep_end=2)
        self.assertEqual(first[0]['text'],'first')
        self.assertEqual(second[0]['text'],'second')


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional audio array dependency unavailable')
class TranscriptionJobTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.db=self.root/'workspace.sqlite3'
        self.audio=self.root/'source.wav';self.audio.write_bytes(b'synthetic fixture')
        self.manager=TranscriptionJobs(self.db)
        self.patches=[patch('lima_next.transcription_jobs.probe_duration',return_value=3),
            patch('lima_next.transcription_jobs.decode_excerpt',side_effect=lambda path,start,seconds:np.zeros(round(seconds*16000),dtype=np.float32))]
        for p in self.patches:p.start()
        class Engine:
            def __init__(self,*args,**kwargs):
                assert kwargs==dict(device='cpu',compute_type='int8',local_files_only=True)
            def transcribe(self,*args,**kwargs):
                assert not kwargs['vad_filter']
                return iter([SimpleNamespace(start=0,end=1,text='Spoken words.',words=None,avg_logprob=-.1,no_speech_prob=0)]),None
        self.model=patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Engine)})
        self.model.start()

    def tearDown(self):
        self.manager.close();self.manager.pool.shutdown(wait=True)
        self.model.stop()
        for p in self.patches:p.stop()
        self.temp.cleanup()

    def wait(self,job_id):
        end=time.monotonic()+5
        while time.monotonic()<end:
            job=self.manager.get(job_id)
            if job['status'] not in {'queued','running'}:return job
            threading.Event().wait(.01)
        self.fail('Worker did not finish')

    def test_completed_draft_does_not_import_until_explicit_action(self):
        job=self.manager.start(str(self.audio))
        self.assertEqual(self.wait(job['id'])['status'],'completed')
        self.assertTrue(self.manager.get(job['id'])['has_preview'])
        self.assertIn('[00:00:00] Spoken words.',self.manager.transcript(job['id']))
        ws=Workspace(self.db)
        self.assertEqual(ws.snapshot()['records'],[])
        project=ws.create_project('Review first');ws.close()
        first=self.manager.import_transcript(job['id'],project,'reference')
        second=self.manager.import_transcript(job['id'],project,'reference')
        self.assertEqual(first,second)
        ws=Workspace(self.db)
        self.assertEqual(len(ws.snapshot()['records']),1)
        self.assertEqual(ws.claims(),[])
        ws.close()

    def test_drafts_survive_service_recreation(self):
        job=self.manager.start(str(self.audio));self.wait(job['id'])
        other=TranscriptionJobs(self.db)
        try:
            self.assertEqual(other.get(job['id'])['status'],'completed')
            self.assertIn('Spoken words',other.transcript(job['id']))
        finally:other.close();other.pool.shutdown(wait=True)

    def test_reviewed_correction_does_not_overwrite_machine_transcript(self):
        job=self.manager.start(str(self.audio));self.wait(job['id'])
        original=self.manager.transcript(job['id'])
        ws=Workspace(self.db);project=ws.create_project('Corrected');ws.close()
        record=self.manager.import_transcript(job['id'],project,'mixed','[00:00:00] Corrected spelling.')
        self.assertEqual(self.manager.transcript(job['id']),original)
        ws=Workspace(self.db)
        self.assertIn('Corrected spelling',ws.record(record)['content'])
        self.assertIn('reviewed correction',ws.record(record)['external_id'])
        ws.close()

    def test_invalid_recording_format_is_rejected(self):
        file=self.root/'private.txt';file.write_text('not audio')
        with self.assertRaises(ValueError):self.manager.start(str(file))

    def test_incomplete_draft_cannot_be_imported(self):
        with self.manager.lock:
            job=self.manager.start(str(self.audio))
            with self.assertRaises(ValueError):self.manager.import_transcript(job['id'],'missing','mixed')
        self.wait(job['id'])

    def test_model_failure_is_a_failed_draft_not_a_completed_transcript(self):
        with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('test failure')))}):
            job=self.manager.start(str(self.audio))
            result=self.wait(job['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['processed'],0)

    def test_resume_refuses_changed_original_recording(self):
        job=self.manager.start(str(self.audio));self.wait(job['id'])
        with self.manager.lock:
            self.manager.jobs[job['id']]['status']='stopped'
            self.manager._save(self.manager.jobs[job['id']])
        self.audio.write_bytes(b'changed original')
        self.manager.resume(job['id'])
        result=self.wait(job['id'])
        self.assertEqual(result['status'],'failed')
        self.assertIn('recording changed',result['error'].lower())

    def test_stop_then_resume_keeps_checkpoint_and_finishes_remaining_parts(self):
        started,release=threading.Event(),threading.Event()
        base=sys.modules['faster_whisper'].WhisperModel
        class Blocking(base):
            def transcribe(self,*args,**kwargs):
                if not started.is_set():
                    started.set();release.wait(3)
                return super().transcribe(*args,**kwargs)
        with patch('lima_next.transcription_jobs.probe_duration',return_value=235),patch.dict(
                sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Blocking)}):
            job=self.manager.start(str(self.audio))
            self.assertTrue(started.wait(3))
            self.manager.stop(job['id']);release.set()
            stopped=self.wait(job['id'])
            self.assertEqual(stopped['status'],'stopped')
            self.assertEqual(stopped['processed'],1)
            self.manager.resume(job['id'])
            completed=self.wait(job['id'])
        self.assertEqual(completed['status'],'completed')
        self.assertEqual(completed['processed'],3)
