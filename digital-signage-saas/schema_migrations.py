"""Runtime schema upgrades for installs without Alembic revision history."""
from sqlalchemy import text, inspect


def migrate_users_after_create_all(db, app):
    """Best-effort add of missing users columns for legacy installs without Alembic history."""
    engine = db.engine
    insp = inspect(engine)
    if not insp.has_table('users'):
        return

    cols = {c['name']: c for c in insp.get_columns('users')}

    def _add_column(sql):
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:
            msg = str(e).lower()
            if 'duplicate' in msg or 'already exists' in msg or ('column' in msg and 'exists' in msg):
                return
            app.logger.warning('users migration note: %s', e)

    if 'connection_code' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN connection_code VARCHAR(9)")
    if 'is_admin' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
    if 'email_verified' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 0")
    if 'email_verify_token' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN email_verify_token VARCHAR(64)")
    if 'email_verify_expires' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN email_verify_expires TIMESTAMP")
    if 'plan' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN plan VARCHAR(50) DEFAULT 'free'")
    if 'trial_ends_at' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN trial_ends_at TIMESTAMP")
    if 'subscription_status' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(50) DEFAULT 'trial'")
    if 'stripe_customer_id' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(100)")
    if 'stripe_subscription_id' not in cols:
        _add_column("ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(100)")

    # Optional indexes/constraints (best effort only)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_connection_code ON users (connection_code)"))
    except Exception:
        pass


def migrate_tenant_displays_after_create_all(db, app):
    """Add new columns and migrate command_id to string (Postgres). SQLite may rebuild table."""
    engine = db.engine
    insp = inspect(engine)
    if not insp.has_table('tenant_displays'):
        return

    dialect = engine.dialect.name
    cols = {c['name']: c for c in insp.get_columns('tenant_displays')}

    def _add_column(sql):
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:
            msg = str(e).lower()
            if 'duplicate' in msg or 'already exists' in msg or ('column' in msg and 'exists' in msg):
                return
            app.logger.warning('tenant_displays migration note: %s', e)

    if 'current_video' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN current_video VARCHAR(500)')
    if 'command_id' not in cols:
        _add_column("ALTER TABLE tenant_displays ADD COLUMN command_id VARCHAR(40) NOT NULL DEFAULT ''")
    if 'status' not in cols:
        _add_column("ALTER TABLE tenant_displays ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'idle'")
    if 'device_info_json' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN device_info_json TEXT')
    if 'screenshot_requested' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN screenshot_requested BOOLEAN NOT NULL DEFAULT 0')
    if 'clear_cache' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN clear_cache BOOLEAN NOT NULL DEFAULT 0')
    if 'playback_cache_only' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN playback_cache_only BOOLEAN NOT NULL DEFAULT 0')
    if 'state_version' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0')
    if 'active_program_id' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN active_program_id VARCHAR(64)')
    if 'cache_manifest_json' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN cache_manifest_json TEXT')
    if 'cache_manifest_file_count' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN cache_manifest_file_count INTEGER')
    if 'cache_manifest_total_bytes' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN cache_manifest_total_bytes BIGINT')
    if 'cache_manifest_updated_at' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN cache_manifest_updated_at VARCHAR(40)')
    if 'cache_delete_keys_json' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN cache_delete_keys_json TEXT')
    if 'current_video_display_name' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN current_video_display_name VARCHAR(250)')
    if 'screenshot_data' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN screenshot_data TEXT')
    if 'screenshot_timestamp' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN screenshot_timestamp VARCHAR(40)')
    if 'download_progress_json' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN download_progress_json TEXT')

    if dialect == 'postgresql':
        try:
            with engine.connect() as conn:
                dt = conn.execute(text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='tenant_displays' AND column_name='command_id'"
                )).scalar()
        except Exception:
            dt = None
        if dt in ('integer', 'bigint', 'smallint'):
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE tenant_displays ALTER COLUMN command_id TYPE VARCHAR(40) "
                        "USING (CASE WHEN command_id IS NULL THEN '' ELSE command_id::text END)"
                    ))
            except Exception as e:
                app.logger.warning('command_id varchar migration (pg): %s', e)
        return

    if dialect != 'sqlite':
        return

    # SQLite: INTEGER affinity on command_id breaks UUID strings — rebuild if needed.
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT typeof(command_id) AS t FROM tenant_displays LIMIT 1")).fetchone()
            aff = row[0] if row else None
    except Exception:
        aff = None

    if aff not in ('integer', 'real'):
        return

    app.logger.info('Rebuilding tenant_displays (SQLite) for string command_id support')
    from models import TenantDisplay

    with engine.begin() as conn:
        rows = [dict(m) for m in conn.execute(text("SELECT * FROM tenant_displays")).mappings().all()]
        conn.execute(text("ALTER TABLE tenant_displays RENAME TO tenant_displays_old"))

    db.create_all()

    for od in rows:
        od.pop('id', None)
        cid = od.get('command_id')
        if cid is None or cid == '' or cid == 0:
            cmd = ''
        else:
            cmd = str(cid).strip()
            if cmd.isdigit():
                cmd = f'legacy-{cmd}'
        row = TenantDisplay(
            user_id=od['user_id'],
            device_id=od['device_id'],
            display_name=(od.get('display_name') or 'Display')[:200],
            first_seen_iso=(od.get('first_seen_iso') or '')[:40],
            last_seen_iso=(od.get('last_seen_iso') or '')[:40],
            current_video=od.get('current_video'),
            command_id=(cmd or '')[:40],
            state_version=int(od.get('state_version') or 0),
            status=(od.get('status') or 'idle')[:32],
            device_info_json=od.get('device_info_json'),
            screenshot_requested=bool(od.get('screenshot_requested', False)),
            clear_cache=bool(od.get('clear_cache', False)),
            playback_cache_only=bool(od.get('playback_cache_only', False)),
            active_program_id=od.get('active_program_id'),
            cache_manifest_json=od.get('cache_manifest_json'),
            cache_manifest_file_count=od.get('cache_manifest_file_count'),
            cache_manifest_total_bytes=od.get('cache_manifest_total_bytes'),
            cache_manifest_updated_at=od.get('cache_manifest_updated_at'),
            cache_delete_keys_json=od.get('cache_delete_keys_json'),
            current_video_display_name=od.get('current_video_display_name'),
            screenshot_data=od.get('screenshot_data'),
            screenshot_timestamp=od.get('screenshot_timestamp'),
            download_progress_json=od.get('download_progress_json'),
        )
        db.session.add(row)
    db.session.commit()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tenant_displays_old"))
