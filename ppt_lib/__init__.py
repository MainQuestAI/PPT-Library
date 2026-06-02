"""PPT Library package."""

from ppt_lib.db import SCHEMA_VERSION, get_schema_version, recompute_slide_stats

__all__ = [
    "SCHEMA_VERSION",
    "get_schema_version",
    "recompute_slide_stats",
]
