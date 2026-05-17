# Local Deployment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn api.main:app --reload --port 8080
```

In another terminal:

```bash
python -m edge.worker --config configs/local.json --source examples/sample_source.json
```

Docker:

```bash
docker compose --profile demo up --build
```

The local profile stores SQLite data in `data/local-observability.sqlite3`.
