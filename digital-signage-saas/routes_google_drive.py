"""
Google Drive integration: OAuth, list files, and token storage per tenant.
Users connect their own Google account; videos are streamed via proxy (server stays light for storage).
"""
from flask import Blueprint, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from config import Config
from utils import load_json_file, save_json_file, get_data_file_path
import os
from urllib.parse import urlencode

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.auth.transport.requests import Request
    DRIVE_AVAILABLE = True
except ImportError:
    DRIVE_AVAILABLE = False

from itsdangerous import URLSafeTimedSerializer
from datetime import datetime

drive_bp = Blueprint('google_drive', __name__, url_prefix='/api')

# Scopes: read-only access to Drive metadata and file content
GOOGLE_DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
# MIME types we treat as video (same as ALLOWED_EXTENSIONS concept)
VIDEO_MIMES = {
    'video/mp4', 'video/avi', 'video/x-msvideo', 'video/mpeg', 'video/quicktime',
    'video/x-matroska', 'video/webm', 'video/x-flv',
}


def _state_serializer():
    return URLSafeTimedSerializer(Config.SECRET_KEY, salt='google-drive-oauth')


def _get_drive_credentials(user_id):
    """Load stored tokens and return Credentials if valid; refresh if needed."""
    if not DRIVE_AVAILABLE:
        return None
    data = load_json_file('google_drive.json', {}, user_id)
    token = data.get('access_token')
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return None
    creds = Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=Config.GOOGLE_DRIVE_CLIENT_ID,
        client_secret=Config.GOOGLE_DRIVE_CLIENT_SECRET,
        scopes=GOOGLE_DRIVE_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            data['access_token'] = creds.token
            data['expiry'] = creds.expiry.isoformat() if creds.expiry else None
            save_json_file('google_drive.json', data, user_id)
        except Exception:
            return None
    return creds


def get_drive_service(user_id):
    """Build Drive API service for tenant; returns None if not connected or Drive lib not available."""
    creds = _get_drive_credentials(user_id)
    if not creds:
        return None
    return build('drive', 'v3', credentials=creds)


# ---------------------------------------------------------------------------
# OAuth: start and callback
# ---------------------------------------------------------------------------

@drive_bp.route('/auth/google/drive')
@login_required
def google_drive_start():
    """Redirect user to Google OAuth consent. State = signed user_id."""
    if not DRIVE_AVAILABLE:
        return jsonify({'error': 'Google Drive libraries not installed'}), 503
    if not Config.GOOGLE_DRIVE_CLIENT_ID or not Config.GOOGLE_DRIVE_CLIENT_SECRET:
        return jsonify({'error': 'Google Drive not configured'}), 503
    redirect_uri = Config.GOOGLE_DRIVE_REDIRECT_URI or (request.url_root.rstrip('/') + '/api/auth/google/drive/callback')
    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': Config.GOOGLE_DRIVE_CLIENT_ID,
                'client_secret': Config.GOOGLE_DRIVE_CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=GOOGLE_DRIVE_SCOPES,
        redirect_uri=redirect_uri,
    )
    state = _state_serializer().dumps(current_user.id, salt='google-drive-oauth')
    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent', state=state)
    return redirect(auth_url)


@drive_bp.route('/auth/google/drive/callback')
def google_drive_callback():
    """Exchange code for tokens and store per tenant. Redirect to dashboard."""
    if not DRIVE_AVAILABLE:
        return redirect(url_for('main.dashboard') + '?google_drive=error')
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or not state:
        return redirect(url_for('main.dashboard') + '?google_drive=error')
    try:
        user_id = _state_serializer().loads(state, salt='google-drive-oauth', max_age=600)
    except Exception:
        return redirect(url_for('main.dashboard') + '?google_drive=error')
    redirect_uri = Config.GOOGLE_DRIVE_REDIRECT_URI or (request.url_root.rstrip('/') + '/api/auth/google/drive/callback')
    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': Config.GOOGLE_DRIVE_CLIENT_ID,
                'client_secret': Config.GOOGLE_DRIVE_CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=GOOGLE_DRIVE_SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    data = {
        'access_token': creds.token,
        'refresh_token': creds.refresh_token,
        'expiry': creds.expiry.isoformat() if creds.expiry else None,
        'connected_at': datetime.utcnow().isoformat(),
    }
    save_json_file('google_drive.json', data, user_id)
    return redirect(url_for('main.dashboard') + '?google_drive=connected')


