"""Workbench shell: static HTML dashboard for local review (v1.8-C).

Provides the base HTML template and static assets for the workbench UI.
"""

from __future__ import annotations

from pathlib import Path

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PPT Library Workbench</title>
    <style>
        :root {
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #e6edf3;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
            --error: #f85149;
            --radius: 6px;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
        }
        header {
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        header h1 { font-size: 18px; font-weight: 600; }
        header h1 span { color: var(--accent); }
        nav { display: flex; gap: 4px; }
        nav a {
            color: var(--text-muted);
            text-decoration: none;
            padding: 6px 12px;
            border-radius: var(--radius);
            font-size: 14px;
        }
        nav a:hover, nav a.active {
            color: var(--text);
            background: var(--border);
        }
        main { padding: 24px; max-width: 1200px; margin: 0 auto; }
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px;
            margin-bottom: 16px;
        }
        .card h2 { font-size: 16px; margin-bottom: 12px; }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        .stat {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px;
            text-align: center;
        }
        .stat .value {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent);
        }
        .stat .label {
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge-success { background: rgba(63, 185, 80, 0.15); color: var(--success); }
        .badge-warning { background: rgba(210, 153, 34, 0.15); color: var(--warning); }
        .badge-error { background: rgba(248, 81, 73, 0.15); color: var(--error); }
        .badge-info { background: rgba(88, 166, 255, 0.15); color: var(--accent); }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th, td {
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        th { color: var(--text-muted); font-weight: 500; }
        .search-bar {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
        }
        .search-bar input {
            flex: 1;
            padding: 8px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            color: var(--text);
            font-size: 14px;
        }
        .search-bar button {
            padding: 8px 16px;
            background: var(--accent);
            color: #fff;
            border: none;
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 14px;
        }
        .empty-state {
            text-align: center;
            padding: 48px;
            color: var(--text-muted);
        }
        #app { min-height: 100vh; }
    </style>
</head>
<body>
    <div id="app">
        <header>
            <h1>PPT Library <span>Workbench</span></h1>
            <nav>
                <a href="#dashboard" class="active" data-page="dashboard">Dashboard</a>
                <a href="#search" data-page="search">Search</a>
                <a href="#assets" data-page="assets">Assets</a>
                <a href="#health" data-page="health">Health</a>
                <a href="#review" data-page="review">Review</a>
                <a href="#jobs" data-page="jobs">Jobs</a>
            </nav>
        </header>
        <main id="content">
            <div class="stat-grid">
                <div class="stat">
                    <div class="value" id="stat-slides">-</div>
                    <div class="label">Slides</div>
                </div>
                <div class="stat">
                    <div class="value" id="stat-presentations">-</div>
                    <div class="label">Presentations</div>
                </div>
                <div class="stat">
                    <div class="value" id="stat-embeddings">-</div>
                    <div class="label">Embeddings</div>
                </div>
                <div class="stat">
                    <div class="value" id="stat-schema">-</div>
                    <div class="label">Schema</div>
                </div>
            </div>
        </main>
    </div>
    <script>
        const API = '/api/v1';

        async function fetchJSON(path) {
            const r = await fetch(API + path);
            return r.json();
        }

        async function loadDashboard() {
            try {
                const data = await fetchJSON('/status');
                if (data.success && data.data) {
                    document.getElementById('stat-slides').textContent = data.data.slides_count || 0;
                    document.getElementById('stat-presentations').textContent = data.data.presentations_count || 0;
                    document.getElementById('stat-embeddings').textContent = data.data.embeddings_count || 0;
                    document.getElementById('stat-schema').textContent = 'v' + (data.data.schema_version || 0);
                }
            } catch (e) {
                document.getElementById('content').innerHTML =
                    '<div class="empty-state">Unable to connect to API server.<br>Start with: ppt-lib workbench</div>';
            }
        }

        document.querySelectorAll('nav a').forEach(a => {
            a.addEventListener('click', e => {
                document.querySelectorAll('nav a').forEach(x => x.classList.remove('active'));
                a.classList.add('active');
            });
        });

        loadDashboard();
    </script>
</body>
</html>
"""


def get_dashboard_html() -> str:
    """Return the dashboard HTML content."""
    return DASHBOARD_HTML


def get_static_dir() -> Path:
    """Return the path to static assets directory."""
    return Path(__file__).parent / "static"
