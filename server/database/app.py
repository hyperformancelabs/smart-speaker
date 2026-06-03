import sys
import logging
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dotenv import dotenv_values
except ModuleNotFoundError:
    def dotenv_values(*args, **kwargs):
        return {}
from flask import Flask, jsonify, render_template, request
from sqlalchemy import text
from profile_schema import build_default_preferences, merge_preferences, normalize_preferences

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
ENV_VALUES = dotenv_values(ENV_FILE)

from models import Alarm, InteractionLog, List, ListItem, MediaHistory, Timer, User, db
from device_schedule_protocol import build_device_schedule_sync_text, resolve_alarm_due_at

app = Flask(__name__, static_folder="static", template_folder="templates")
app.json.ensure_ascii = False
DEFAULT_SERVER_PORT = 8386
REGISTER_HOST = "register.ssproject.hyperformancelabs.click"
ALLOWED_REPEAT_VALUES = {"once", "daily", "weekly"}
ALLOWED_SCHEDULE_TYPES = {"time", "datetime", "relative"}

DATABASE_URL = str(ENV_VALUES.get("DATABASE_URL") or "").strip()
VOICE_BACKEND_NOTIFY_URL = str(
    ENV_VALUES.get("VOICE_BACKEND_NOTIFY_URL") or "http://localhost:8387/api/device/schedules/notify"
).strip()
if not DATABASE_URL:
    raise RuntimeError(f"DATABASE_URL must be set in {ENV_FILE}.")

if DATABASE_URL == "postgres://":
    raise RuntimeError("DATABASE_URL must include the full PostgreSQL connection string.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg2://")):
    raise RuntimeError("DATABASE_URL must use a PostgreSQL SQLAlchemy URI.")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["JSON_SORT_KEYS"] = False

db.init_app(app)

logger = logging.getLogger(__name__)


def apply_runtime_schema_migrations() -> None:
    statements = (
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS schedule_type VARCHAR(20)",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS offset_seconds INTEGER",
        "UPDATE alarms SET schedule_type = 'time' WHERE schedule_type IS NULL",
        "ALTER TABLE alarms ALTER COLUMN schedule_type SET DEFAULT 'time'",
        "ALTER TABLE alarms ALTER COLUMN schedule_type SET NOT NULL",
        "ALTER TABLE alarms ALTER COLUMN time DROP NOT NULL",
        "ALTER TABLE alarms DROP CONSTRAINT IF EXISTS chk_alarms_schedule_type",
        (
            "ALTER TABLE alarms ADD CONSTRAINT chk_alarms_schedule_type "
            "CHECK (schedule_type IN ('time', 'datetime', 'relative'))"
        ),
    )
    with db.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    logger.info("runtime_schema_migrations_applied | statements=%d", len(statements))


with app.app_context():
    db.create_all()
    apply_runtime_schema_migrations()


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    original_error = getattr(error, "original_exception", None) or error
    logger.exception("database_server_error | error=%r", original_error)
    return jsonify({"error": "Server error"}), 500


def get_user_or_404(nfc_tag_id: str):
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id:
        return None
    return User.query.filter_by(nfc_tag_id=normalized_nfc_tag_id).first()


def parse_uuid_param(value: str):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def utcnow():
    return datetime.now(timezone.utc)


def server_now():
    return datetime.now().astimezone()


def normalize_optional_text(value):
    if value is None or not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_nfc_tag_id(value):
    value = normalize_optional_text(value)
    if not value:
        return None

    compact = value.replace(":", "").upper()
    if len(compact) % 2 == 0 and compact.isalnum():
        return ":".join(compact[index : index + 2] for index in range(0, len(compact), 2))
    return value.upper()


def compact_nfc_tag_id(value):
    normalized = normalize_nfc_tag_id(value)
    if not normalized:
        return None
    return normalized.replace(":", "")


def build_register_url(nfc_tag_id: str | None = None) -> str:
    base = f"https://{REGISTER_HOST}"
    compact = compact_nfc_tag_id(nfc_tag_id)
    if not compact:
        return f"{base}/register"
    return f"{base}/register/{compact}"


def render_register_page(
    nfc_tag_id: str | None = None,
    status_message: str | None = None,
    status_kind: str = "success",
    form_data: dict | None = None,
    registration_completed: bool = False,
    http_status: int = 200,
):
    return (
        render_template(
            "register.html",
            nfc_tag_id=nfc_tag_id,
            register_url=build_register_url(nfc_tag_id),
            status_message=status_message,
            status_kind=status_kind,
            form_data=form_data or {},
            registration_completed=registration_completed,
        ),
        http_status,
    )


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@app.route("/", methods=["GET"])
def dashboard_page():
    return render_template("index.html")


