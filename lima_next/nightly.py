"""Lima's local nightly preparation, independent of desktop chat automations."""

import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .briefing import prepare_brief
from .workspace import Workspace
from . import drafts


class NightlyBrief:
    def __init__(self, path, prepare=prepare_brief):
        self.path, self.prepare = path, prepare
        ws = Workspace(path)
        try:
            ws.db.executescript('''
                CREATE TABLE IF NOT EXISTS brief_schedule (
                    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
                    at_time TEXT NOT NULL, timezone TEXT NOT NULL);
                INSERT OR IGNORE INTO brief_schedule(id,enabled,at_time,timezone) VALUES (1,0,'18:00','America/Chicago');
                CREATE TABLE IF NOT EXISTS brief_schedule_runs (
                    day TEXT PRIMARY KEY, status TEXT NOT NULL, attempted_at TEXT NOT NULL,
                    brief_id TEXT, error TEXT);
            ''')
            if 'prepare_drafts' not in {r[1] for r in ws.db.execute('PRAGMA table_info(brief_schedule)')}:
                with ws.db:
                    ws.db.execute('ALTER TABLE brief_schedule ADD COLUMN prepare_drafts INTEGER NOT NULL DEFAULT 0')
        finally:
            ws.close()
        self.lock = threading.Lock()

    def configure(self, enabled, at_time, prepare_drafts=None):
        if type(enabled) is not bool or not isinstance(at_time, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', at_time):
            raise ValueError('Choose an enabled setting and valid daily time (HH:MM).')
        if prepare_drafts is not None and type(prepare_drafts) is not bool:
            raise ValueError('Choose whether nightly preparation should include local drafts')
        ws = Workspace(self.path)
        try:
            with ws.db:
                ws.db.execute('UPDATE brief_schedule SET enabled=?,at_time=? WHERE id=1', (int(enabled), at_time))
                if prepare_drafts is not None:
                    ws.db.execute('UPDATE brief_schedule SET prepare_drafts=? WHERE id=1', (int(prepare_drafts),))
        finally:
            ws.close()

    def state(self, now=None):
        now = now or datetime.now(timezone.utc)
        ws = Workspace(self.path)
        try:
            settings = dict(ws.db.execute('SELECT * FROM brief_schedule').fetchone())
            last = ws.db.execute('SELECT * FROM brief_schedule_runs ORDER BY day DESC LIMIT 1').fetchone()
            batch = drafts.latest_batch(ws)
        finally:
            ws.close()
        local = now.astimezone(ZoneInfo(settings['timezone']))
        hour, minute = map(int, settings['at_time'].split(':'))
        due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if last and last['day'] == local.date().isoformat() and last['status'] == 'prepared':
            due += timedelta(days=1)
        settings.update(last_run=dict(last) if last else None,
                        last_batch=batch,
                        next_due=due.isoformat() if settings['enabled'] else None)
        return settings

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('An explicit timezone is required')
        if not self.lock.acquire(blocking=False):
            return
        ws = None
        claimed = False
        day = None
        try:
            ws = Workspace(self.path)
            # Claim the day atomically; a short persisted lease permits crash recovery.
            with ws.db:
                ws.db.execute('BEGIN IMMEDIATE')
                settings = ws.db.execute('SELECT * FROM brief_schedule').fetchone()
                local = now.astimezone(ZoneInfo(settings['timezone']))
                if not settings['enabled'] or local.strftime('%H:%M') < settings['at_time']:
                    return
                day = local.date().isoformat()
                run = ws.db.execute('SELECT * FROM brief_schedule_runs WHERE day=?', (day,)).fetchone()
                if run and (run['status'] == 'prepared' or
                            run['status'] == 'preparing' and now - datetime.fromisoformat(run['attempted_at']) < timedelta(minutes=5)):
                    return
                ws.db.execute('INSERT INTO brief_schedule_runs VALUES (?,\'preparing\',?,NULL,NULL) '
                              'ON CONFLICT(day) DO UPDATE SET status=excluded.status,attempted_at=excluded.attempted_at,error=NULL',
                              (day, now.astimezone(timezone.utc).isoformat()))
                claimed = True
            brief = self.prepare(ws, day)
            if settings['prepare_drafts']:
                drafts.prepare_all(ws, day)
            with ws.db:
                ws.db.execute('UPDATE brief_schedule_runs SET status=\'prepared\',brief_id=?,error=NULL WHERE day=?',
                              (brief['id'], day))
        except Exception:
            if ws and claimed:
                with ws.db:
                    ws.db.execute('UPDATE brief_schedule_runs SET status=\'failed\',error=? WHERE day=?',
                                  ('Nightly preparation could not finish. Lima will retry while running.', day))
            else:
                raise
        finally:
            if ws:
                ws.close()
            self.lock.release()


class NightlyWorker:
    def __init__(self, path):
        self.schedule = NightlyBrief(path)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='lima-nightly')
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                self.schedule.tick()
            except Exception:
                pass
            self.wake.wait(60)
            self.wake.clear()

    def close(self):
        self.stop.set()
        self.wake.set()
        self.thread.join(timeout=2)
