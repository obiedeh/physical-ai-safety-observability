import json
import os
import tempfile

# Tests never touch the operator's database, secret key or cameras. These are
# read at import time by api.services.store / api.services.edge, so they are
# set here before any test module imports the app.
_TEST_DIR = tempfile.mkdtemp(prefix="physical-ai-tests-")
_CONFIG = os.path.join(_TEST_DIR, "config.json")
with open(_CONFIG, "w", encoding="utf-8") as fh:
    json.dump({"app": {"database_path": os.path.join(_TEST_DIR, "test.sqlite3")}}, fh)
os.environ.setdefault("PHYSICAL_AI_CONFIG", _CONFIG)
os.environ.setdefault("PHYSICAL_AI_SECRET_KEY_FILE", os.path.join(_TEST_DIR, "secret.key"))
os.environ.setdefault("PHYSICAL_AI_AUTOSTART", "0")
os.environ.setdefault("PHYSICAL_AI_POST_EVENTS", "0")
os.environ.setdefault("PHYSICAL_AI_REPORTS_DIR", os.path.join(_TEST_DIR, "reports"))
