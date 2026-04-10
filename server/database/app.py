import uuid
from datetime import datetime, timezone
from pathlib import Path
import re
import unicodedata

from dotenv import dotenv_values
from flask import Flask, jsonify, request, render_template, send_from_directory
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / '.env'
ENV_VALUES = dotenv_values(ENV_FILE)

from models import db, User, Alarm, Timer, List, ListItem, InteractionLog

# ============================================
# Flask App Configuration
# ============================================

app = Flask(__name__, static_folder='static', static_url_path='/', template_folder='templates')
app.json.ensure_ascii = False
DEFAULT_SERVER_PORT = 8386
REGISTER_HOST = 'register.ssproject.hyperformancelabs.click'

# Database configuration
DATABASE_URL = str(ENV_VALUES.get('DATABASE_URL') or '').strip()
if not DATABASE_URL:
    raise RuntimeError(f'DATABASE_URL must be set in {ENV_FILE}.')

if DATABASE_URL == 'postgres://':
    raise RuntimeError('DATABASE_URL must include the full PostgreSQL connection string.')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if not DATABASE_URL.startswith(('postgresql://', 'postgresql+psycopg2://')):
    raise RuntimeError('DATABASE_URL must use a PostgreSQL SQLAlchemy URI.')

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
}
app.config['JSON_SORT_KEYS'] = False

db.init_app(app)

# ============================================
# Create tables on startup
# ============================================

with app.app_context():
    db.create_all()

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({'error': 'Server error'}), 500

# ============================================
# UTILITY FUNCTIONS
# ============================================

def get_user_or_404(nfc_tag_id: str):
    """Get user by NFC tag ID or return 404"""
    user = User.query.filter_by(nfc_tag_id=nfc_tag_id).first()
    if not user:
        return None
    return user


def parse_uuid_param(value: str):
    """Parse a UUID route or payload parameter safely."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def utcnow():
    """Return the current UTC timestamp as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def parse_alarm_time(value: str):
    """Parse an alarm time in HH:MM format."""
    if not isinstance(value, str):
        return None

    try:
        return datetime.strptime(value.strip(), '%H:%M').time()
    except ValueError:
        return None


