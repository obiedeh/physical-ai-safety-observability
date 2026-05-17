from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations(database_path: str) -> None:
    if database_path == ":memory:":
        return
    project_root = Path(__file__).resolve().parents[2]
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
