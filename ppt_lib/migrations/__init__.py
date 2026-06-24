"""PPT Library schema migration engine."""

from ppt_lib.migrations.schema_v5 import (
    MigrationPlan,
    MigrationResult,
    apply_migration,
    plan_migration,
    restore_from_backup,
    verify_migration,
)

__all__ = [
    "MigrationPlan",
    "MigrationResult",
    "apply_migration",
    "plan_migration",
    "restore_from_backup",
    "verify_migration",
]
