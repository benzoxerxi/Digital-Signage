"""Short-lived JWTs for digital signage players (APK) and SSE stream auth."""
from datetime import datetime, timedelta
import functools

import jwt
from flask import request, jsonify, current_app


def _secret():
    return current_app.config.get('SECRET_KEY') or 'dev-insecure'


def issue_device_access_token(user_id, ttl_seconds=None):
    ttl = ttl_seconds or int(current_app.config.get('DEVICE_JWT_TTL_SECONDS', 86400))
    now = datetime.utcnow()
    payload = {
        'sub': str(int(user_id)),
        'typ': 'device',
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm='HS256')


def decode_device_access_token(token):
    if not token:
        return None
    try:
        return jwt.decode(token, _secret(), algorithms=['HS256'], options={'require': ['exp', 'sub']})
    except jwt.PyJWTError:
        return None


def get_bearer_token():
    auth = request.headers.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return None


def resolve_playback_user_id():
    """Return (user_id, error_response) for playback routes. Prefers Bearer device JWT, then legacy code."""
    from models import User

    bearer = get_bearer_token()
    if bearer:
        claims = decode_device_access_token(bearer)
        if claims and claims.get('typ') == 'device':
            try:
                return int(claims['sub']), None
            except (TypeError, ValueError):
                return None, (jsonify({'error': 'Invalid token', 'message': 'Bad subject'}), 401)
        return None, (jsonify({'error': 'Invalid token', 'message': 'Use a device access token from POST /api/auth/device-token'}), 401)  # noqa: E501

    params = request.args.to_dict() if request.args else {}
    if request.is_json and request.get_json(silent=True):
        body = request.get_json(silent=True) or {}
        for k, v in body.items():
            if k not in params or params.get(k) in (None, ''):
                params[k] = v
    code = params.get('code')
    if code:
        user = User.get_by_connection_code(code)
        if user:
            return user.id, None
    uid = params.get('user_id')
    if uid is not None:
        try:
            u = User.query.get(int(uid))
            if u:
                return u.id, None
        except (TypeError, ValueError):
            pass
    return None, None


def require_device_or_session_user():
    """Decorator: for routes that accept either Flask-Login session or device JWT (Bearer)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            from flask_login import current_user
            if current_user.is_authenticated:
                return fn(*args, **kwargs)
            uid, err = resolve_playback_user_id()
            if err:
                return err
            if uid is None:
                return jsonify({'error': 'Unauthorized', 'message': 'Log in, send Bearer device token, or ?code='}), 401
            kwargs['_playback_user_id'] = uid
            return fn(*args, **kwargs)
        return wrapped
    return decorator
