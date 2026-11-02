"""Read-only Bee delivery into a durable local inbox. No outward actions."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .workspace import Workspace, fingerprint


class BeeConversationMissing(ValueError):
    """A specific queued conversation is no longer available, not a sign-in failure."""


def bee_command(args):
    cli = shutil.which('bee.cmd' if os.name == 'nt' else 'bee')
    if not cli and os.name == 'nt':
        path = os.path.join(os.environ.get('APPDATA', ''), 'npm', 'bee.cmd')
        cli = path if os.path.isfile(path) else None
    if not cli:
        raise ValueError('Bee command-line tool is unavailable. Install and sign in to Bee first.')
    try:
        result = subprocess.run([cli, *args, '--json'], capture_output=True, text=True,
                                encoding='utf-8', timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            if args[:2] in (['conversations','get'],['conversations','transcript']) and result.stderr.strip().casefold()=='conversation not found':
                raise BeeConversationMissing('A queued conversation is no longer available in Bee.')
            raise ValueError('Bee could not deliver updates. Check Bee sign-in and connection. A stale change cursor may require reconnecting.')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise ValueError('Bee delivery is unavailable or returned an unreadable response. Saved inbox items remain intact.') from error


class BeeInbox:
    def __init__(self, path, command=bee_command):
        self.path, self.command = path, command
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bee_delivery_missing (conversation_id TEXT PRIMARY KEY,noticed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bee_delivery_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
                    cursor TEXT, last_sync TEXT, error TEXT);
                INSERT OR IGNORE INTO bee_delivery_settings(id) VALUES (1);
                CREATE TABLE IF NOT EXISTS bee_pending (
                    conversation_id TEXT PRIMARY KEY, last_attempt TEXT);
                CREATE TABLE IF NOT EXISTS bee_inbox (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, content TEXT NOT NULL,
                    received_at TEXT NOT NULL, captured_at TEXT, imported_record TEXT,
                    raw_transcript TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bee_routing_rules (
                    project_id TEXT PRIMARY KEY REFERENCES projects(id),
                    phrases TEXT NOT NULL, mode TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bee_context_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
                    participation TEXT NOT NULL, relevance TEXT NOT NULL,
                    notes TEXT NOT NULL, reviewed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bee_context_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
                INSERT OR IGNORE INTO bee_context_settings VALUES (1,0);
                CREATE TABLE IF NOT EXISTS bee_context_suggestions (
                    item_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, result TEXT);
                CREATE TABLE IF NOT EXISTS bee_speaker_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
                    speaker TEXT, reviewed_at TEXT NOT NULL);
            ''')
            if 'last_attempt' not in {r[1] for r in db.execute('PRAGMA table_info(bee_pending)')}:
                db.execute('ALTER TABLE bee_pending ADD COLUMN last_attempt TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self):
        with self.connect() as db:
            settings = dict(db.execute('SELECT enabled,last_sync,error FROM bee_delivery_settings').fetchone())
            settings['items'] = [dict(row) for row in db.execute(
                'SELECT id,conversation_id,received_at,captured_at,length(content) characters,imported_record, '
                'EXISTS(SELECT 1 FROM bee_context_reviews r WHERE r.item_id=bee_inbox.id) context_checked '
                'FROM bee_inbox ORDER BY received_at DESC LIMIT 100')]
            settings['unavailable_in_bee'] = db.execute('SELECT count(*) FROM bee_delivery_missing').fetchone()[0]
            settings['waiting'] = db.execute('SELECT count(*) FROM bee_pending').fetchone()[0]
            settings['context_enabled'] = bool(db.execute('SELECT enabled FROM bee_context_settings').fetchone()[0])
            settings['context_reading'] = db.execute("SELECT count(*) FROM bee_context_suggestions WHERE status IN ('queued','running')").fetchone()[0]
            settings['context_ready'] = db.execute("SELECT count(*) FROM bee_context_suggestions WHERE status IN ('completed','partial')").fetchone()[0]
            return settings

    def enable(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Choose whether Bee delivery is enabled')
        with self.connect() as db:
            db.execute('UPDATE bee_delivery_settings SET enabled=? WHERE id=1', (int(enabled),))

    def sync(self):
        """Commit discovered IDs with cursor before fetching; failures remain retryable."""
        with self.connect() as db:
            settings = db.execute('SELECT * FROM bee_delivery_settings').fetchone()
        if not settings['enabled']:
            return
        try:
            args = ['changed'] + (['--cursor', settings['cursor']] if settings['cursor'] else [])
            changes = self.command(args)
            cursor = changes['meta']['next_cursor']
            if not isinstance(cursor, str) or not cursor:
                raise ValueError('Bee returned no usable change cursor. Delivery paused for retry.')
            ids = [str(c['id']) for c in changes['conversations']]
            if not settings['cursor']:
                # Limited initial history, plus changefeed since its bootstrap boundary.
                recent = self.command(['conversations', 'list', '--limit', '5'])
                ids.extend(str(c['id']) for c in recent['conversations'])
            if any(not cid.isdigit() for cid in ids):
                raise ValueError('Bee returned an invalid conversation identifier.')
            with self.connect() as db:
                db.executemany('INSERT OR IGNORE INTO bee_pending(conversation_id) VALUES (?)', [(cid,) for cid in ids])
                db.execute('UPDATE bee_delivery_settings SET cursor=? WHERE id=1', (cursor,))
            with self.connect() as db:
                pending = [row[0] for row in db.execute('SELECT conversation_id FROM bee_pending ORDER BY last_attempt LIMIT 20')]
            for cid in pending:
                with self.connect() as db:
                    db.execute('UPDATE bee_pending SET last_attempt=? WHERE conversation_id=?',
                               (datetime.now(timezone.utc).isoformat(), cid))
                try:
                    conversation = self.command(['conversations', 'get', cid])['conversation']
                    if str(conversation.get('state', '')).upper() not in {'COMPLETED', 'PROCESSED'}:
                        continue
                    transcript = self.command(['conversations', 'transcript', cid])['transcript']
                except BeeConversationMissing:
                    with self.connect() as db:
                        db.execute('INSERT OR IGNORE INTO bee_delivery_missing VALUES (?,?)',(cid,datetime.now(timezone.utc).isoformat()))
                        db.execute('DELETE FROM bee_pending WHERE conversation_id=?',(cid,))
                    continue
                if not transcript:
                    continue
                lines = []
                for utterance in transcript:
                    text, speaker = utterance['text'], utterance.get('speaker') or 'unknown'
                    if not isinstance(text, str) or not isinstance(speaker, str):
                        raise ValueError('Bee transcript contains unsupported fields.')
                    # Do not manufacture USER: identity from speaker names or text.
                    speaker = speaker.replace('\n', ' ').replace('\r', ' ')
                    lines.append(f"[Bee speaker {speaker} | {utterance.get('start', '?')}–{utterance.get('end', '?')}] "
                                 + text.replace('\r', ' ').replace('\n', ' '))
                content = '\n'.join(lines)
                if not content.strip():
                    continue
                key = fingerprint({'bee_conversation': cid, 'content': content})
                captured = conversation.get('start_time')
                captured_at = (datetime.fromtimestamp(captured / 1000, timezone.utc).isoformat()
                               if isinstance(captured, (int, float)) else None)
                with self.connect() as db:
                    db.execute('INSERT OR IGNORE INTO bee_inbox VALUES (?,?,?,?,?,NULL,?)',
                               (key, cid, content, datetime.now(timezone.utc).isoformat(), captured_at,
                                json.dumps(transcript, ensure_ascii=False)))
                    db.execute('DELETE FROM bee_pending WHERE conversation_id=?', (cid,))
            with self.connect() as db:
                db.execute('UPDATE bee_delivery_settings SET last_sync=?,error=NULL WHERE id=1',
                           (datetime.now(timezone.utc).isoformat(),))
        except (ValueError, KeyError, TypeError, OverflowError, OSError) as error:
            # Never store subprocess output, credentials, or source text in errors.
            message = str(error) if isinstance(error, ValueError) else 'Bee returned unexpected data. Delivery will retry.'
            with self.connect() as db:
                db.execute('UPDATE bee_delivery_settings SET error=? WHERE id=1', (message,))

    def item(self, item_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM bee_inbox WHERE id=?', (item_id,)).fetchone()
            if row is None:
                raise KeyError(item_id)
            result = dict(row)
        result['routes'] = self.suggest_routes(result['content'])
        with self.connect() as db:
            context = db.execute('SELECT * FROM bee_context_reviews WHERE item_id=? ORDER BY id DESC LIMIT 1', (item_id,)).fetchone()
        result['context_review'] = dict(context) if context else None
        result['speakers'] = sorted({u['speaker'] for u in json.loads(result['raw_transcript'])
                                     if isinstance(u.get('speaker'), str) and u['speaker']})
        with self.connect() as db:
            speaker = db.execute('SELECT speaker FROM bee_speaker_reviews WHERE item_id=? ORDER BY id DESC LIMIT 1', (item_id,)).fetchone()
            suggestion = db.execute('SELECT * FROM bee_context_suggestions WHERE item_id=?', (item_id,)).fetchone()
        result['wearer_speaker'] = speaker[0] if speaker else None
        result['context_suggestion'] = None
        if suggestion:
            from .context_suggestions import aggregate_context
            result['context_suggestion'] = {'status': suggestion['status'],
                **aggregate_context(json.loads(suggestion['payload']), suggestion['total'], result['wearer_speaker'])}
        return result

    def context_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Choose whether automatic context suggestions are enabled')
        with self.connect() as db:
            db.execute('UPDATE bee_context_settings SET enabled=? WHERE id=1', (int(enabled),))

    def confirm_speaker(self, item_id, speaker):
        item = self.item(item_id)
        if speaker is not None and speaker not in item['speakers']:
            raise ValueError('Choose a speaker present in this transcript, or leave identity unknown')
        with self.connect() as db:
            db.execute('INSERT INTO bee_speaker_reviews(item_id,speaker,reviewed_at) VALUES (?,?,?)',
                       (item_id, speaker, datetime.now(timezone.utc).isoformat()))

    def retry_context(self, item_id):
        self.item(item_id)
        with self.connect() as db:
            row = db.execute('SELECT status FROM bee_context_suggestions WHERE item_id=?', (item_id,)).fetchone()
            if row and row[0] in {'queued', 'running'}:
                raise ValueError('Context reading is already queued or running for this source')
            db.execute("INSERT INTO bee_context_suggestions(item_id,status,payload) VALUES (?,'queued','[]') "
                       "ON CONFLICT(item_id) DO UPDATE SET status='queued',payload='[]',processed=0,total=0,result=NULL", (item_id,))

    def review_context(self, item_id, participation, relevance, notes=''):
        if participation not in {'participant', 'ambient', 'mixed', 'uncertain'}:
            raise ValueError('Choose whether you participated in this conversation')
        if relevance not in {'work', 'reference', 'personal', 'unrelated', 'mixed', 'uncertain'}:
            raise ValueError('Choose how this conversation relates to your work')
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError('Use a note of at most 2,000 characters')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM bee_inbox WHERE id=?', (item_id,)).fetchone():
                raise ValueError('Choose an existing Bee inbox item')
            db.execute('INSERT INTO bee_context_reviews(item_id,participation,relevance,notes,reviewed_at) VALUES (?,?,?,?,?)',
                       (item_id, participation, relevance, notes.strip(), datetime.now(timezone.utc).isoformat()))
        return {'ok': True}

    def routing_rules(self):
        with self.connect() as db:
            return [dict(row, phrases=json.loads(row['phrases'])) for row in db.execute(
                'SELECT r.*,p.name FROM bee_routing_rules r JOIN projects p ON p.id=r.project_id ORDER BY p.name')]

    def save_rule(self, project_id, phrases, mode):
        if mode not in {'mixed', 'reference', 'work'}:
            raise ValueError('Choose a reading mode')
        if (not isinstance(phrases, list) or len(phrases) > 12 or
                any(not isinstance(p, str) or not 3 <= len(p.strip()) <= 80 or '\n' in p or '\r' in p for p in phrases)):
            raise ValueError('Use up to twelve phrases, each 3–80 characters, one per line.')
        phrases = list(dict.fromkeys(p.strip().casefold() for p in phrases))
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise ValueError('Choose an existing project')
            if not phrases:
                db.execute('DELETE FROM bee_routing_rules WHERE project_id=?', (project_id,))
            else:
                db.execute('INSERT INTO bee_routing_rules VALUES (?,?,?) ON CONFLICT(project_id) '
                           'DO UPDATE SET phrases=excluded.phrases,mode=excluded.mode',
                           (project_id, json.dumps(phrases), mode))

    def suggest_routes(self, content):
        """Transparent phrase matches, not proof of relevance or participation."""
        results = []
        for rule in self.routing_rules():
            matches = []
            # Strip our generated speaker/timing labels; match only spoken text.
            for line in content.splitlines():
                spoken = re.sub(r'^\[Bee speaker .*?\] ', '', line)
                for phrase in rule['phrases']:
                    hit = re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', spoken, re.I)
                    if hit and not any(m['phrase'] == phrase for m in matches):
                        low, high = max(0, hit.start()-70), min(len(spoken), hit.end()+100)
                        matches.append({'phrase': phrase, 'quote': spoken[low:high]})
            if matches:
                results.append({'project_id': rule['project_id'], 'name': rule['name'],
                                'mode': rule['mode'], 'matches': matches})
        return results

    def import_item(self, item_id, project_id, mode):
        if mode not in {'mixed', 'reference', 'work'}:
            raise ValueError('Choose how Lima should read this source')
        item = self.item(item_id)
        ws = Workspace(self.path)
        try:
            record = ws.import_text([project_id], kind='bee_export',
                external_id='Bee conversation ' + item['conversation_id'], content=item['content'],
                captured_at=item['captured_at'])
            ws.source_mode(project_id, record, mode)
        finally:
            ws.close()
        with self.connect() as db:
            db.execute('UPDATE bee_inbox SET imported_record=? WHERE id=?', (record, item_id))
        return {'record_id': record}


class BeeDelivery:
    def __init__(self, path):
        self.inbox = BeeInbox(path)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='lima-bee')
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                self.inbox.sync()
            except Exception:
                # Keep the worker alive after local transient failures.
                pass
            self.wake.wait(60)
            self.wake.clear()

    def close(self):
        self.stop.set()
        self.wake.set()
        self.thread.join(timeout=2)
