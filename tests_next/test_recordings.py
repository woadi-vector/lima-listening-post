import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lima_next.recordings import compare_recording, decode_excerpt, old_excerpt, render_difference, validate_window


class RecordingComparisonTests(unittest.TestCase):
    def test_old_report_summary_is_excluded_and_matching_window_is_selected(self):
        text='## Executive Summary\nWrong summary.\n## Full Transcript\n[00:00] First. [01:00] Second. [01:05] Third.'
        result,note=old_excerpt(text,60,10)
        self.assertEqual(result,'Second. Third.')
        self.assertNotIn('Wrong summary',result)

    def test_unaligned_old_text_is_not_presented_as_a_matching_excerpt(self):
        result,note=old_excerpt('Text with no timestamps.',0,60)
        self.assertEqual(result,'')
        self.assertIn('No timestamp-aligned',note)

    def test_diff_escapes_untrusted_source_markup(self):
        left,right=render_difference('<script>old</script>','<img>new')
        self.assertNotIn('<script>',left)
        self.assertNotIn('<img>',right)

    def test_window_limits(self):
        for start,seconds in ((-1,60),(0,121),(float('nan'),60),(0,0)):
            with self.assertRaises(ValueError):validate_window(start,seconds)

    @unittest.skipUnless(importlib.util.find_spec('av') and importlib.util.find_spec('numpy'), 'Optional audio dependencies unavailable')
    def test_decoder_reads_exact_window_and_comparison_keeps_paths_unchanged(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            audio=folder/'original.wav'
            samples=np.concatenate([np.zeros(16000),np.full(16000,.5),np.zeros(16000)]).astype(np.float32)
            with wave.open(str(audio),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
                stream.writeframes((samples*32767).astype('<i2').tobytes())
            before=audio.read_bytes()
            excerpt=decode_excerpt(audio,1,1)
            self.assertEqual(len(excerpt),16000)
            self.assertAlmostEqual(float(excerpt.mean()),.5,places=3)
            class Engine:
                def __init__(self,*args,**kwargs):
                    self.kwargs=kwargs
                    assert kwargs['local_files_only'] is True
                    assert kwargs['compute_type']=='int8'
                def transcribe(self,samples,**kwargs):
                    assert kwargs['vad_filter'] is False
                    return iter([SimpleNamespace(start=0,end=1,text='Fresh words',avg_logprob=-.2,no_speech_prob=.01)]),None
            report=folder/'old.md';report.write_text('## Full Transcript\n[00:01] Old words.',encoding='utf-8')
            result=compare_recording(audio,old_report=report,start=1,seconds=1,output=folder/'result',
                                     model_factory=Engine,progress=lambda s:None)
            self.assertEqual(result['segments'][0]['start'],1)
            self.assertEqual(result['old_excerpt'],'Old words.')
            self.assertTrue((folder/'result/comparison.html').exists())
            self.assertEqual(audio.read_bytes(),before)
            with self.assertRaises(ValueError):
                compare_recording(audio,output=folder/'result',model_factory=Engine,progress=lambda s:None)


if __name__=='__main__':unittest.main()
