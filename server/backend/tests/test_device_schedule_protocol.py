from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


SERVER_DATABASE_ROOT = Path(__file__).resolve().parents[2] / "database"
if str(SERVER_DATABASE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_DATABASE_ROOT))

from device_schedule_protocol import (
    build_device_schedule_sync_text,
    resolve_alarm_due_at,
    resolve_timer_due_at,
)


class DeviceScheduleProtocolTests(unittest.TestCase):
    def test_resolve_alarm_due_at_for_once_time_alarm_uses_first_future_occurrence(self) -> None:
        now = datetime(2026, 4, 20, 18, 0, tzinfo=timezone.utc)
        alarm = SimpleNamespace(
            schedule_type="time",
            time=time(7, 0),
            repeat="once",
            enabled=True,
            created_at=datetime(2026, 4, 20, 17, 30, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 20, 17, 30, tzinfo=timezone.utc),
            scheduled_for=None,
            offset_seconds=None,
        )

        due_at = resolve_alarm_due_at(alarm, now=now)

        self.assertEqual(
            due_at,
            datetime(2026, 4, 21, 7, 0, tzinfo=timezone.utc),
        )

    def test_build_device_schedule_sync_text_serializes_alarm_and_timer_due_times(self) -> None:
        now = datetime(2026, 4, 20, 6, 0, tzinfo=timezone.utc)
        alarm = SimpleNamespace(
            alarm_id="alarm-1",
            schedule_type="time",
            time=time(7, 30),
            repeat="daily",
            enabled=True,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
            scheduled_for=None,
            offset_seconds=None,
        )
        timer = SimpleNamespace(
            timer_id="timer-1",
            label="Tea",
            duration_seconds=180,
            started_at=now - timedelta(seconds=60),
            active=True,
        )

        payload = build_device_schedule_sync_text(
            server_now=now,
            alarms=[alarm],
            timers=[timer],
        )

        self.assertIn("version=1", payload)
        self.assertIn(f"server_epoch={int(now.timestamp())}", payload)
        self.assertIn(f"alarm|alarm-1|{int(datetime(2026, 4, 20, 7, 30, tzinfo=timezone.utc).timestamp())}|daily", payload)
        self.assertIn(f"timer|timer-1|{int((now + timedelta(seconds=120)).timestamp())}|once", payload)

    def test_resolve_timer_due_at_can_keep_overdue_active_for_device_sync(self) -> None:
        now = datetime(2026, 4, 20, 6, 0, 10, tzinfo=timezone.utc)
        timer = SimpleNamespace(
            timer_id="timer-1",
            duration_seconds=5,
            started_at=datetime(2026, 4, 20, 6, 0, 0, tzinfo=timezone.utc),
            active=True,
        )

        self.assertIsNone(resolve_timer_due_at(timer, now=now))
        self.assertEqual(
            resolve_timer_due_at(timer, now=now, include_overdue=True),
            datetime(2026, 4, 20, 6, 0, 5, tzinfo=timezone.utc),
        )

    def test_build_device_schedule_sync_text_can_include_overdue_once_entries(self) -> None:
        now = datetime(2026, 4, 20, 6, 0, 10, tzinfo=timezone.utc)
        alarm = SimpleNamespace(
            alarm_id="alarm-1",
            schedule_type="datetime",
            scheduled_for=datetime(2026, 4, 20, 6, 0, 2, tzinfo=timezone.utc),
            repeat="once",
            enabled=True,
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(minutes=1),
            time=None,
            offset_seconds=None,
        )
        timer = SimpleNamespace(
            timer_id="timer-1",
            label="Tea",
            duration_seconds=5,
            started_at=datetime(2026, 4, 20, 6, 0, 0, tzinfo=timezone.utc),
            active=True,
        )

        payload = build_device_schedule_sync_text(
            server_now=now,
            alarms=[alarm],
            timers=[timer],
            include_overdue_once=True,
        )

        self.assertIn(f"alarm|alarm-1|{int(datetime(2026, 4, 20, 6, 0, 2, tzinfo=timezone.utc).timestamp())}|once", payload)
        self.assertIn(f"timer|timer-1|{int(datetime(2026, 4, 20, 6, 0, 5, tzinfo=timezone.utc).timestamp())}|once", payload)


if __name__ == "__main__":
    unittest.main()
