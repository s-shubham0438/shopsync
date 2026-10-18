from alembic import command
from alembic.script import ScriptDirectory

from tests.integration.conftest import alembic_config


def test_single_head() -> None:
    """Exactly one migration head: no unmerged branches."""
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_downgrade_and_upgrade_round_trip(migrated_db: str) -> None:
    cfg = alembic_config(migrated_db)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_models_match_migrations(migrated_db: str) -> None:
    """Fails if a model changed without a matching Alembic migration."""
    command.check(alembic_config(migrated_db))
