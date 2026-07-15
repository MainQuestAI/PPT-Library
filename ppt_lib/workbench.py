"""Workbench shell for local review and operational verification."""

from __future__ import annotations

import html
from pathlib import Path

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="ppt-library-csrf" content="{{CSRF_TOKEN}}">
    <meta name="ppt-library-workspace" content="{{WORKSPACE_ID}}">
    <meta name="ppt-library-auth-required" content="{{AUTH_REQUIRED}}">
    <title>PPT Library Workbench</title>
    <style>
        :root {
            --bg: #0d1117;
            --surface: #161b22;
            --surface-2: #21262d;
            --border: #30363d;
            --text: #e6edf3;
            --muted: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
            --error: #f85149;
            --radius: 8px;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
        }
        header {
            position: sticky;
            top: 0;
            z-index: 2;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 12px 24px;
            background: rgba(22, 27, 34, 0.96);
            border-bottom: 1px solid var(--border);
        }
        h1 { margin: 0; font-size: 18px; }
        h1 span { color: var(--accent); }
        nav { display: flex; flex-wrap: wrap; gap: 4px; }
        nav a {
            color: var(--muted);
            text-decoration: none;
            padding: 7px 11px;
            border-radius: var(--radius);
            font-size: 14px;
        }
        nav a:hover, nav a:focus-visible, nav a.active {
            color: var(--text);
            background: var(--surface-2);
            outline: none;
        }
        main { max-width: 1200px; margin: 0 auto; padding: 24px; }
        #app-status {
            min-height: 24px;
            margin-bottom: 12px;
            color: var(--muted);
            font-size: 13px;
        }
        #app-status.error { color: var(--error); }
        #app-status.success { color: var(--success); }
        .toolbar, .search-bar { display: flex; gap: 8px; margin-bottom: 16px; }
        input, select {
            min-width: 0;
            flex: 1;
            padding: 9px 12px;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            background: var(--bg);
            color: var(--text);
        }
        button {
            padding: 9px 14px;
            border: 1px solid transparent;
            border-radius: var(--radius);
            background: var(--accent);
            color: white;
            cursor: pointer;
            font-weight: 600;
        }
        button.secondary { background: var(--surface-2); border-color: var(--border); }
        button:disabled { opacity: 0.55; cursor: wait; }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
        }
        .stat, .card {
            padding: 16px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
        }
        .card { margin-bottom: 14px; overflow-x: auto; }
        .stat .value { color: var(--accent); font-size: 28px; font-weight: 700; }
        .stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
        h2 { margin: 0 0 16px; font-size: 20px; }
        h3 { margin: 0 0 8px; font-size: 15px; }
        p { margin: 6px 0; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--border); }
        th { color: var(--muted); font-weight: 600; }
        code { color: #a5d6ff; }
        .muted, .empty-state { color: var(--muted); }
        .empty-state { padding: 40px 16px; text-align: center; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            background: var(--surface-2);
            color: var(--muted);
            font-size: 12px;
        }
        @media (max-width: 760px) {
            header { align-items: flex-start; flex-direction: column; padding: 12px 16px; }
            main { padding: 16px; }
            .toolbar, .search-bar { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div id="app">
        <header>
            <h1>PPT Library <span>Workbench</span></h1>
            <nav aria-label="Workbench sections">
                <a href="#dashboard" data-page="dashboard">Dashboard</a>
                <a href="#search" data-page="search">Search</a>
                <a href="#assets" data-page="assets">Assets</a>
                <a href="#health" data-page="health">Health</a>
                <a href="#review" data-page="review">Review</a>
                <a href="#jobs" data-page="jobs">Jobs</a>
            </nav>
        </header>
        <main>
            <div id="app-status" role="status" aria-live="polite"></div>
            <section id="content" tabindex="-1"></section>
        </main>
    </div>
    <script>
        const API = '/api/v1';
        const csrfToken = document.querySelector('meta[name="ppt-library-csrf"]').content;
        const workspaceId = document.querySelector('meta[name="ppt-library-workspace"]').content;
        const authRequired = document.querySelector('meta[name="ppt-library-auth-required"]').content === 'true';
        const content = document.getElementById('content');
        const statusRegion = document.getElementById('app-status');

        function escapeHTML(value) {
            return String(value ?? '').replace(/[&<>"]/g, char => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'
            })[char]);
        }

        function setStatus(message = '', kind = '') {
            statusRegion.textContent = message;
            statusRegion.className = kind;
        }

        function getAuthToken() {
            let token = sessionStorage.getItem('ppt-library-auth-token') || '';
            if (authRequired && !token) {
                token = window.prompt('Enter the shared whole-library administrator token') || '';
                if (token) sessionStorage.setItem('ppt-library-auth-token', token);
            }
            return token;
        }

        async function fetchJSON(path, options = {}, apiBase = API) {
            const method = (options.method || 'GET').toUpperCase();
            const headers = new Headers(options.headers || {});
            headers.set('Accept', 'application/json');
            headers.set('X-Workspace-ID', workspaceId);
            if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
                headers.set('X-CSRF-Token', csrfToken);
            }
            const authToken = getAuthToken();
            if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
            if (options.body && !headers.has('Content-Type')) {
                headers.set('Content-Type', 'application/json');
            }
            const response = await fetch(apiBase + path, {...options, method, headers});
            const payload = await response.json().catch(() => ({detail: `HTTP ${response.status}`}));
            if (!response.ok) {
                throw new Error(payload.detail || payload.message || `HTTP ${response.status}`);
            }
            return payload;
        }

        function emptyState(message) {
            return `<div class="empty-state">${escapeHTML(message)}</div>`;
        }

        async function loadDashboard() {
            content.innerHTML = '<h2>Dashboard</h2>' + emptyState('Loading library status…');
            const payload = await fetchJSON('/status');
            const data = payload.data || {};
            const stats = [
                ['Slides', data.slides_count || 0, 'stat-slides'],
                ['Presentations', data.presentations_count || 0, 'stat-presentations'],
                ['Embeddings', data.embeddings_count || 0, 'stat-embeddings'],
                ['Schema', `v${data.schema_version || 0}`, 'stat-schema'],
            ];
            content.innerHTML = '<h2>Dashboard</h2><div class="stat-grid">' + stats.map(([label, value, id]) =>
                `<div class="stat"><div class="value" id="${id}">${escapeHTML(value)}</div><div class="label">${label}</div></div>`
            ).join('') + '</div>';
        }

        function renderSearch() {
            content.innerHTML = `
                <h2>Search</h2>
                <form class="search-bar" id="search-form">
                    <label class="muted" for="search-input">Query</label>
                    <input id="search-input" name="q" autocomplete="off" placeholder="Architecture, case study, industry…" required>
                    <button type="submit">Search</button>
                </form>
                <div id="search-results">${emptyState('Enter a query to search the library.')}</div>`;
            document.getElementById('search-form').addEventListener('submit', async event => {
                event.preventDefault();
                const query = document.getElementById('search-input').value.trim();
                if (!query) return;
                const target = document.getElementById('search-results');
                target.innerHTML = emptyState('Searching…');
                try {
                    const requestId = globalThis.crypto?.randomUUID
                        ? globalThis.crypto.randomUUID()
                        : `workbench-${Date.now()}`;
                    const payload = await fetchJSON('/search', {
                        method: 'POST',
                        body: JSON.stringify({
                            contract: 'ppt_library.search_request.v2',
                            request_id: requestId,
                            query,
                            top_k: 20,
                            search_profile: 'default',
                            explain: false,
                        }),
                    }, '/api/v2');
                    const candidates = payload.data?.candidates || [];
                    target.innerHTML = candidates.length ? candidates.map((item, index) => `
                        <article class="card">
                            <h3>${index + 1}. ${escapeHTML(item.title || `Slide ${item.slide_id || item.canonical_asset_id || ''}`)}</h3>
                            <p>${escapeHTML(item.snippet || item.text_summary || item.summary || '')}</p>
                            <p class="muted">Score: ${escapeHTML(item.score ?? item.fused_score ?? item.final_score ?? 'n/a')}</p>
                        </article>`).join('') : emptyState('No matching slides. Try a broader query.');
                } catch (error) {
                    target.innerHTML = emptyState(error.message);
                }
            });
        }

        async function renderAssets() {
            content.innerHTML = '<h2>Assets</h2>' + emptyState('Loading assets…');
            const payload = await fetchJSON('/assets?limit=100');
            const assets = payload.data?.assets || [];
            content.innerHTML = '<h2>Assets</h2>' + (assets.length ? `
                <div class="card"><table><thead><tr><th>Asset ID</th><th>Type</th><th>Created</th></tr></thead><tbody>
                ${assets.map(asset => `<tr>
                    <td><code>${escapeHTML(asset.asset_id)}</code></td>
                    <td>${escapeHTML(asset.asset_type)}</td>
                    <td>${escapeHTML(asset.created_at)}</td>
                </tr>`).join('')}
                </tbody></table></div>` : emptyState('No canonical assets have been indexed yet.'));
        }

        async function renderHealth() {
            content.innerHTML = `
                <div class="toolbar"><h2 style="flex:1">Health</h2><button id="health-scan">Run scan</button></div>
                <div id="health-results">${emptyState('Loading health findings…')}</div>`;
            const target = document.getElementById('health-results');
            const load = async () => {
                const payload = await fetchJSON('/health/findings?limit=100');
                const findings = payload.data?.findings || [];
                target.innerHTML = findings.length ? findings.map(item => `
                    <article class="card"><h3>${escapeHTML(item.code || item.finding_type || item.finding_id)}</h3>
                    <p>${escapeHTML(item.message || item.details || '')}</p>
                    <span class="badge">${escapeHTML(item.severity || 'unknown')}</span>
                </article>`).join('') : emptyState('No open health findings.');
            };
            document.getElementById('health-scan').addEventListener('click', async event => {
                const button = event.currentTarget;
                button.disabled = true;
                try {
                    await fetchJSON('/health/scan', {method: 'POST'});
                    setStatus('Health scan completed.', 'success');
                    await load();
                } catch (error) {
                    setStatus(error.message, 'error');
                } finally {
                    button.disabled = false;
                }
            });
            await load();
        }

        async function renderReview() {
            content.innerHTML = `
                <div class="toolbar"><h2 style="flex:1">Review</h2><button id="review-classify">Generate suggestions</button></div>
                <div id="review-status">${emptyState('Loading review status…')}</div>`;
            const target = document.getElementById('review-status');
            const load = async () => {
                const payload = await fetchJSON('/review/status');
                target.innerHTML = `<div class="card"><pre>${escapeHTML(JSON.stringify(payload.data || {}, null, 2))}</pre></div>`;
            };
            document.getElementById('review-classify').addEventListener('click', async event => {
                const button = event.currentTarget;
                button.disabled = true;
                try {
                    await fetchJSON('/review/classify?limit=100', {method: 'POST'});
                    setStatus('Classification suggestions refreshed.', 'success');
                    await load();
                } catch (error) {
                    setStatus(error.message, 'error');
                } finally {
                    button.disabled = false;
                }
            });
            await load();
        }

        async function renderJobs() {
            content.innerHTML = '<h2>Jobs</h2>' + emptyState('Loading jobs…');
            const payload = await fetchJSON('/jobs?limit=100');
            const jobs = payload.data?.jobs || [];
            content.innerHTML = '<h2>Jobs</h2>' + (jobs.length ? jobs.map(job => `
                <article class="card"><h3>${escapeHTML(job.job_type)} <span class="badge">${escapeHTML(job.status)}</span></h3>
                <p><code>${escapeHTML(job.job_id)}</code></p>
                <p class="muted">${escapeHTML(job.completed_units)} / ${escapeHTML(job.total_units)} units</p>
                </article>`).join('') : emptyState('No jobs recorded.'));
        }

        async function renderPage() {
            setStatus('');
            const page = (location.hash || '#dashboard').slice(1);
            document.querySelectorAll('nav a').forEach(link => link.classList.toggle('active', link.dataset.page === page));
            try {
                if (page === 'search') renderSearch();
                else if (page === 'assets') await renderAssets();
                else if (page === 'health') await renderHealth();
                else if (page === 'review') await renderReview();
                else if (page === 'jobs') await renderJobs();
                else await loadDashboard();
                content.focus({preventScroll: true});
            } catch (error) {
                content.innerHTML = emptyState(error.message);
                setStatus(error.message, 'error');
            }
        }

        window.addEventListener('hashchange', renderPage);
        renderPage();
    </script>
</body>
</html>
"""


def get_dashboard_html(
    *,
    csrf_token: str = "",
    workspace_id: str = "default",
    auth_required: bool = False,
) -> str:
    """Return the dashboard HTML with escaped runtime security context."""
    return (
        DASHBOARD_HTML
        .replace("{{CSRF_TOKEN}}", html.escape(csrf_token, quote=True))
        .replace("{{WORKSPACE_ID}}", html.escape(workspace_id, quote=True))
        .replace("{{AUTH_REQUIRED}}", "true" if auth_required else "false")
    )


def get_static_dir() -> Path:
    """Return the optional static asset directory."""
    return Path(__file__).parent / "static"
