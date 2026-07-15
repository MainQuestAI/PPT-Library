"""PPT Library schema migration engine."""

from ppt_lib.migrations.schema_v5 import (
    MigrationPlan,
    MigrationResult,
    apply_migration,
    plan_migration,
    restore_from_backup,
    verify_migration,
)
from ppt_lib.migrations.schema_v6 import TARGET_SCHEMA_VERSION, migrate_v5_to_v6

__all__ = [
    "MigrationPlan",
    "MigrationResult",
    "apply_migration",
    "plan_migration",
    "restore_from_backup",
    "verify_migration",
    "TARGET_SCHEMA_VERSION",
    "migrate_v5_to_v6",
]
