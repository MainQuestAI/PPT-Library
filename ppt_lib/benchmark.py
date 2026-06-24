"""Scale and performance harness for reproducible benchmarks (v1.6-G).

Generates synthetic datasets at 10k/50k/100k slide tiers and measures
indexing time, search latency, and memory usage.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HardwareManifest:
    """Hardware and environment details for a benchmark run."""

    platform: str
    architecture: str
    python_version: str
    cpu_count: int
    memory_mb: int | None
    sqlite_version: str

    def to_json(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "architecture": self.architecture,
            "python_version": self.python_version,
            "cpu_count": self.cpu_count,
            "memory_mb": self.memory_mb,
            "sqlite_version": self.sqlite_version,
        }


@dataclass(frozen=True)
class PerformanceSample:
    """A single performance measurement."""

    operation: str
    slide_count: int
    duration_ms: float
    throughput_per_sec: float
    details: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "operation": self.operation,
            "slide_count": self.slide_count,
            "duration_ms": round(self.duration_ms, 2),
            "throughput_per_sec": round(self.throughput_per_sec, 2),
        }
        if self.details:
            d["details"] = self.details
        return d


@dataclass(frozen=True)
class BenchmarkReport:
    """Complete benchmark report."""

    run_id: str
    generated_at: str
    tier: str  # "10k" | "50k" | "100k"
    hardware: HardwareManifest
    samples: list[PerformanceSample]
    cold: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "tier": self.tier,
            "cold": self.cold,
            "hardware": self.hardware.to_json(),
            "samples": [s.to_json() for s in self.samples],
        }


def detect_hardware() -> HardwareManifest:
    """Detect current hardware and environment."""

    mem_mb: int | None = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_mb = int(line.split()[1]) // 1024
                    break
    except (FileNotFoundError, PermissionError, ValueError):
        pass

    return HardwareManifest(
        platform=platform.system(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        cpu_count=os.cpu_count() or 0,
        memory_mb=mem_mb,
        sqlite_version=sqlite3.sqlite_version,
    )


def generate_synthetic_slides(
    conn: sqlite3.Connection,
    count: int,
    *,
    presentation_size: int = 20,
) -> int:
    """Insert synthetic slides into the database for benchmarking.

    Returns the number of slides inserted.
    """
    cursor = conn.cursor()

    # Ensure tables exist
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS presentations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT,
            filename TEXT,
            project_name TEXT,
            slide_count INTEGER DEFAULT 0,
            content_hash TEXT,
            file_size INTEGER DEFAULT 0,
            file_mtime REAL DEFAULT 0
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS slides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            presentation_id INTEGER,
            slide_index INTEGER,
            title TEXT,
            text_content TEXT,
            screenshot_hash TEXT,
            source TEXT DEFAULT 'text_extraction',
            extraction_warnings TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            slide_revision_id TEXT,
            canonical_asset_id TEXT
        )"""
    )

    topics = [
        "architecture", "microservices", "cloud", "data", "analytics",
        "machine learning", "security", "devops", "infrastructure",
        "api design", "database", "networking", "performance",
        "scalability", "monitoring", "deployment", "testing",
        "automation", "integration", "migration",
    ]

    inserted = 0
    pres_count = max(1, count // presentation_size)

    for p in range(pres_count):
        topic = topics[p % len(topics)]
        cursor.execute(
            "INSERT INTO presentations (path, filename, project_name, slide_count) VALUES (?, ?, ?, ?)",
            (f"/bench/deck_{p}.pptx", f"deck_{p}.pptx", f"Benchmark {topic}", presentation_size),
        )
        pres_id = cursor.lastrowid

        slides_this_pres = min(presentation_size, count - inserted)
        for s in range(slides_this_pres):
            title = f"{topic.title()} Slide {s+1}"
            text = f"This slide covers {topic} concepts including implementation details for deck {p}."
            cursor.execute(
                "INSERT INTO slides (presentation_id, slide_index, title, text_content) VALUES (?, ?, ?, ?)",
                (pres_id, s + 1, title, text),
            )
            inserted += 1

    conn.commit()
    return inserted


def benchmark_search_latency(
    conn: sqlite3.Connection,
    queries: list[str],
    *,
    iterations: int = 5,
) -> list[PerformanceSample]:
    """Measure search latency across multiple queries and iterations."""
    from ppt_lib.fts_search import lexical_search

    samples: list[PerformanceSample] = []

    for query in queries:
        durations: list[float] = []
        result_count = 0

        for _ in range(iterations):
            start = time.monotonic()
            results = lexical_search(conn, query, top_k=10)
            elapsed_ms = (time.monotonic() - start) * 1000
            durations.append(elapsed_ms)
            result_count = len(results)

        avg_ms = sum(durations) / len(durations)
        throughput = 1000.0 / avg_ms if avg_ms > 0 else 0.0

        samples.append(PerformanceSample(
            operation=f"search: {query[:30]}",
            slide_count=0,
            duration_ms=avg_ms,
            throughput_per_sec=throughput,
            details={
                "iterations": iterations,
                "min_ms": round(min(durations), 2),
                "max_ms": round(max(durations), 2),
                "result_count": result_count,
            },
        ))

    return samples


def benchmark_fts_indexing(conn: sqlite3.Connection) -> PerformanceSample:
    """Measure FTS5 indexing performance."""
    from ppt_lib.fts_search import create_fts_tables, index_from_slides

    create_fts_tables(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM slides")
    slide_count = cursor.fetchone()[0]

    start = time.monotonic()
    indexed = index_from_slides(conn)
    elapsed_ms = (time.monotonic() - start) * 1000
    throughput = indexed / (elapsed_ms / 1000) if elapsed_ms > 0 else 0.0

    return PerformanceSample(
        operation="fts_indexing",
        slide_count=slide_count,
        duration_ms=elapsed_ms,
        throughput_per_sec=throughput,
        details={"indexed_count": indexed},
    )
