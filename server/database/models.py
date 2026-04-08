import uuid
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime, Time, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    """Return the current UTC timestamp as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ============================================
# 1. User Model
# ============================================


class User(db.Model):
    __tablename__ = 'users'

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

    # PostgreSQL JSONB fields with mutation tracking.
    traits = db.Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    preferences = db.Column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    memory = db.Column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    alarms = db.relationship('Alarm', backref='user', lazy=True, cascade='all, delete-orphan')
    timers = db.relationship('Timer', backref='user', lazy=True, cascade='all, delete-orphan')
    lists = db.relationship('List', backref='user', lazy=True, cascade='all, delete-orphan')
    logs = db.relationship('InteractionLog', backref='user', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        """Convert to dict for JSON response."""
        return {
            'user_id': str(self.user_id),
            'nfc_tag_id': self.nfc_tag_id,
            'user_name': self.user_name,
            'name': self.name,
            'has_user_password': bool(self.user_password),
            'traits': self.traits or [],
            'preferences': self.preferences or {},
            'memory': self.memory or [],
        }

    def set_user_password(self, raw_password: str | None):
        """Store a hashed password or clear the password when None is provided."""
        self.user_password = generate_password_hash(raw_password) if raw_password else None
        return self

    def check_user_password(self, raw_password: str) -> bool:
        """Compare a plain-text password with the stored password hash."""
        if not self.user_password:
            return False
        return check_password_hash(self.user_password, raw_password)

    def add_memory(self, memory_text: str):
        """Add to memory list (max 20 items)."""
        if not self.memory:
            self.memory = []

        if memory_text not in self.memory:
            self.memory.append(memory_text)
            if len(self.memory) > 20:
                self.memory = self.memory[-20:]

        return self


# ============================================
# 2. Alarm Model
# ============================================


class Alarm(db.Model):
    __tablename__ = 'alarms'

    alarm_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id'), nullable=False, index=True)
    time = db.Column(Time, nullable=False)
    label = db.Column(db.String(255), nullable=False)
    repeat = db.Column(db.String(20), nullable=False, default='once', server_default='once')
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=text('true'))
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
            'alarm_id': str(self.alarm_id),
            'time': self.time.strftime('%H:%M') if self.time else None,
            'label': self.label,
            'repeat': self.repeat,
            'enabled': self.enabled,
        }


# ============================================
# 3. Timer Model
# ============================================


class Timer(db.Model):
    __tablename__ = 'timers'

    timer_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id'), nullable=False, index=True)
    label = db.Column(db.String(255), nullable=False)
    duration_seconds = db.Column(db.Integer, nullable=False)
    started_at = db.Column(DateTime(timezone=True), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=text('true'))
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    def to_dict(self):
        return {
            'timer_id': str(self.timer_id),
            'label': self.label,
            'duration_seconds': self.duration_seconds,
            'started_at': self.started_at.isoformat(),
            'active': self.active,
        }


# ============================================
# 4. List Model
# ============================================


class List(db.Model):
    __tablename__ = 'lists'

    list_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id'), nullable=False, index=True)
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

    items = db.relationship('ListItem', backref='list', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'list_id': str(self.list_id),
            'list_name': self.list_name,
            'items': [item.to_dict() for item in self.items],
        }


# ============================================
# 5. ListItem Model
# ============================================


class ListItem(db.Model):
    __tablename__ = 'list_items'

    item_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id = db.Column(UUID(as_uuid=True), db.ForeignKey('lists.list_id'), nullable=False, index=True)
    content = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False, server_default=text('false'))
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
            'item_id': str(self.item_id),
            'content': self.content,
            'completed': self.completed,
        }


# ============================================
# 6. InteractionLog Model
# ============================================


class InteractionLog(db.Model):
    __tablename__ = 'interaction_logs'

    log_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.user_id'), nullable=False, index=True)
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
            'log_id': str(self.log_id),
            'input_text': self.input_text,
            'output_text': self.output_text,
            'intent': self.intent,
            'latency_ms': self.latency_ms,
            'timestamp': self.timestamp.isoformat(),
        }
