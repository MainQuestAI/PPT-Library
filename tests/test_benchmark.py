"""Tests for benchmark harness (v1.6-G)."""

from __future__ import annotations

import sqlite3

from ppt_lib.benchmark import (
    BenchmarkReport,
    HardwareManifest,
    PerformanceSample,
    benchmark_fts_indexing,
    benchmark_search_latency,
    detect_hardware,
    generate_synthetic_slides,
)


def _create_bench_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # Create asset_identity_map for FTS index_from_slides LEFT JOIN
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT,
            slide_revision_id TEXT,
            legacy_slide_id INTEGER
        )"""
    )
    return conn


class TestHardwareManifest:
    def test_detect_hardware(self):
        hw = detect_hardware()
        assert hw.platform != ""
        assert hw.cpu_count > 0
        assert hw.sqlite_version != ""

    def test_to_json(self):
        hw = HardwareManifest(
            platform="Darwin",
            architecture="arm64",
            python_version="3.12.0",
            cpu_count=8,
            memory_mb=16384,
            sqlite_version="3.45.0",
        )
        j = hw.to_json()
        assert j["platform"] == "Darwin"
        assert j["cpu_count"] == 8


class TestPerformanceSample:
    def test_to_json(self):
        s = PerformanceSample(
            operation="search: architecture",
            slide_count=1000,
            duration_ms=15.5,
            throughput_per_sec=64.5,
            details={"iterations": 5},
        )
        j = s.to_json()
        assert j["operation"] == "search: architecture"
        assert j["duration_ms"] == 15.5
        assert j["details"]["iterations"] == 5


class TestGenerateSynthetic:
    def test_generate_count(self):
        conn = _create_bench_db()
        count = generate_synthetic_slides(conn, 100, presentation_size=10)
        assert count == 100

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM slides")
        assert cursor.fetchone()[0] == 100

    def test_generate_small(self):
        conn = _create_bench_db()
        count = generate_synthetic_slides(conn, 5)
        assert count == 5

    def test_generate_large(self):
        conn = _create_bench_db()
        count = generate_synthetic_slides(conn, 500, presentation_size=50)
        assert count == 500


class TestBenchmarkFTS:
    def test_fts_indexing(self):
        conn = _create_bench_db()
        generate_synthetic_slides(conn, 50, presentation_size=10)
        sample = benchmark_fts_indexing(conn)
        assert sample.operation == "fts_indexing"
        assert sample.slide_count == 50
        assert sample.duration_ms > 0
        assert sample.throughput_per_sec > 0


class TestBenchmarkSearch:
    def test_search_latency(self):
        conn = _create_bench_db()
        generate_synthetic_slides(conn, 50, presentation_size=10)
        benchmark_fts_indexing(conn)
        queries = ["architecture", "data", "security"]
        samples = benchmark_search_latency(conn, queries, iterations=2)
        assert len(samples) == 3
        assert all(s.duration_ms >= 0 for s in samples)

    def test_empty_search(self):
        conn = _create_bench_db()
        generate_synthetic_slides(conn, 10)
        benchmark_fts_indexing(conn)
        samples = benchmark_search_latency(conn, ["nonexistent_xyz"], iterations=1)
        assert len(samples) == 1
        assert samples[0].details["result_count"] == 0


class TestBenchmarkReport:
    def test_to_json(self):
        hw = detect_hardware()
        report = BenchmarkReport(
            run_id="bench_001",
            generated_at="2026-06-23T12:00:00Z",
            tier="10k",
            hardware=hw,
            samples=[
                PerformanceSample("search", 1000, 10.0, 100.0),
            ],
            cold=True,
        )
        j = report.to_json()
        assert j["run_id"] == "bench_001"
        assert j["tier"] == "10k"
        assert len(j["samples"]) == 1
