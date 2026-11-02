"""Bounded local recording comparison, separate from project memory and legacy code."""

import difflib
import hashlib
import html
import json
import math
import re
import wave
from datetime import UTC, datetime
from pathlib import Path


def validate_window(start, seconds):
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, seconds)):
        raise ValueError('Excerpt times must be finite numbers')
    if start < 0 or not 1 <= seconds <= 120:
        raise ValueError('Choose a nonnegative start and an excerpt between 1 and 120 seconds')


def decode_excerpt(path, start=0, seconds=60):
    """Decode only a selected window, not a full multi-hour recording into memory."""
    validate_window(start, seconds)
    import av
    import numpy as np
    pieces = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('This file has no audio stream')
        stream = container.streams.audio[0]
        base = float(stream.start_time * stream.time_base) if stream.start_time is not None else 0.0
        if start:
            container.seek(int((start + base) * av.time_base), backward=True)
        resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
        end = start + seconds
        reached_end = False
        def retain(frame):
            if frame.pts is None:
                raise ValueError('Audio timestamps are missing; cannot align this excerpt reliably')
            frame_start = float(frame.pts * frame.time_base) - base
            samples = frame.to_ndarray().reshape(-1)
            low = max(0, round((start-frame_start)*16000))
            high = min(len(samples), round((end-frame_start)*16000))
            if high > low:
                pieces.append(samples[low:high].copy())
            return frame_start + len(samples)/16000 >= end
        for source_frame in container.decode(stream):
            for frame in resampler.resample(source_frame):
                reached_end = retain(frame) or reached_end
            if reached_end:
                break
        if not reached_end:
            for frame in resampler.resample(None):
                retain(frame)
    if not pieces:
        raise ValueError('No audio was found at the selected time')
    samples = np.concatenate(pieces).astype(np.float32)
    return samples[:round(seconds*16000)]


def old_excerpt(text, start, seconds):
    """Conservative timestamp alignment; generated report notes are never compared."""
    marker = re.search(r'^## Full Transcript\s*$', text, re.M)
    if marker:
        text = text[marker.end():]
    elif re.match(r'\A---.*?^session_id:', text, re.M | re.S):
        return '', 'This report has no Full Transcript section; its generated summary was excluded.'
    stamps = list(re.finditer(r'\[(\d{1,3}):(\d{2})(?::(\d{2}))?\]', text))
    selected = []
    for i, match in enumerate(stamps):
        parts = [int(x) for x in match.groups() if x is not None]
        time = parts[0]*60+parts[1] if len(parts)==2 else parts[0]*3600+parts[1]*60+parts[2]
        fragment = text[match.end():stamps[i+1].start() if i+1<len(stamps) else len(text)].strip()
        if fragment and start <= time < start+seconds:
            selected.append(fragment)
    if not selected:
        return '', 'No timestamp-aligned old text was found for this excerpt. Do not compare the whole report against this sample.'
    return ' '.join(selected), 'Aligned using old transcript timestamps, which may themselves be inaccurate. Listen to confirm alignment.'


def render_difference(old, new):
    """A textual change display, deliberately not labeled WER or accuracy."""
    first, second = old.split(), new.split()
    left, right = [], []
    for operation, a, b, c, d in difflib.SequenceMatcher(a=first, b=second, autojunk=False).get_opcodes():
        old_part = html.escape(' '.join(first[a:b]))
        new_part = html.escape(' '.join(second[c:d]))
        left.append(old_part if operation=='equal' else f'<mark>{old_part}</mark>')
        right.append(new_part if operation=='equal' else f'<mark>{new_part}</mark>')
    return ' '.join(left), ' '.join(right)


def transcribe_samples(engine, samples, start, *, keep_start=None, keep_end=None):
    segments, info = engine.transcribe(samples, language='en', beam_size=5,
        vad_filter=False, condition_on_previous_text=False, word_timestamps=True)
    transcript = []
    for segment in segments:
        text = segment.text.strip()
        low, high = start + segment.start, start + segment.end
        if keep_start is not None:
            words = getattr(segment, 'words', None)
            if words:
                words = [w for w in words if keep_start <= start+(w.start+w.end)/2 < keep_end]
                if not words:
                    continue
                text = ''.join(w.word for w in words).strip()
                low, high = start+words[0].start, start+words[-1].end
            elif not keep_start <= (low+high)/2 < keep_end:
                continue
        transcript.append({'start': low, 'end': high, 'text': text,
                           'avg_logprob': segment.avg_logprob,
                           'no_speech_prob': segment.no_speech_prob})
    return transcript


