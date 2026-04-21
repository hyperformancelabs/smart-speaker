from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable


DEVICE_SCHEDULE_PROTOCOL_VERSION = 1


@dataclass(slots=True)
class DeviceScheduleEntry:
    kind: str
    schedule_id: str
    due_at: datetime
    repeat: str

    def to_line(self) -> str:
        return f"{self.kind}|{self.schedule_id}|{int(self.due_at.timestamp())}|{self.repeat}"


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)
    return None


def _coerce_time(value: object) -> time | None:
    if isinstance(value, time):
        return value
    return None


def _repeat_interval(repeat: object) -> timedelta | None:
    normalized = str(repeat or "once").strip().lower()
    if normalized == "daily":
        return timedelta(days=1)
    if normalized == "weekly":
        return timedelta(days=7)
    return None


def _schedule_timezone(reference: datetime) -> timezone:
    tzinfo = reference.tzinfo or reference.astimezone().tzinfo
    return tzinfo if tzinfo is not None else timezone.utc


def _resolve_alarm_anchor_at(alarm: object, *, now: datetime) -> datetime:
    updated_at = _coerce_datetime(getattr(alarm, "updated_at", None))
    created_at = _coerce_datetime(getattr(alarm, "created_at", None))
    return updated_at or created_at or now


def resolve_alarm_due_at(
    alarm: object,
    *,
    now: datetime | None = None,
    include_overdue_once: bool = False,
) -> datetime | None:
    current_time = _coerce_datetime(now) or datetime.now(timezone.utc)
    if not bool(getattr(alarm, "enabled", True)):
        return None

    repeat = str(getattr(alarm, "repeat", "once") or "once").strip().lower() or "once"
    schedule_type = str(getattr(alarm, "schedule_type", "time") or "time").strip().lower() or "time"
    interval = _repeat_interval(repeat)

    if schedule_type == "datetime":
        due_at = _coerce_datetime(getattr(alarm, "scheduled_for", None))
        if due_at is None:
            return None
        if interval is None:
            return due_at if due_at > current_time or include_overdue_once else None
        while due_at <= current_time:
            due_at += interval
        return due_at

    if schedule_type == "relative":
        offset_seconds = int(getattr(alarm, "offset_seconds", 0) or 0)
        if offset_seconds <= 0:
            return None
        anchor_at = _resolve_alarm_anchor_at(alarm, now=current_time)
        due_at = anchor_at + timedelta(seconds=offset_seconds)
        if interval is None:
            return due_at if due_at > current_time or include_overdue_once else None
        while due_at <= current_time:
            due_at += interval
        return due_at

    alarm_time = _coerce_time(getattr(alarm, "time", None))
    if alarm_time is None:
        return None

    schedule_tz = _schedule_timezone(current_time)
    anchor_local = _resolve_alarm_anchor_at(alarm, now=current_time).astimezone(schedule_tz)
    candidate_local = datetime.combine(anchor_local.date(), alarm_time, tzinfo=schedule_tz)

    if interval is None:
        while candidate_local <= anchor_local:
            candidate_local += timedelta(days=1)
        candidate_utc = candidate_local.astimezone(timezone.utc)
        return candidate_utc if candidate_utc > current_time or include_overdue_once else None

    while candidate_local <= anchor_local:
        candidate_local += interval
    while candidate_local.astimezone(timezone.utc) <= current_time:
        candidate_local += interval
    return candidate_local.astimezone(timezone.utc)


def resolve_timer_due_at(
    timer: object,
    *,
    now: datetime | None = None,
    include_overdue: bool = False,
) -> datetime | None:
    current_time = _coerce_datetime(now) or datetime.now(timezone.utc)
    if not bool(getattr(timer, "active", True)):
        return None

    started_at = _coerce_datetime(getattr(timer, "started_at", None))
    duration_seconds = int(getattr(timer, "duration_seconds", 0) or 0)
    if started_at is None or duration_seconds <= 0:
        return None

    due_at = started_at + timedelta(seconds=duration_seconds)
    return due_at if due_at > current_time or include_overdue else None


def iter_device_schedule_entries(
    *,
    server_now: datetime,
    alarms: Iterable[object],
    timers: Iterable[object],
    include_overdue_once: bool = False,
) -> list[DeviceScheduleEntry]:
    entries: list[DeviceScheduleEntry] = []

    for alarm in alarms:
        due_at = resolve_alarm_due_at(
            alarm,
            now=server_now,
            include_overdue_once=include_overdue_once,
        )
        if due_at is None:
            continue
        entries.append(
            DeviceScheduleEntry(
                kind="alarm",
                schedule_id=str(getattr(alarm, "alarm_id", "") or ""),
                due_at=due_at,
                repeat=str(getattr(alarm, "repeat", "once") or "once").strip().lower() or "once",
            )
        )

    for timer in timers:
        due_at = resolve_timer_due_at(
            timer,
            now=server_now,
            include_overdue=include_overdue_once,
        )
        if due_at is None:
            continue
        entries.append(
            DeviceScheduleEntry(
                kind="timer",
                schedule_id=str(getattr(timer, "timer_id", "") or ""),
                due_at=due_at,
                repeat="once",
            )
        )

    entries.sort(key=lambda entry: (entry.due_at, entry.kind, entry.schedule_id))
    return entries


def build_device_schedule_sync_text(
    *,
    server_now: datetime,
    alarms: Iterable[object],
    timers: Iterable[object],
    include_overdue_once: bool = False,
) -> str:
    normalized_now = _coerce_datetime(server_now) or datetime.now(timezone.utc)
    lines = [
        f"version={DEVICE_SCHEDULE_PROTOCOL_VERSION}",
        f"server_epoch={int(normalized_now.timestamp())}",
    ]
    for entry in iter_device_schedule_entries(
        server_now=normalized_now,
        alarms=alarms,
        timers=timers,
        include_overdue_once=include_overdue_once,
    ):
        lines.append(entry.to_line())
    return "\n".join(lines) + "\n"
