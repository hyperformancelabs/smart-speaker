import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import DateTime, Integer, Time, func, text

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from werkzeug.security import check_password_hash, generate_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from profile_schema import DEFAULT_PREFERENCES_JSON_SQL, build_default_preferences, normalize_preferences

db = SQLAlchemy()


def utcnow():
    """Return the current UTC timestamp as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _memory_key(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


class User(db.Model):
    __tablename__ = "users"

    user_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nfc_tag_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    user_name = db.Column(db.String(100), unique=True, index=True)
    user_password = db.Column(db.String(255))
    name = db.Column(db.String(255))
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    last_interaction = db.Column(DateTime(timezone=True))
    traits = db.Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    preferences = db.Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=build_default_preferences,
        server_default=text(f"'{DEFAULT_PREFERENCES_JSON_SQL}'::jsonb"),
    )
    memory = db.Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    alarms = db.relationship("Alarm", backref="user", lazy=True, cascade="all, delete-orphan")
    timers = db.relationship("Timer", backref="user", lazy=True, cascade="all, delete-orphan")
    lists = db.relationship("List", backref="user", lazy=True, cascade="all, delete-orphan")
    logs = db.relationship("InteractionLog", backref="user", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "user_id": str(self.user_id),
            "nfc_tag_id": self.nfc_tag_id,
            "user_name": self.user_name,
            "name": self.name,
            "has_user_password": bool(self.user_password),
            "traits": self.traits or [],
            "preferences": normalize_preferences(self.preferences),
            "memory": self.memory or [],
        }

    def set_user_password(self, raw_password: str | None):
        self.user_password = generate_password_hash(raw_password) if raw_password else None
        return self

    def check_user_password(self, raw_password: str) -> bool:
        if not self.user_password:
            return False
        return check_password_hash(self.user_password, raw_password)

    def add_memory(self, memory_text: str):
        cleaned_memory = " ".join(str(memory_text or "").split()).strip()
        if not cleaned_memory:
            return self

        if not self.memory:
            self.memory = []

        existing_keys = {_memory_key(item) for item in self.memory}
        if _memory_key(cleaned_memory) not in existing_keys:
            self.memory.append(cleaned_memory)
            if len(self.memory) > 20:
                self.memory = self.memory[-20:]

        return self

    def remove_memory(self, memory_text: str) -> bool:
        if not self.memory:
            return False

        lookup_key = _memory_key(memory_text)
        filtered_memory = [item for item in self.memory if _memory_key(item) != lookup_key]
        if len(filtered_memory) == len(self.memory):
            return False

        self.memory = filtered_memory
        return True


class Alarm(db.Model):
    __tablename__ = "alarms"

    alarm_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.user_id"), nullable=False, index=True)
    time = db.Column(Time)
    label = db.Column(db.String(255), nullable=False)
    repeat = db.Column(db.String(20), nullable=False, default="once", server_default="once")
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=text("true"))
    schedule_type = db.Column(
        db.String(20),
        nullable=False,
        default="time",
        server_default="time",
    )
    scheduled_for = db.Column(DateTime(timezone=True))
    offset_seconds = db.Column(Integer)
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    def to_dict(self):
        return {
            "alarm_id": str(self.alarm_id),
            "time": self.time.strftime("%H:%M") if self.time else None,
            "label": self.label,
            "repeat": self.repeat,
            "enabled": self.enabled,
            "schedule_type": self.schedule_type,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "offset_seconds": self.offset_seconds,
        }


class Timer(db.Model):
    __tablename__ = "timers"

    timer_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.user_id"), nullable=False, index=True)
    label = db.Column(db.String(255), nullable=False)
    duration_seconds = db.Column(db.Integer, nullable=False)
    started_at = db.Column(DateTime(timezone=True), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    def to_dict(self):
        return {
            "timer_id": str(self.timer_id),
            "label": self.label,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat(),
            "active": self.active,
        }


class List(db.Model):
    __tablename__ = "lists"

    list_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.user_id"), nullable=False, index=True)
    list_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    items = db.relationship("ListItem", backref="list", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "list_id": str(self.list_id),
            "list_name": self.list_name,
            "items": [item.to_dict() for item in self.items],
        }


class ListItem(db.Model):
    __tablename__ = "list_items"

    item_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id = db.Column(UUID(as_uuid=True), db.ForeignKey("lists.list_id"), nullable=False, index=True)
    content = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    def to_dict(self):
        return {
            "item_id": str(self.item_id),
            "content": self.content,
            "completed": self.completed,
        }


class InteractionLog(db.Model):
    __tablename__ = "interaction_logs"

    log_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.user_id"), nullable=False, index=True)
    input_text = db.Column(db.String(1000))
    output_text = db.Column(db.String(2000))
    intent = db.Column(db.String(50))
    tools_called = db.Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    latency_ms = db.Column(db.Integer)
    timestamp = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
        index=True,
    )

    def to_dict(self):
        return {
            "log_id": str(self.log_id),
            "input_text": self.input_text,
            "output_text": self.output_text,
            "intent": self.intent,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
        }