# ---------------------------------------------------------------------------
# Drive files list and status
# ---------------------------------------------------------------------------

@drive_bp.route('/drive/status')
@login_required
def drive_status():
    """Return whether Drive is connected and optional folder_id."""
    data = load_json_file('google_drive.json', {}, current_user.id)
    connected = bool(data.get('refresh_token'))
    return jsonify({
        'connected': connected,
        'folder_id': data.get('folder_id') or 'root',
    })


@drive_bp.route('/drive/files')
@login_required
def drive_list_files():
    """List video files in the user's Drive folder (default root, or folder_id query)."""
    if not DRIVE_AVAILABLE:
        return jsonify({'error': 'Google Drive not available', 'files': []}), 503
    folder_id = request.args.get('folder_id') or 'root'
    user_id = current_user.id
    service = get_drive_service(user_id)
    if not service:
        return jsonify({'error': 'Not connected to Google Drive', 'files': []}), 401
    try:
        # List files in folder; only video MIME types
        q_parts = [f"'{folder_id}' in parents", "trashed = false"]
        mime_cond = ' or '.join([f"mimeType = '{m}'" for m in VIDEO_MIMES])
        q_parts.append(f'({mime_cond})')
        query = ' and '.join(q_parts)
        results = service.files().list(
            q=query,
            pageSize=100,
            fields='nextPageToken, files(id, name, mimeType, size, webContentLink)',
            orderBy='name',
        ).execute()
        files = []
        for f in results.get('files', []):
            files.append({
                'id': f['id'],
                'name': f.get('name', ''),
                'mimeType': f.get('mimeType', ''),
                'size': int(f.get('size', 0)),
                'webContentLink': f.get('webContentLink'),  # may be None for private
            })
        # Also return subfolders so UI can navigate
        q_folders = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders_res = service.files().list(
            q=q_folders,
            pageSize=50,
            fields='files(id, name)',
            orderBy='name',
        ).execute()
        folders = [{'id': x['id'], 'name': x.get('name', '')} for x in folders_res.get('files', [])]
        return jsonify({'files': files, 'folders': folders})
    except Exception as e:
        return jsonify({'error': str(e), 'files': [], 'folders': []}), 500


@drive_bp.route('/drive/folder', methods=['POST'])
@login_required
def drive_set_folder():
    """Set default folder_id for this tenant (so list defaults to this folder)."""
    data = load_json_file('google_drive.json', {}, current_user.id)
    data['folder_id'] = (request.json or {}).get('folder_id') or 'root'
    save_json_file('google_drive.json', data, current_user.id)
    return jsonify({'success': True, 'folder_id': data['folder_id']})


@drive_bp.route('/drive/disconnect', methods=['POST'])
@login_required
def drive_disconnect():
    """Remove stored Drive tokens."""
    save_json_file('google_drive.json', {}, current_user.id)
    return jsonify({'success': True})


def stream_drive_file(user_id, file_id):
    """Yield chunks of file content from Drive for given user. Raises if not connected or file not found."""
    creds = _get_drive_credentials(user_id)
    if not creds:
        raise ValueError('Google Drive not connected')
    import requests
    url = f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media'
    headers = {'Authorization': f'Bearer {creds.token}'}
    r = requests.get(url, headers=headers, stream=True, timeout=60)
    r.raise_for_status()
    for chunk in r.iter_content(chunk_size=65536):
        if chunk:
            yield chunk
