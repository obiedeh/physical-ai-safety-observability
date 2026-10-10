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
- `alembic_version`