def compare_recording(recording, *, old_report=None, start=0, seconds=60,
                      output, model='distil-large-v3', model_factory=None, progress=print):
    """No model download, no phrase suppression, no LLM rewriting or memory import."""
    validate_window(start, seconds)
    recording = Path(recording).resolve(strict=True)
    if not recording.is_file():
        raise ValueError('Choose a recording file')
    old_text = Path(old_report).read_text(encoding='utf-8-sig') if old_report else None
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a new output folder so earlier results cannot be overwritten')
    progress('Decoding the selected audio excerpt…')
    samples = decode_excerpt(recording, start, seconds)
    progress('Loading the cached local model (CPU, int8)…')
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    engine = model_factory(model, device='cpu', compute_type='int8', local_files_only=True)
    progress('Transcribing the excerpt…')
    transcript = transcribe_samples(engine, samples, start)
    fresh = ' '.join(segment['text'] for segment in transcript)
    previous, alignment = old_excerpt(old_text, start, len(samples)/16000) if old_text is not None else (
        '', 'No old transcript was supplied.')
    left, right = render_difference(previous, fresh) if previous else ('', html.escape(fresh))
    output.mkdir(parents=True, exist_ok=False)
    import numpy as np
    pcm = (np.clip(samples,-1,1)*32767).astype('<i2')
    with wave.open(str(output/'excerpt.wav'),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(pcm.tobytes())
    metadata = {'created_at': datetime.now(UTC).isoformat(), 'recording': str(recording),
        'old_report': str(Path(old_report).resolve()) if old_report else None,
        'old_report_text_sha256': hashlib.sha256(old_text.encode('utf-8')).hexdigest() if old_text is not None else None,
        'recording_bytes': recording.stat().st_size, 'excerpt_start': start,
        'excerpt_seconds': len(samples)/16000, 'excerpt_pcm_sha256': hashlib.sha256(pcm.tobytes()).hexdigest(),
        'model': model, 'device': 'cpu', 'compute_type': 'int8', 'vad_filter': False,
        'condition_on_previous_text': False, 'phrase_filter': False, 'speaker_attribution': 'unverified',
        'alignment_note': alignment, 'segments': transcript, 'old_excerpt': previous,
        'accuracy': 'Not measured. Neither transcript is a human-verified reference.'}
    (output/'comparison.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'transcript.txt').write_text('\n'.join(
        f"[{s['start']:.2f}–{s['end']:.2f}] {s['text']}" for s in transcript),encoding='utf-8')
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lima recording comparison</title><style>body{{font:16px/1.65 system-ui;max-width:1100px;margin:45px auto;padding:0 24px;background:#f5f5ee;color:#172b29}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:30px}}mark{{background:#f5dfac}}p{{overflow-wrap:anywhere}}audio{{width:100%}}small{{color:#68736a}}@media(max-width:700px){{.columns{{grid-template-columns:1fr}}}}</style>
<h1>Listen, then compare.</h1><p>{start:.1f}–{start+len(samples)/16000:.1f} seconds · {html.escape(model)} · local CPU</p>
<audio controls src="excerpt.wav"></audio><p>{html.escape(alignment)}</p>
<div class="columns"><section><h2>Old transcript</h2><p>{left or 'No aligned old passage available.'}</p></section><section><h2>Fresh transcript</h2><p>{right or 'No speech returned.'}</p></section></div>
<p><small>Highlights show textual differences, not which version is correct. Accuracy requires listening and a human-checked reference. No speaker identity was inferred, no summary was generated, and nothing was added to project memory.</small></p></html>'''
    (output/'comparison.html').write_text(page,encoding='utf-8')
    progress('Comparison saved. Listen to the excerpt before judging either transcript.')
    return metadata
