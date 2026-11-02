import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from lima_next.nightly import NightlyBrief
from lima_next.workspace import Workspace


def at(text):
    return datetime.fromisoformat(text)


class NightlyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'nightly.db'
        self.prepare=Mock(return_value={'id':'test-brief'})
        self.schedule=NightlyBrief(self.path, self.prepare)

    def tearDown(self):
        self.temp.cleanup()

    def test_paused_schedule_does_not_prepare(self):
        self.schedule.tick(at('2026-10-30T23:15:00+00:00'))
        self.prepare.assert_not_called()

    def test_due_time_and_restart_prepare_only_once_per_local_day(self):
        self.schedule.configure(True,'18:00')
        self.schedule.tick(at('2026-10-30T22:59:00+00:00'))
        self.prepare.assert_not_called()
        self.schedule.tick(at('2026-10-30T23:00:00+00:00'))
        self.schedule.tick(at('2026-10-30T23:01:00+00:00'))
        restarted=NightlyBrief(self.path,self.prepare)
        restarted.tick(at('2026-10-31T02:00:00+00:00'))
        self.assertEqual(self.prepare.call_count,1)
        self.assertEqual(self.prepare.call_args.args[1],'2026-10-30')
        self.assertEqual(restarted.state(at('2026-10-31T02:00:00+00:00'))['last_run']['status'],'prepared')

    def test_catchup_prepares_current_day_without_fabricating_missed_days(self):
        self.schedule.configure(True,'18:00')
        self.schedule.tick(at('2026-11-03T02:00:00+00:00'))
        self.assertEqual(self.prepare.call_args.args[1],'2026-11-02')
        self.assertEqual(self.prepare.call_count,1)

    def test_central_standard_time_is_used_after_dst_transition(self):
        self.schedule.configure(True,'18:00')
        self.schedule.tick(at('2026-11-01T23:59:00+00:00'))
        self.prepare.assert_not_called()
        self.schedule.tick(at('2026-11-02T00:00:00+00:00'))
        self.assertEqual(self.prepare.call_args.args[1],'2026-11-01')

    def test_failed_preparation_is_visible_and_retryable(self):
        self.schedule.configure(True,'18:00')
        self.prepare.side_effect=ValueError('Sensitive internal details')
        self.schedule.tick(at('2026-10-30T23:00:00+00:00'))
        state=self.schedule.state(at('2026-10-30T23:01:00+00:00'))
        self.assertEqual(state['last_run']['status'],'failed')
        self.assertNotIn('Sensitive',state['last_run']['error'])
        self.prepare.side_effect=None
        self.schedule.tick(at('2026-10-30T23:01:00+00:00'))
        self.assertEqual(self.schedule.state()['last_run']['status'],'prepared')

    def test_crashed_lease_is_not_duplicated_but_expires(self):
        self.schedule.configure(True,'18:00')
        ws=Workspace(self.path)
        with ws.db:
            ws.db.execute('INSERT INTO brief_schedule_runs VALUES (?,?,?,NULL,NULL)',
                          ('2026-10-30','preparing','2026-10-30T23:00:00+00:00'))
        ws.close()
        self.schedule.tick(at('2026-10-30T23:01:00+00:00'))
        self.prepare.assert_not_called()
        self.schedule.tick(at('2026-10-30T23:06:00+00:00'))
        self.prepare.assert_called_once()

    def test_config_persists_and_validates_input(self):
        self.schedule.configure(True,'21:30')
        self.assertEqual(NightlyBrief(self.path).state()['at_time'],'21:30')
        for enabled,time in [(True,'24:00'),('yes','18:00'),(True,None)]:
            with self.assertRaises(ValueError):
                self.schedule.configure(enabled,time)

    def test_optional_drafts_run_after_brief_and_persist_setting(self):
        self.schedule.configure(True,'18:00',True)
        with patch('lima_next.nightly.drafts.prepare_all',return_value={'created':0}) as batch:
            self.schedule.tick(at('2026-10-30T23:01:00+00:00'))
            batch.assert_called_once()
            self.assertEqual(batch.call_args.args[1],'2026-10-30')
            self.schedule.tick(at('2026-10-30T23:02:00+00:00'))
            batch.assert_called_once()
        restarted=NightlyBrief(self.path)
        self.assertTrue(restarted.state()['prepare_drafts'])
        restarted.configure(True,'21:00')
        self.assertTrue(restarted.state()['prepare_drafts'])

    def test_draft_failure_does_not_report_successful_evening_pack(self):
        self.schedule.configure(True,'18:00',True)
        with patch('lima_next.nightly.drafts.prepare_all',side_effect=RuntimeError('test')):
            self.schedule.tick(at('2026-10-30T23:01:00+00:00'))
        self.assertEqual(self.schedule.state()['last_run']['status'],'failed')
        with patch('lima_next.nightly.drafts.prepare_all') as batch:
            self.schedule.tick(at('2026-10-30T23:02:00+00:00'))
            batch.assert_called_once()
        self.assertEqual(self.schedule.state()['last_run']['status'],'prepared')