def normalize_optional_text(value):
    """Normalize an optional text field and treat blank strings as None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def normalize_whitespace(value: str) -> str:
    return ' '.join(value.split())


def normalize_nfc_tag_id(value):
    value = normalize_optional_text(value)
    if not value:
        return None

    compact = value.replace(':', '').upper()
    if len(compact) % 2 == 0 and compact.isalnum():
        return ':'.join(compact[i:i + 2] for i in range(0, len(compact), 2))

    return value.upper()


def compact_nfc_tag_id(value):
    normalized = normalize_nfc_tag_id(value)
    if not normalized:
        return None
    return normalized.replace(':', '')


# Web Routes
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_spa(path):
    if path and Path(app.static_folder, path).exists():
        return send_from_directory(app.static_folder, path)
    return render_template('index.html')


USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_]+$')


def is_valid_user_name(value: str | None) -> bool:
    """Allow only ASCII letters, digits, and underscores."""
    return value is None or bool(USERNAME_PATTERN.fullmatch(value))


def is_valid_name(value: str | None) -> bool:
    """Allow only letters (including accented letters) and spaces."""
    if value is None:
        return True

    return all(char.isalpha() or char.isspace() for char in value)


def build_device_spoken_name(value: str | None) -> str | None:
    """Return an ASCII-only name for device playback while preserving DB storage elsewhere."""
    value = normalize_optional_text(value)
    if not value:
        return None

    value = normalize_whitespace(value)
    value = value.replace('Đ', 'D').replace('đ', 'd')
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = normalize_whitespace(value)
    return value or None


def upsert_user_registration(nfc_tag_id: str, user_name: str, user_password: str, name: str):
    existing_user = User.query.filter_by(nfc_tag_id=nfc_tag_id).first()

    if not is_valid_user_name(user_name):
        return None, 'user_name may only contain letters, numbers, and underscores', 400

    existing_username = User.query.filter_by(user_name=user_name).first()
    if existing_username and (not existing_user or existing_username.user_id != existing_user.user_id):
        return None, 'user_name already exists', 409

    if not is_valid_name(name):
        return None, 'name may only contain letters and spaces', 400

    if existing_user:
        existing_user.user_name = user_name
        existing_user.name = name
        existing_user.set_user_password(user_password)
        db.session.commit()
        return existing_user, None, 200

    user = User(
        nfc_tag_id=nfc_tag_id,
        user_name=user_name,
        name=name,
        traits=[],
        preferences={},
        memory=[]
    )
    user.set_user_password(user_password)

    db.session.add(user)
    db.session.commit()
    return user, None, 201


def user_has_complete_profile(user: User) -> bool:
    return bool(user.user_name and user.user_password and user.name)

# ============================================
# ROUTES - USER MANAGEMENT
# ============================================

@app.route('/register', methods=['GET'])
@app.route('/REGISTER', methods=['GET'])
def register_page():
    nfc_tag_id = normalize_nfc_tag_id(request.args.get('nfc_tag_id'))
    return render_register_page(nfc_tag_id=nfc_tag_id)


@app.route('/REGISTER/<nfc_tag_id>', methods=['GET'])
@app.route('/register/<nfc_tag_id>', methods=['GET'])
@app.route('/U/<nfc_tag_id>', methods=['GET'])
@app.route('/u/<nfc_tag_id>', methods=['GET'])
@app.route('/r/<nfc_tag_id>', methods=['GET'])
@app.route('/R/<nfc_tag_id>', methods=['GET'])
def register_page_short(nfc_tag_id: str):
    return render_register_page(nfc_tag_id=normalize_nfc_tag_id(nfc_tag_id))


@app.route('/register', methods=['POST'])
def register_page_submit():
    form_data = request.form.to_dict(flat=True)
    nfc_tag_id = normalize_nfc_tag_id(form_data.get('nfc_tag_id'))
    user_name = normalize_optional_text(form_data.get('user_name'))
    user_password = normalize_optional_text(form_data.get('user_password'))
    name = normalize_optional_text(form_data.get('name'))

    if not nfc_tag_id:
        return render_register_page(
            nfc_tag_id=None,
            status_message='NFC tag ID is missing. Open the page from the QR code on the device.',
            status_kind='error',
            form_data=form_data,
            http_status=400,
        )

    if not user_name or not user_password or not name:
        return render_register_page(
            nfc_tag_id=nfc_tag_id,
            status_message='Please provide your full name, username, and password.',
            status_kind='error',
            form_data=form_data,
            http_status=400,
        )

    _, error_message, status_code = upsert_user_registration(nfc_tag_id, user_name, user_password, name)
    if error_message:
        return render_register_page(
            nfc_tag_id=nfc_tag_id,
            status_message=error_message,
            status_kind='error',
            form_data=form_data,
            http_status=status_code,
        )

    return render_register_page(
        nfc_tag_id=nfc_tag_id,
        status_message='Registration completed. Please tap your NFC card on the speaker again.',
        status_kind='success',
        form_data={},
        http_status=status_code,
    )

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    user_name = data.get('user_name')
    user_password = data.get('user_password')
    
    if not user_name or not user_password:
        return jsonify({'error': 'Missing user_name or user_password'}), 400
        
    user = User.query.filter_by(user_name=user_name).first()
    if not user or not user.check_user_password(user_password):
        return jsonify({'error': 'Invalid credentials'}), 401
        
    return jsonify({
        'user_id': str(user.user_id),
        'nfc_tag_id': user.nfc_tag_id,
        'user_name': user.user_name,
        'name': user.name
    }), 200

@app.route('/api/users/register', methods=['POST'])
def register_user():
    """
    Register a new user from an NFC tag tap.
    
    Request:
    {
      "nfc_tag_id": "ABCD1234",
      "user_name": "huynguyen",
      "user_password": "secure-pass",
      "name": "Huy Nguyen"
    }
    
    Response:
    {
      "user_id": "uuid",
      "nfc_tag_id": "ABCD1234",
      "user_name": null,
      "name": null,
      "has_user_password": false,
      "traits": [],
      "preferences": {},
      "memory": []
    }
    """
    data = request.get_json(silent=True) or {}
    
    nfc_tag_id = normalize_nfc_tag_id(data.get('nfc_tag_id'))
    user_name = normalize_optional_text(data.get('user_name'))
    user_password = normalize_optional_text(data.get('user_password'))
    name = normalize_optional_text(data.get('name'))
    
    if not nfc_tag_id:
        return jsonify({'error': 'Missing nfc_tag_id'}), 400
    
    if not user_name or not user_password or not name:
        return jsonify({'error': 'Missing user_name, user_password, or name'}), 400

    user, error_message, status_code = upsert_user_registration(
        nfc_tag_id,
        user_name,
        user_password,
        name,
    )
    if error_message:
        return jsonify({'error': error_message}), status_code

    return jsonify(user.to_dict()), status_code

@app.route('/api/users/<nfc_tag_id>', methods=['GET'])
def get_user(nfc_tag_id: str):
    """
    Get user profile by NFC tag ID
    
    Response:
    {
      "user_id": "uuid",
      "nfc_tag_id": "ABCD1234",
      "user_name": "huynguyen",
      "name": "Huy Nguyen",
      "has_user_password": true,
      "traits": ["student", "night owl"],
      "preferences": {"response_style": "casual"},
      "memory": ["user likes jazz"]
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Update last interaction
    user.last_interaction = utcnow()
    db.session.commit()
    
    return jsonify(user.to_dict()), 200


@app.route('/api/device/users/<nfc_tag_id>/profile-status', methods=['GET'])
def get_device_profile_status(nfc_tag_id: str):
    normalized_nfc_tag_id = normalize_nfc_tag_id(nfc_tag_id)
    if not normalized_nfc_tag_id:
        return 'invalid nfc_tag_id', 400, {'Content-Type': 'text/plain; charset=utf-8'}

    user = get_user_or_404(normalized_nfc_tag_id)
    if not user:
        return 'not-found', 404, {'Content-Type': 'text/plain; charset=utf-8'}

    if not user_has_complete_profile(user):
        return 'incomplete', 412, {'Content-Type': 'text/plain; charset=utf-8'}

    device_name = build_device_spoken_name(user.name)
    if not device_name:
        return 'incomplete', 412, {'Content-Type': 'text/plain; charset=utf-8'}

    return device_name, 200, {'Content-Type': 'text/plain; charset=us-ascii'}

@app.route('/api/users/<nfc_tag_id>/update', methods=['PATCH'])
def update_user(nfc_tag_id: str):
    """
    Update user profile field
    
    Request:
    {
      "field": "user_name",
      "value": "huynguyen"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value')
    
    if field == 'traits':
        user.traits = value if isinstance(value, list) else [value]
    elif field == 'preferences':
        user.preferences = value if isinstance(value, dict) else {}
    elif field == 'name':
        name = normalize_optional_text(value)
        if name and not is_valid_name(name):
            return jsonify({'error': 'name may only contain letters and spaces'}), 400
        user.name = name
    elif field == 'user_name':
        user_name = normalize_optional_text(value)
        if user_name:
            if not is_valid_user_name(user_name):
                return jsonify({'error': 'user_name may only contain letters, numbers, and underscores'}), 400
            existing_username = User.query.filter(
                User.user_name == user_name,
                User.user_id != user.user_id,
            ).first()
            if existing_username:
                return jsonify({'error': 'user_name already exists'}), 409
        user.user_name = user_name
    elif field == 'user_password':
        user.set_user_password(normalize_optional_text(value))
    else:
        return jsonify({'error': f'Invalid field: {field}'}), 400
    
    db.session.commit()
    
    return jsonify(user.to_dict()), 200

@app.route('/api/users/<nfc_tag_id>/memory', methods=['POST'])
def add_memory(nfc_tag_id: str):
    """
    Add to user memory
    
    Request:
    {
      "memory": "user likes jazz music"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json(silent=True) or {}
    memory_text = data.get('memory')
    
    if not memory_text:
        return jsonify({'error': 'Missing memory text'}), 400
    
    user.add_memory(memory_text)
    db.session.commit()
    
    return jsonify({
        'message': 'Memory saved',
        'memory': user.memory
    }), 200

# ============================================
# ROUTES - ALARMS
# ============================================

@app.route('/api/users/<nfc_tag_id>/alarms', methods=['GET'])
def list_alarms(nfc_tag_id: str):
    """List all alarms for user"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    alarms = [alarm.to_dict() for alarm in user.alarms]
    return jsonify({'alarms': alarms}), 200

@app.route('/api/users/<nfc_tag_id>/alarms', methods=['POST'])
def create_alarm(nfc_tag_id: str):
    """
    Create alarm
    
    Request:
    {
      "time": "07:00",
      "label": "Wake up",
      "repeat": "daily"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json(silent=True) or {}
    time_value = data.get('time')
    label = data.get('label')
    repeat = data.get('repeat', 'once')
    
    if not time_value or not label:
        return jsonify({'error': 'Missing time or label'}), 400

    alarm_time = parse_alarm_time(time_value)
    if not alarm_time:
        return jsonify({'error': 'Invalid time format. Expected HH:MM'}), 400
    
    alarm = Alarm(
        user_id=user.user_id,
        time=alarm_time,
        label=label,
        repeat=repeat
    )
    
    db.session.add(alarm)
    db.session.commit()
    
    return jsonify(alarm.to_dict()), 201

@app.route('/api/users/<nfc_tag_id>/alarms/<alarm_id>', methods=['PATCH'])
def update_alarm(nfc_tag_id: str, alarm_id: str):
    """Update alarm"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    alarm_uuid = parse_uuid_param(alarm_id)
    if not alarm_uuid:
        return jsonify({'error': 'Invalid alarm_id'}), 400
    
    alarm = Alarm.query.filter_by(
        alarm_id=alarm_uuid,
        user_id=user.user_id
    ).first()
    
    if not alarm:
        return jsonify({'error': 'Alarm not found'}), 404
    
    data = request.get_json(silent=True) or {}
    if 'time' in data:
        alarm_time = parse_alarm_time(data['time'])
        if not alarm_time:
            return jsonify({'error': 'Invalid time format. Expected HH:MM'}), 400
        alarm.time = alarm_time
    if 'label' in data:
        alarm.label = data['label']
    if 'repeat' in data:
        alarm.repeat = data['repeat']
    
    db.session.commit()
    
    return jsonify(alarm.to_dict()), 200

@app.route('/api/users/<nfc_tag_id>/alarms/<alarm_id>', methods=['DELETE'])
def delete_alarm(nfc_tag_id: str, alarm_id: str):
    """Delete alarm"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    alarm_uuid = parse_uuid_param(alarm_id)
    if not alarm_uuid:
        return jsonify({'error': 'Invalid alarm_id'}), 400
    
    alarm = Alarm.query.filter_by(
        alarm_id=alarm_uuid,
        user_id=user.user_id
    ).first()
    
    if not alarm:
        return jsonify({'error': 'Alarm not found'}), 404
    
    db.session.delete(alarm)
    db.session.commit()
    
    return jsonify({'message': 'Alarm deleted'}), 200

# ============================================
# ROUTES - TIMERS
# ============================================

@app.route('/api/users/<nfc_tag_id>/timers', methods=['GET'])
def list_timers(nfc_tag_id: str):
    """List all timers"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    timers = [timer.to_dict() for timer in user.timers if timer.active]
    return jsonify({'timers': timers}), 200

@app.route('/api/users/<nfc_tag_id>/timers', methods=['POST'])
def start_timer(nfc_tag_id: str):
    """
    Start timer
    
    Request:
    {
      "duration": "5m",
      "label": "Cooking"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json(silent=True) or {}
    duration_str = data.get('duration')
    label = data.get('label')
    
    if not duration_str or not label:
        return jsonify({'error': 'Missing duration or label'}), 400
    
    # Parse duration (e.g., "5m" -> 300 seconds, "1h30m" -> 5400)
    duration_seconds = parse_duration(duration_str)
    
    if duration_seconds <= 0:
        return jsonify({'error': 'Invalid duration'}), 400
    
    timer = Timer(
        user_id=user.user_id,
        label=label,
        duration_seconds=duration_seconds,
        started_at=utcnow()
    )
    
    db.session.add(timer)
    db.session.commit()
    
    return jsonify(timer.to_dict()), 201

@app.route('/api/users/<nfc_tag_id>/timers/<timer_id>', methods=['DELETE'])
def cancel_timer(nfc_tag_id: str, timer_id: str):
    """Cancel timer"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    timer_uuid = parse_uuid_param(timer_id)
    if not timer_uuid:
        return jsonify({'error': 'Invalid timer_id'}), 400
    
    timer = Timer.query.filter_by(
        timer_id=timer_uuid,
        user_id=user.user_id
    ).first()
    
    if not timer:
        return jsonify({'error': 'Timer not found'}), 404
    
    timer.active = False
    db.session.commit()
    
    return jsonify({'message': 'Timer cancelled'}), 200

# ============================================
# ROUTES - LISTS
# ============================================

@app.route('/api/users/<nfc_tag_id>/lists', methods=['GET'])
def list_lists(nfc_tag_id: str):
    """Get all lists"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    lists = [lst.to_dict() for lst in user.lists]
    return jsonify({'lists': lists}), 200

@app.route('/api/users/<nfc_tag_id>/lists', methods=['POST'])
def create_list(nfc_tag_id: str):
    """
    Create new list
    
    Request:
    {
      "list_name": "Shopping"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json(silent=True) or {}
    list_name = data.get('list_name')
    
    if not list_name:
        return jsonify({'error': 'Missing list_name'}), 400
    
    lst = List(
        user_id=user.user_id,
        list_name=list_name
    )
    
    db.session.add(lst)
    db.session.commit()
    
    return jsonify(lst.to_dict()), 201

@app.route('/api/users/<nfc_tag_id>/lists/<list_id>/items', methods=['POST'])
def add_list_item(nfc_tag_id: str, list_id: str):
    """
    Add item to list
    
    Request:
    {
      "item": "Milk"
    }
    """
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    list_uuid = parse_uuid_param(list_id)
    if not list_uuid:
        return jsonify({'error': 'Invalid list_id'}), 400
    
    lst = List.query.filter_by(
        list_id=list_uuid,
        user_id=user.user_id
    ).first()
    
    if not lst:
        return jsonify({'error': 'List not found'}), 404
    
    data = request.get_json(silent=True) or {}
    content = data.get('item')
    
    if not content:
        return jsonify({'error': 'Missing item'}), 400
    
    item = ListItem(
        list_id=lst.list_id,
        content=content
    )
    
    db.session.add(item)
    db.session.commit()
    
    return jsonify(item.to_dict()), 201

@app.route('/api/users/<nfc_tag_id>/lists/<list_id>/items/<item_id>', methods=['DELETE'])
def remove_list_item(nfc_tag_id: str, list_id: str, item_id: str):
    """Remove item from list"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    list_uuid = parse_uuid_param(list_id)
    item_uuid = parse_uuid_param(item_id)
    if not list_uuid:
        return jsonify({'error': 'Invalid list_id'}), 400
    if not item_uuid:
        return jsonify({'error': 'Invalid item_id'}), 400
    
    lst = List.query.filter_by(
        list_id=list_uuid,
        user_id=user.user_id
    ).first()
    
    if not lst:
        return jsonify({'error': 'List not found'}), 404
    
    item = ListItem.query.filter_by(
        item_id=item_uuid,
        list_id=lst.list_id
    ).first()
    
    if not item:
        return jsonify({'error': 'Item not found'}), 404
    
    db.session.delete(item)
    db.session.commit()
    
    return jsonify({'message': 'Item removed'}), 200

# ============================================
# ROUTES - INTERACTION LOGS
# ============================================

@app.route('/api/users/<nfc_tag_id>/logs', methods=['GET'])
def get_logs(nfc_tag_id: str):
    """Get interaction logs for user"""
    user = get_user_or_404(nfc_tag_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    limit = request.args.get('limit', 50, type=int)
    logs = InteractionLog.query.filter_by(user_id=user.user_id).order_by(
        InteractionLog.timestamp.desc()
    ).limit(limit).all()
    
    return jsonify({
        'logs': [log.to_dict() for log in logs]
    }), 200

@app.route('/api/logs', methods=['POST'])
def create_log():
    """
    Log interaction (called by LLM)
    
    Request:
    {
      "user_id": "uuid",
      "input_text": "phát nhạc jazz",
      "output_text": "Đang phát nhạc jazz",
      "intent": "play_audio",
      "tools_called": ["play_audio"],
      "latency_ms": 500
    }
    """
    data = request.get_json(silent=True) or {}
    
    user_id = parse_uuid_param(data.get('user_id'))
    if not user_id:
        return jsonify({'error': 'Invalid user_id'}), 400

    user = db.session.get(User, user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    log = InteractionLog(
        user_id=user_id,
        input_text=data.get('input_text'),
        output_text=data.get('output_text'),
        intent=data.get('intent'),
        tools_called=data.get('tools_called', []),
        latency_ms=data.get('latency_ms')
    )
    
    db.session.add(log)
    db.session.commit()
    
    return jsonify({'log_id': str(log.log_id)}), 201

# ============================================
# UTILITY FUNCTIONS
# ============================================

def parse_duration(duration_str: str) -> int:
    """
    Parse duration string to seconds
    
    Examples:
    - "5m" -> 300
    - "30s" -> 30
    - "1h30m" -> 5400
    """
    duration_str = duration_str.lower().strip()
    total_seconds = 0
    
    import re
    
    # Match hours
    hours = re.search(r'(\d+)\s*h', duration_str)
    if hours:
        total_seconds += int(hours.group(1)) * 3600
    
    # Match minutes
    minutes = re.search(r'(\d+)\s*m(?!s)', duration_str)
    if minutes:
        total_seconds += int(minutes.group(1)) * 60
    
    # Match seconds
    seconds = re.search(r'(\d+)\s*s', duration_str)
    if seconds:
        total_seconds += int(seconds.group(1))
    
    return total_seconds

# ============================================
# HEALTH CHECK
# ============================================

@app.route('/health', methods=['GET'])
def health_check():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        app.logger.exception('Database health check failed')
        return jsonify({
            'status': 'error',
            'database': 'postgresql',
            'error': 'Database unavailable',
        }), 503

    return jsonify({
        'status': 'ok',
        'database': 'postgresql',
    }), 200

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=DEFAULT_SERVER_PORT,
        debug=True
    )