def is_valid_user_name(value: str | None) -> bool:
    return value is None or bool(USERNAME_PATTERN.fullmatch(value))


def is_valid_name(value: str | None) -> bool:
    if value is None:
        return True
    return all(char.isalpha() or char.isspace() for char in value)


def build_device_spoken_name(value: str | None) -> str | None:
    value = normalize_optional_text(value)
    if not value:
        return None

    value = normalize_whitespace(value)
    value = value.replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = normalize_whitespace(value)
    return value or None


def parse_alarm_time(value: str):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def parse_iso_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    raw_value = value.strip()
    if not raw_value:
        return None

    normalized_value = raw_value.replace("Z", "+00:00")
    candidates = (
        normalized_value,
        normalized_value.replace(" ", "T"),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    fallback_formats = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
    )
    for fmt in fallback_formats:
        try:
            return datetime.strptime(raw_value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_duration(duration_str: str) -> int:
    if duration_str is None:
        return 0
    if isinstance(duration_str, (int, float)):
        return int(duration_str)
    if not isinstance(duration_str, str):
        return 0

    normalized = normalize_whitespace(duration_str.lower())
    if not normalized:
        return 0

    if normalized.isdigit():
        return int(normalized)

    total_seconds = 0
    patterns = (
        (r"(\d+)\s*(?:d|day|days|ngay|ngày)", 86400),
        (r"(\d+)\s*(?:h|hr|hrs|hour|hours|gio|giờ)", 3600),
        (r"(\d+)\s*(?:m|min|mins|minute|minutes|phut|phút)", 60),
        (r"(\d+)\s*(?:s|sec|secs|second|seconds|giay|giây)", 1),
    )
    for pattern, multiplier in patterns:
        matches = re.findall(pattern, normalized)
        for match in matches:
            total_seconds += int(match) * multiplier

    return total_seconds


def user_has_complete_profile(user: User) -> bool:
    return bool(user.user_name and user.user_password and user.name)


def _timer_is_expired(timer: Timer, *, now: datetime | None = None) -> bool:
    if not timer.active:
        return False
    if not timer.started_at or int(timer.duration_seconds or 0) <= 0:
        return False
    effective_now = now or utcnow()
    return timer.started_at + timedelta(seconds=int(timer.duration_seconds)) <= effective_now


def _alarm_is_expired(alarm: Alarm, *, now: datetime | None = None) -> bool:
    if not alarm.enabled:
        return False
    repeat = normalize_optional_text(alarm.repeat) or "once"
    if repeat != "once":
        return False
    effective_now = now or server_now()
    return resolve_alarm_due_at(alarm, now=effective_now) is None


def _sync_expired_alarms(user: User) -> int:
    updated_count = 0
    current_time = server_now()
    for alarm in user.alarms:
        if _alarm_is_expired(alarm, now=current_time):
            alarm.enabled = False
            updated_count += 1
    if updated_count:
        db.session.commit()
        logger.info(
            "expired_alarms_synchronized | user_id=%r | count=%d",
            str(user.user_id),
            updated_count,
        )
    return updated_count


def _sync_expired_timers(user: User) -> int:
    updated_count = 0
    current_time = utcnow()
    for timer in user.timers:
        if _timer_is_expired(timer, now=current_time):
            timer.active = False
            updated_count += 1
    if updated_count:
        db.session.commit()
        logger.info(
            "expired_timers_synchronized | user_id=%r | count=%d",
            str(user.user_id),
            updated_count,
        )
    return updated_count


def _build_device_schedule_payload_text(user: User) -> str:
    effective_now = server_now()
    active_alarms = [alarm for alarm in user.alarms if alarm.enabled]
    active_timers = [timer for timer in user.timers if timer.active]
    return build_device_schedule_sync_text(
        server_now=effective_now,
        alarms=active_alarms,
        timers=active_timers,
        include_overdue_once=True,
    )


def _consume_schedule_event(user: User, *, kind: str, schedule_id: str, event: str) -> tuple[dict, bool]:
    normalized_kind = normalize_optional_text(kind)
    normalized_event = normalize_optional_text(event)
    if normalized_kind not in {"alarm", "timer"}:
        return {
            "status": "invalid_kind",
            "kind": kind,
            "schedule_id": schedule_id,
            "event": event,
        }, False

    if normalized_event not in {"triggered", "completed", "dismissed"}:
        return {
            "status": "invalid_event",
            "kind": normalized_kind,
            "schedule_id": schedule_id,
            "event": event,
        }, False

    schedule_uuid = parse_uuid_param(schedule_id)
    if not schedule_uuid:
        return {
            "status": "invalid_id",
            "kind": normalized_kind,
            "schedule_id": schedule_id,
            "event": normalized_event,
        }, False

    if normalized_kind == "timer":
        timer = Timer.query.filter_by(
            timer_id=schedule_uuid,
            user_id=user.user_id,
            active=True,
        ).first()
        if timer is None:
            return {
                "status": "not_found",
                "kind": normalized_kind,
                "schedule_id": schedule_id,
                "event": normalized_event,
            }, False

        timer.active = False
        return {
            "status": "consumed",
            "kind": normalized_kind,
            "schedule_id": str(timer.timer_id),
            "event": normalized_event,
        }, True

    alarm = Alarm.query.filter_by(
        alarm_id=schedule_uuid,
        user_id=user.user_id,
        enabled=True,
    ).first()
    if alarm is None:
        return {
            "status": "not_found",
            "kind": normalized_kind,
            "schedule_id": schedule_id,
            "event": normalized_event,
        }, False

    if (normalize_optional_text(alarm.repeat) or "once") != "once":
        return {
            "status": "ignored_repeat",
            "kind": normalized_kind,
            "schedule_id": str(alarm.alarm_id),
            "event": normalized_event,
            "repeat": alarm.repeat,
        }, False

    alarm.enabled = False
    return {
        "status": "consumed",
        "kind": normalized_kind,
        "schedule_id": str(alarm.alarm_id),
        "event": normalized_event,
    }, True


def _notify_device_schedule_change(nfc_tag_id: str, *, reason: str) -> None:
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id or not VOICE_BACKEND_NOTIFY_URL:
        return

    payload = json.dumps(
        {
            "nfc_tag_id": normalized_nfc_tag_id,
            "reason": reason,
        }
    ).encode("utf-8")
    request_obj = urllib_request.Request(
        VOICE_BACKEND_NOTIFY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=3.0) as response:
            response.read()
            logger.info(
                "device_schedule_notify_completed | nfc_tag_id=%r | reason=%r | http_status=%r",
                normalized_nfc_tag_id,
                reason,
                getattr(response, "status", None),
            )
    except (urllib_error.URLError, TimeoutError, ValueError):
        logger.warning(
            "device_schedule_notify_failed | nfc_tag_id=%r | reason=%r | notify_url=%r",
            normalized_nfc_tag_id,
            reason,
            VOICE_BACKEND_NOTIFY_URL,
            exc_info=True,
        )


def upsert_user_registration(nfc_tag_id: str, user_name: str, user_password: str, name: str):
    existing_user = User.query.filter_by(nfc_tag_id=nfc_tag_id).first()

    if not is_valid_user_name(user_name):
        return None, "user_name may only contain letters, numbers, and underscores", 400

    existing_username = User.query.filter_by(user_name=user_name).first()
    if existing_username and (not existing_user or existing_username.user_id != existing_user.user_id):
        return None, "user_name already exists", 409

    if not is_valid_name(name):
        return None, "name may only contain letters and spaces", 400

    if existing_user:
        existing_user.user_name = user_name
        existing_user.name = name
        existing_user.set_user_password(user_password)
        existing_user.preferences = normalize_preferences(existing_user.preferences)
        db.session.commit()
        return existing_user, None, 200

    user = User(
        nfc_tag_id=nfc_tag_id,
        user_name=user_name,
        name=name,
        traits=[],
        preferences=build_default_preferences(),
        memory=[],
    )
    user.set_user_password(user_password)
    db.session.add(user)
    db.session.commit()
    return user, None, 201


def _normalize_alarm_fields(data: dict, *, partial: bool = False):
    schedule_type = normalize_optional_text(data.get("schedule_type"))
    time_value = data.get("time")
    scheduled_for_value = data.get("scheduled_for")
    offset_seconds_value = data.get("offset_seconds")
    relative_value = data.get("after")

    if not schedule_type:
        if scheduled_for_value:
            schedule_type = "datetime"
        elif offset_seconds_value is not None or relative_value:
            schedule_type = "relative"
        elif time_value:
            schedule_type = "time"

    if not partial and schedule_type not in ALLOWED_SCHEDULE_TYPES:
        return None, "Missing or invalid schedule_type"
    if schedule_type and schedule_type not in ALLOWED_SCHEDULE_TYPES:
        return None, "Invalid schedule_type"

    normalized = {}
    if "label" in data or not partial:
        label = normalize_optional_text(data.get("label"))
        if not partial and not label:
            label = "Báo thức"
        if label is not None:
            normalized["label"] = label

    if "repeat" in data or not partial:
        repeat = normalize_optional_text(data.get("repeat")) or "once"
        if repeat not in ALLOWED_REPEAT_VALUES:
            return None, "Invalid repeat value"
        normalized["repeat"] = repeat

    if "enabled" in data:
        normalized["enabled"] = bool(data.get("enabled"))

    if schedule_type == "time":
        alarm_time = parse_alarm_time(time_value)
        if not alarm_time:
            return None, "Invalid time format. Expected HH:MM"
        normalized.update(
            {
                "schedule_type": "time",
                "time": alarm_time,
                "scheduled_for": None,
                "offset_seconds": None,
            }
        )
    elif schedule_type == "datetime":
        scheduled_for = parse_iso_datetime(scheduled_for_value)
        if not scheduled_for:
            return None, "Invalid scheduled_for datetime"
        normalized.update(
            {
                "schedule_type": "datetime",
                "time": None,
                "scheduled_for": scheduled_for,
                "offset_seconds": None,
            }
        )
    elif schedule_type == "relative":
        offset_seconds = offset_seconds_value
        if offset_seconds is None:
            offset_seconds = parse_duration(relative_value)
        try:
            offset_seconds = int(offset_seconds)
        except (TypeError, ValueError):
            offset_seconds = 0
        if offset_seconds <= 0:
            return None, "Invalid offset_seconds"
        normalized.update(
            {
                "schedule_type": "relative",
                "time": None,
                "scheduled_for": None,
                "offset_seconds": offset_seconds,
                "repeat": "once",
            }
        )
    elif not partial and schedule_type is None:
        return None, "Missing alarm schedule"

    return normalized, None


@app.route("/register", methods=["GET"])
@app.route("/REGISTER", methods=["GET"])
def register_page():
    nfc_tag_id = normalize_nfc_tag_id(request.args.get("nfc_tag_id"))
    return render_register_page(nfc_tag_id=nfc_tag_id)


@app.route("/REGISTER/<nfc_tag_id>", methods=["GET"])
@app.route("/register/<nfc_tag_id>", methods=["GET"])
@app.route("/U/<nfc_tag_id>", methods=["GET"])
@app.route("/u/<nfc_tag_id>", methods=["GET"])
@app.route("/r/<nfc_tag_id>", methods=["GET"])
@app.route("/R/<nfc_tag_id>", methods=["GET"])
def register_page_short(nfc_tag_id: str):
    return render_register_page(nfc_tag_id=normalize_nfc_tag_id(nfc_tag_id))


@app.route("/register", methods=["POST"])
def register_page_submit():
    form_data = request.form.to_dict(flat=True)
    nfc_tag_id = normalize_nfc_tag_id(form_data.get("nfc_tag_id"))
    user_name = normalize_optional_text(form_data.get("user_name"))
    user_password = normalize_optional_text(form_data.get("user_password"))
    name = normalize_optional_text(form_data.get("name"))

    if not nfc_tag_id:
        return render_register_page(
            nfc_tag_id=None,
            status_message="NFC tag ID is missing. Open the page from the QR code on the device.",
            status_kind="error",
            form_data=form_data,
            http_status=400,
        )

    if not user_name or not user_password or not name:
        return render_register_page(
            nfc_tag_id=nfc_tag_id,
            status_message="Please provide your full name, username, and password.",
            status_kind="error",
            form_data=form_data,
            http_status=400,
        )

    _, error_message, status_code = upsert_user_registration(nfc_tag_id, user_name, user_password, name)
    if error_message:
        return render_register_page(
            nfc_tag_id=nfc_tag_id,
            status_message=error_message,
            status_kind="error",
            form_data=form_data,
            http_status=status_code,
        )

    return render_register_page(
        nfc_tag_id=nfc_tag_id,
        status_message="Registration completed.",
        status_kind="success",
        form_data={},
        registration_completed=True,
        http_status=status_code,
    )


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    user_name = normalize_optional_text(data.get("user_name"))
    user_password = normalize_optional_text(data.get("user_password"))

    if not user_name or not user_password:
        return jsonify({"error": "Missing user_name or user_password"}), 400

    user = User.query.filter_by(user_name=user_name).first()
    if not user or not user.check_user_password(user_password):
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify(user.to_dict()), 200


@app.route("/api/users/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True) or {}
    nfc_tag_id = normalize_nfc_tag_id(data.get("nfc_tag_id"))
    user_name = normalize_optional_text(data.get("user_name"))
    user_password = normalize_optional_text(data.get("user_password"))
    name = normalize_optional_text(data.get("name"))

    if not nfc_tag_id:
        return jsonify({"error": "Missing nfc_tag_id"}), 400
    if not user_name or not user_password or not name:
        return jsonify({"error": "Missing user_name, user_password, or name"}), 400

    user, error_message, status_code = upsert_user_registration(
        nfc_tag_id,
        user_name,
        user_password,
        name,
    )
    if error_message:
        return jsonify({"error": error_message}), status_code
    return jsonify(user.to_dict()), status_code


@app.route("/api/users/<nfc_tag_id>", methods=["GET"])
def get_user(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.last_interaction = utcnow()
    db.session.commit()
    return jsonify(user.to_dict()), 200


@app.route("/api/device/users/<nfc_tag_id>/profile-status", methods=["GET"])
def get_device_profile_status(nfc_tag_id: str):
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id:
        return "invalid nfc_tag_id", 400, {"Content-Type": "text/plain; charset=utf-8"}

    user = get_user_or_404(normalized_nfc_tag_id)
    if not user:
        return "not-found", 404, {"Content-Type": "text/plain; charset=utf-8"}

    if not user_has_complete_profile(user):
        return "incomplete", 412, {"Content-Type": "text/plain; charset=utf-8"}

    device_name = build_device_spoken_name(user.name)
    if not device_name:
        return "incomplete", 412, {"Content-Type": "text/plain; charset=utf-8"}

    return device_name, 200, {"Content-Type": "text/plain; charset=us-ascii"}


@app.route("/api/device/users/<nfc_tag_id>/schedule-sync", methods=["GET"])
def get_device_schedule_sync(nfc_tag_id: str):
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id:
        return "invalid nfc_tag_id", 400, {"Content-Type": "text/plain; charset=utf-8"}

    user = get_user_or_404(normalized_nfc_tag_id)
    if not user:
        return "not-found", 404, {"Content-Type": "text/plain; charset=utf-8"}

    if not user_has_complete_profile(user):
        return "incomplete", 412, {"Content-Type": "text/plain; charset=utf-8"}

    payload = _build_device_schedule_payload_text(user)
    return payload, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/device/users/<nfc_tag_id>/schedule-events", methods=["POST"])
def post_device_schedule_events(nfc_tag_id: str):
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id:
        return jsonify({"error": "Invalid nfc_tag_id"}), 400

    user = get_user_or_404(normalized_nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        return jsonify({"error": "events must be a non-empty list"}), 400

    results: list[dict] = []
    changed = False
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            results.append({"status": "invalid_payload", "event": raw_event})
            continue

        result, did_change = _consume_schedule_event(
            user,
            kind=str(raw_event.get("kind") or ""),
            schedule_id=str(raw_event.get("schedule_id") or ""),
            event=str(raw_event.get("event") or "triggered"),
        )
        results.append(result)
        changed = changed or did_change

    if changed:
        db.session.commit()

    return jsonify({"events": results, "changed": changed}), 200


@app.route("/api/users/<nfc_tag_id>/update", methods=["PATCH"])
def update_user(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    field = data.get("field")
    value = data.get("value")
    replace = bool(data.get("replace", False))

    if field == "traits":
        user.traits = value if isinstance(value, list) else [value]
    elif field == "preferences":
        if not isinstance(value, dict):
            return jsonify({"error": "preferences must be a JSON object"}), 400
        if replace:
            user.preferences = normalize_preferences(value)
        else:
            user.preferences = normalize_preferences(merge_preferences(user.preferences, value))
    elif field == "name":
        name = normalize_optional_text(value)
        if name and not is_valid_name(name):
            return jsonify({"error": "name may only contain letters and spaces"}), 400
        user.name = name
    elif field == "user_name":
        user_name = normalize_optional_text(value)
        if user_name:
            if not is_valid_user_name(user_name):
                return jsonify({"error": "user_name may only contain letters, numbers, and underscores"}), 400
            existing_username = User.query.filter(
                User.user_name == user_name,
                User.user_id != user.user_id,
            ).first()
            if existing_username:
                return jsonify({"error": "user_name already exists"}), 409
        user.user_name = user_name
    elif field == "user_password":
        user.set_user_password(normalize_optional_text(value))
    elif field == "memory":
        user.memory = value if isinstance(value, list) else []
    else:
        return jsonify({"error": f"Invalid field: {field}"}), 400

    db.session.commit()
    return jsonify(user.to_dict()), 200


@app.route("/api/users/<nfc_tag_id>/memory", methods=["POST"])
def add_memory(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    memory_text = normalize_optional_text(data.get("memory"))
    if not memory_text:
        return jsonify({"error": "Missing memory text"}), 400

    user.add_memory(memory_text)
    db.session.commit()
    return jsonify({"message": "Memory saved", "memory": user.memory}), 200


@app.route("/api/users/<nfc_tag_id>/memory", methods=["DELETE"])
def delete_memory(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    memory_text = normalize_optional_text(data.get("memory"))
    if not memory_text:
        return jsonify({"error": "Missing memory text"}), 400

    if not user.remove_memory(memory_text):
        return jsonify({"error": "Memory not found"}), 404

    db.session.commit()
    return jsonify({"message": "Memory removed", "memory": user.memory}), 200


@app.route("/api/users/<nfc_tag_id>/alarms", methods=["GET"])
def list_alarms(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"alarms": [alarm.to_dict() for alarm in user.alarms]}), 200


@app.route("/api/users/<nfc_tag_id>/alarms", methods=["POST"])
def create_alarm(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    normalized_fields, error_message = _normalize_alarm_fields(data, partial=False)
    if error_message:
        return jsonify({"error": error_message}), 400

    logger.info(
        "create_alarm_request | nfc_tag_id=%r | user_id=%r | payload=%r | normalized_fields=%r",
        nfc_tag_id,
        str(user.user_id),
        data,
        normalized_fields,
    )
    try:
        alarm = Alarm(user_id=user.user_id, **normalized_fields)
        db.session.add(alarm)
        db.session.commit()
        response_payload = alarm.to_dict()
        logger.info(
            "create_alarm_succeeded | nfc_tag_id=%r | alarm_id=%r | response=%r",
            nfc_tag_id,
            response_payload.get("alarm_id"),
            response_payload,
        )
        _notify_device_schedule_change(user.nfc_tag_id, reason="alarm_created")
        return jsonify(response_payload), 201
    except Exception:
        db.session.rollback()
        logger.exception(
            "create_alarm_failed | nfc_tag_id=%r | user_id=%r | payload=%r | normalized_fields=%r",
            nfc_tag_id,
            str(user.user_id),
            data,
            normalized_fields,
        )
        return jsonify({"error": "Server error"}), 500


@app.route("/api/users/<nfc_tag_id>/alarms/<alarm_id>", methods=["PATCH"])
def update_alarm(nfc_tag_id: str, alarm_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    alarm_uuid = parse_uuid_param(alarm_id)
    if not alarm_uuid:
        return jsonify({"error": "Invalid alarm_id"}), 400

    alarm = Alarm.query.filter_by(alarm_id=alarm_uuid, user_id=user.user_id).first()
    if not alarm:
        return jsonify({"error": "Alarm not found"}), 404

    data = request.get_json(silent=True) or {}
    normalized_fields, error_message = _normalize_alarm_fields(data, partial=True)
    if error_message:
        return jsonify({"error": error_message}), 400

    for field_name, field_value in normalized_fields.items():
        setattr(alarm, field_name, field_value)

    db.session.commit()
    _notify_device_schedule_change(user.nfc_tag_id, reason="alarm_updated")
    return jsonify(alarm.to_dict()), 200


@app.route("/api/users/<nfc_tag_id>/alarms/<alarm_id>", methods=["DELETE"])
def delete_alarm(nfc_tag_id: str, alarm_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    alarm_uuid = parse_uuid_param(alarm_id)
    if not alarm_uuid:
        return jsonify({"error": "Invalid alarm_id"}), 400

    alarm = Alarm.query.filter_by(alarm_id=alarm_uuid, user_id=user.user_id).first()
    if not alarm:
        return jsonify({"error": "Alarm not found"}), 404

    db.session.delete(alarm)
    db.session.commit()
    _notify_device_schedule_change(user.nfc_tag_id, reason="alarm_deleted")
    return jsonify({"message": "Alarm deleted"}), 200


@app.route("/api/users/<nfc_tag_id>/timers", methods=["GET"])
def list_timers(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    timers = [timer.to_dict() for timer in user.timers if timer.active]
    return jsonify({"timers": timers}), 200


@app.route("/api/users/<nfc_tag_id>/timers", methods=["POST"])
def start_timer(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    duration_str = data.get("duration")
    label = normalize_optional_text(data.get("label")) or "Timer"
    duration_seconds = parse_duration(duration_str)
    if duration_seconds <= 0:
        return jsonify({"error": "Invalid duration"}), 400

    timer = Timer(
        user_id=user.user_id,
        label=label,
        duration_seconds=duration_seconds,
        started_at=utcnow(),
    )
    db.session.add(timer)
    db.session.commit()
    _notify_device_schedule_change(user.nfc_tag_id, reason="timer_created")
    return jsonify(timer.to_dict()), 201


@app.route("/api/users/<nfc_tag_id>/timers/<timer_id>", methods=["PATCH"])
def update_timer(nfc_tag_id: str, timer_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    timer_uuid = parse_uuid_param(timer_id)
    if not timer_uuid:
        return jsonify({"error": "Invalid timer_id"}), 400

    timer = Timer.query.filter_by(timer_id=timer_uuid, user_id=user.user_id, active=True).first()
    if not timer:
        return jsonify({"error": "Timer not found"}), 404

    data = request.get_json(silent=True) or {}
    if "duration" in data:
        duration_seconds = parse_duration(data.get("duration"))
        if duration_seconds <= 0:
            return jsonify({"error": "Invalid duration"}), 400
        timer.duration_seconds = duration_seconds
        timer.started_at = utcnow()
    if "label" in data:
        timer.label = normalize_optional_text(data.get("label")) or timer.label

    db.session.commit()
    _notify_device_schedule_change(user.nfc_tag_id, reason="timer_updated")
    return jsonify(timer.to_dict()), 200


@app.route("/api/users/<nfc_tag_id>/timers/<timer_id>", methods=["DELETE"])
def cancel_timer(nfc_tag_id: str, timer_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    timer_uuid = parse_uuid_param(timer_id)
    if not timer_uuid:
        return jsonify({"error": "Invalid timer_id"}), 400

    timer = Timer.query.filter_by(timer_id=timer_uuid, user_id=user.user_id).first()
    if not timer:
        return jsonify({"error": "Timer not found"}), 404

    timer.active = False
    db.session.commit()
    _notify_device_schedule_change(user.nfc_tag_id, reason="timer_cancelled")
    return jsonify({"message": "Timer cancelled"}), 200


@app.route("/api/users/<nfc_tag_id>/lists", methods=["GET"])
def list_lists(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"lists": [lst.to_dict() for lst in user.lists]}), 200


@app.route("/api/users/<nfc_tag_id>/lists", methods=["POST"])
def create_list(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    list_name = normalize_optional_text(data.get("list_name"))
    if not list_name:
        return jsonify({"error": "Missing list_name"}), 400

    lst = List(user_id=user.user_id, list_name=list_name)
    db.session.add(lst)
    db.session.commit()
    return jsonify(lst.to_dict()), 201


@app.route("/api/users/<nfc_tag_id>/lists/<list_id>", methods=["PATCH"])
def rename_list(nfc_tag_id: str, list_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    list_uuid = parse_uuid_param(list_id)
    if not list_uuid:
        return jsonify({"error": "Invalid list_id"}), 400

    lst = List.query.filter_by(list_id=list_uuid, user_id=user.user_id).first()
    if not lst:
        return jsonify({"error": "List not found"}), 404

    data = request.get_json(silent=True) or {}
    list_name = normalize_optional_text(data.get("list_name"))
    if not list_name:
        return jsonify({"error": "Missing list_name"}), 400

    lst.list_name = list_name
    db.session.commit()
    return jsonify(lst.to_dict()), 200


@app.route("/api/users/<nfc_tag_id>/lists/<list_id>", methods=["DELETE"])
def delete_list(nfc_tag_id: str, list_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    list_uuid = parse_uuid_param(list_id)
    if not list_uuid:
        return jsonify({"error": "Invalid list_id"}), 400

    lst = List.query.filter_by(list_id=list_uuid, user_id=user.user_id).first()
    if not lst:
        return jsonify({"error": "List not found"}), 404

    db.session.delete(lst)
    db.session.commit()
    return jsonify({"message": "List deleted"}), 200


@app.route("/api/users/<nfc_tag_id>/lists/<list_id>/items", methods=["POST"])
def add_list_item(nfc_tag_id: str, list_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    list_uuid = parse_uuid_param(list_id)
    if not list_uuid:
        return jsonify({"error": "Invalid list_id"}), 400

    lst = List.query.filter_by(list_id=list_uuid, user_id=user.user_id).first()
    if not lst:
        return jsonify({"error": "List not found"}), 404

    data = request.get_json(silent=True) or {}
    content = normalize_optional_text(data.get("item"))
    if not content:
        return jsonify({"error": "Missing item"}), 400

    item = ListItem(list_id=lst.list_id, content=content)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route("/api/users/<nfc_tag_id>/lists/<list_id>/items/<item_id>", methods=["PATCH"])
def update_list_item(nfc_tag_id: str, list_id: str, item_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    list_uuid = parse_uuid_param(list_id)
    item_uuid = parse_uuid_param(item_id)
    if not list_uuid:
        return jsonify({"error": "Invalid list_id"}), 400
    if not item_uuid:
        return jsonify({"error": "Invalid item_id"}), 400

    lst = List.query.filter_by(list_id=list_uuid, user_id=user.user_id).first()
    if not lst:
        return jsonify({"error": "List not found"}), 404

    item = ListItem.query.filter_by(item_id=item_uuid, list_id=lst.list_id).first()
    if not item:
        return jsonify({"error": "Item not found"}), 404

    data = request.get_json(silent=True) or {}
    if "item" in data:
        content = normalize_optional_text(data.get("item"))
        if not content:
            return jsonify({"error": "Missing item"}), 400
        item.content = content
    if "completed" in data:
        item.completed = bool(data.get("completed"))

    db.session.commit()
    return jsonify(item.to_dict()), 200


@app.route("/api/users/<nfc_tag_id>/lists/<list_id>/items/<item_id>", methods=["DELETE"])
def remove_list_item(nfc_tag_id: str, list_id: str, item_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    list_uuid = parse_uuid_param(list_id)
    item_uuid = parse_uuid_param(item_id)
    if not list_uuid:
        return jsonify({"error": "Invalid list_id"}), 400
    if not item_uuid:
        return jsonify({"error": "Invalid item_id"}), 400

    lst = List.query.filter_by(list_id=list_uuid, user_id=user.user_id).first()
    if not lst:
        return jsonify({"error": "List not found"}), 404

    item = ListItem.query.filter_by(item_id=item_uuid, list_id=lst.list_id).first()
    if not item:
        return jsonify({"error": "Item not found"}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Item removed"}), 200


@app.route("/api/users/<nfc_tag_id>/logs", methods=["GET"])
def get_logs(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    limit = request.args.get("limit", 50, type=int)
    logs = InteractionLog.query.filter_by(user_id=user.user_id).order_by(InteractionLog.timestamp.desc()).limit(limit).all()
    return jsonify({"logs": [log.to_dict() for log in logs]}), 200


@app.route("/api/logs", methods=["POST"])
def create_log():
    data = request.get_json(silent=True) or {}
    user_id = parse_uuid_param(data.get("user_id"))
    if not user_id:
        return jsonify({"error": "Invalid user_id"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    log = InteractionLog(
        user_id=user_id,
        input_text=data.get("input_text"),
        output_text=data.get("output_text"),
        intent=data.get("intent"),
        tools_called=data.get("tools_called", []),
        latency_ms=data.get("latency_ms"),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"log_id": str(log.log_id)}), 201


@app.route("/api/users/<nfc_tag_id>/media-history", methods=["GET"])
def list_media_history(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    limit = request.args.get("limit", 50, type=int)
    records = (
        MediaHistory.query.filter_by(user_id=user.user_id)
        .order_by(MediaHistory.last_played_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"media_history": [r.to_dict() for r in records]}), 200


@app.route("/api/users/<nfc_tag_id>/media-history", methods=["POST"])
def upsert_media_history(nfc_tag_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    public_stream_url = normalize_optional_text(data.get("public_stream_url"))
    if not public_stream_url:
        return jsonify({"error": "Missing public_stream_url"}), 400

    existing = MediaHistory.query.filter_by(
        user_id=user.user_id, public_stream_url=public_stream_url
    ).first()

    if existing:
        existing.play_count = (existing.play_count or 0) + 1
        existing.last_played_at = utcnow()
        if data.get("title") is not None:
            existing.title = data["title"]
        if data.get("source") is not None:
            existing.source = data["source"]
        if data.get("webpage_url") is not None:
            existing.webpage_url = data["webpage_url"]
        if data.get("thumbnail_url") is not None:
            existing.thumbnail_url = data["thumbnail_url"]
        db.session.commit()
        return jsonify(existing.to_dict()), 200

    record = MediaHistory(
        user_id=user.user_id,
        public_stream_url=public_stream_url,
        title=normalize_optional_text(data.get("title")) or "Media stream",
        source_url=normalize_optional_text(data.get("source_url")),
        source=normalize_optional_text(data.get("source")),
        webpage_url=normalize_optional_text(data.get("webpage_url")),
        thumbnail_url=normalize_optional_text(data.get("thumbnail_url")),
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(record.to_dict()), 201


@app.route("/api/users/<nfc_tag_id>/media-history/<media_id>", methods=["DELETE"])
def delete_media_history(nfc_tag_id: str, media_id: str):
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    media_uuid = parse_uuid_param(media_id)
    if not media_uuid:
        return jsonify({"error": "Invalid media_id"}), 400

    record = MediaHistory.query.filter_by(
        media_id=media_uuid, user_id=user.user_id
    ).first()
    if not record:
        return jsonify({"error": "Media history not found"}), 404

    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Media history deleted"}), 200


@app.route("/health", methods=["GET"])
def health_check():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        app.logger.exception("Database health check failed")
        return jsonify(
            {
                "status": "error",
                "database": "postgresql",
                "error": "Database unavailable",
            }
        ), 503

    return jsonify({"status": "ok", "database": "postgresql"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=DEFAULT_SERVER_PORT, debug=True)
