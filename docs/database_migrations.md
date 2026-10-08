# Database Migrations

The backend uses SQLite for local and edge deployments, with schema changes managed by
Alembic.

Run migrations:

```bash
PHYSICAL_AI_CONFIG=configs/local.json alembic upgrade head
```

The API store also applies migrations automatically for file-backed SQLite databases on
startup. `:memory:` stores keep a small bootstrap path for isolated tests only.

Current schema:

- `cameras`
- `events`
- `incidents`
- `feedback`
- `camera_configs` (JSON payload per camera; connector fields such as `source_url`,
  `device`, `upload_id` and `playback` live in the payload with defaults, so adding a
  connector needs no column change)
- `settings`
- `uploads` (0004: uploaded video files, with the declared `source_kind`; the bytes live
  next to the database under `uploads/`)
- `alembic_version`

Migrations are additive. `tests/test_store_upgrade.py` loads a database dumped at Alembic
head 0003 from the previous release and checks that every camera, secret, feed URL and
setting comes back unchanged after upgrading to head.

