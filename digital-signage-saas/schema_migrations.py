"""Runtime schema upgrades for installs without Alembic revision history."""
from sqlalchemy import text, inspect


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

    if 'state_version' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0')
    if 'active_program_id' not in cols:
        _add_column('ALTER TABLE tenant_displays ADD COLUMN active_program_id VARCHAR(64)')
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
