/**
 * Jarvis Dashboard — Client-side Application
 *
 * Single-page app with hash-based routing, WebSocket real-time updates,
 * and JWT authentication. All data comes from existing API endpoints.
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    const state = {
        token: localStorage.getItem('jarvis_token'),
        ws: null,
        wsConnected: false,
        currentSection: 'today',
        refreshInterval: null,
        events: [],          // recent WebSocket events
        lastUptime: null,
    };

    // -----------------------------------------------------------------------
    // Auth
    // -----------------------------------------------------------------------

    function getToken() {
        return state.token || localStorage.getItem('jarvis_token');
    }

    function setToken(token) {
        state.token = token;
        localStorage.setItem('jarvis_token', token);
    }

    function clearToken() {
        state.token = null;
        localStorage.removeItem('jarvis_token');
    }

    function checkAuth() {
        if (!getToken()) {
            window.location.href = '/login';
            return false;
        }
        return true;
    }

    // -----------------------------------------------------------------------
    // API helpers
    // -----------------------------------------------------------------------

    async function api(path, opts = {}) {
        const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
        const token = getToken();
        if (token) {
            headers['Authorization'] = 'Bearer ' + token;
        }
        try {
            const resp = await fetch(path, Object.assign({}, opts, { headers }));
            if (resp.status === 401) {
                clearToken();
                window.location.href = '/login';
                return null;
            }
            if (resp.status === 204) return {};
            const data = await resp.json();
            return data;
        } catch (err) {
            console.error('API error:', path, err);
            return null;
        }
    }

    async function apiGet(path) { return api(path); }
    async function apiPost(path, body) {
        return api(path, { method: 'POST', body: JSON.stringify(body) });
    }
    async function apiDelete(path) {
        return api(path, { method: 'DELETE' });
    }

    // -----------------------------------------------------------------------
    // WebSocket
    // -----------------------------------------------------------------------

    function connectWebSocket() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = getToken();
        const url = proto + '//' + location.host + '/api/ws' + (token ? '?token=' + token : '');

        try {
            state.ws = new WebSocket(url);
        } catch (e) {
            setWsStatus(false);
            return;
        }

        state.ws.onopen = function () {
            state.wsConnected = true;
            setWsStatus(true);
        };

        state.ws.onclose = function () {
            state.wsConnected = false;
            setWsStatus(false);
            // Reconnect after 5 seconds.
            setTimeout(connectWebSocket, 5000);
        };

        state.ws.onerror = function () {
            state.wsConnected = false;
            setWsStatus(false);
        };

        state.ws.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);
                handleWsEvent(data);
            } catch (e) { /* ignore */ }
        };
    }

    function setWsStatus(connected) {
        const dot = document.getElementById('wsStatus');
        const label = document.getElementById('wsLabel');
        if (dot) dot.className = 'status-dot' + (connected ? '' : ' disconnected');
        if (label) label.textContent = connected ? 'Connected' : 'Disconnected';
    }

    function handleWsEvent(event) {
        // Store event for the Today view.
        state.events.unshift(event);
        if (state.events.length > 100) state.events.pop();

        // Update the relevant section if visible.
        if (state.currentSection === 'today') {
            renderRecentEvents();
        }
    }

    // -----------------------------------------------------------------------
    // Router
    // -----------------------------------------------------------------------

    function navigateTo(section) {
        state.currentSection = section;
        // Update nav items.
        document.querySelectorAll('.nav-item').forEach(function (item) {
            item.classList.toggle('active', item.dataset.section === section);
        });
        // Show/hide sections.
        document.querySelectorAll('.section').forEach(function (el) {
            el.classList.toggle('active', el.id === 'section-' + section);
        });
        // Update title.
        const titles = {
            today: 'Today', tasks: 'Tasks & Workflows', memory: 'Memory',
            knowledge: 'Knowledge Library', audit: 'Audit Log',
            providers: 'AI Providers', goals: 'Goals', settings: 'Settings'
        };
        document.getElementById('pageTitle').textContent = titles[section] || section;
        // Load data for the section.
        loadSection(section);
        // Update URL hash.
        window.location.hash = '#' + section;
    }

    // -----------------------------------------------------------------------
    // Section loaders
    // -----------------------------------------------------------------------

    async function loadSection(section) {
        switch (section) {
            case 'today': await loadToday(); break;
            case 'tasks': await loadTasks(); break;
            case 'memory': await loadMemory(); break;
            case 'knowledge': await loadKnowledge(); break;
            case 'audit': await loadAudit(); break;
            case 'providers': await loadProviders(); break;
            case 'goals': await loadGoals(); break;
            case 'settings': await loadSettings(); break;
        }
    }

    // --- Today ---

    async function loadToday() {
        const status = await apiGet('/api/system/status');
        if (status) {
            renderTodayStats(status);
            renderSubsystemGrid(status.subsystems || {});
        }
        renderRecentEvents();
    }

    function renderTodayStats(status) {
        const el = document.getElementById('todayStats');
        if (!el) return;
        const subs = status.subsystems || {};
        const onlineCount = Object.values(subs).filter(Boolean).length;
        const totalCount = Object.keys(subs).length;
        el.innerHTML =
            '<div class="stat-card"><div class="stat-value">' + (status.version || '?') + '</div><div class="stat-label">Version</div></div>' +
            '<div class="stat-card"><div class="stat-value">' + onlineCount + '/' + totalCount + '</div><div class="stat-label">Subsystems Online</div></div>' +
            '<div class="stat-card"><div class="stat-value">' + formatUptime(status.uptime_seconds) + '</div><div class="stat-label">Uptime</div></div>' +
            '<div class="stat-card"><div class="stat-value badge badge-' + (status.status === 'ok' ? 'green' : 'red') + '">' + (status.status || '?') + '</div><div class="stat-label">Status</div></div>';
    }

    function renderSubsystemGrid(subsystems) {
        // Also used by Today and Settings.
    }

    function renderRecentEvents() {
        const el = document.getElementById('recentEvents');
        if (!el) return;
        if (state.events.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#9881;</div><div class="empty-state-text">No events yet</div></div>';
            return;
        }
        el.innerHTML = state.events.slice(0, 30).map(function (evt) {
            const time = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '';
            return '<div class="event-item">' +
                '<span class="event-time">' + time + '</span>' +
                '<div class="event-content">' +
                '<div class="event-action">' + escHtml(evt.type || evt.action_type || 'event') + '</div>' +
                '<div class="event-detail">' + escHtml(evt.detail || '') + '</div>' +
                '</div></div>';
        }).join('');
    }

    // --- Tasks ---

    async function loadTasks() {
        const data = await apiGet('/api/workflows');
        const el = document.getElementById('taskWorkflows');
        if (!el) return;
        const workflows = (data && data.workflows) || [];
        if (workflows.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-text">No active workflows</div></div>';
            return;
        }
        el.innerHTML = workflows.map(function (w) {
            return '<div style="padding:12px 0; border-bottom:1px solid var(--border);">' +
                '<div style="display:flex; justify-content:space-between;">' +
                '<span>' + escHtml(w.action || w.request_id || 'workflow') + '</span>' +
                '<span class="badge badge-yellow">' + escHtml(w.status || 'pending') + '</span>' +
                '</div>' +
                '<div class="progress-bar"><div class="progress-fill" style="width:50%"></div></div>' +
                '</div>';
        }).join('');
    }

    // --- Memory ---

    async function loadMemory() {
        const category = document.getElementById('memoryCategory').value;
        const search = document.getElementById('memorySearch').value;
        let data;
        if (search) {
            data = await apiGet('/api/memory/search?q=' + encodeURIComponent(search));
        } else {
            const params = category ? '?category=' + encodeURIComponent(category) : '';
            data = await apiGet('/api/memory' + params);
        }
        renderMemoryList(data);
    }

    function renderMemoryList(data) {
        const el = document.getElementById('memoryList');
        if (!el) return;
        const memories = (data && data.memories) || [];
        if (memories.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#9997;</div><div class="empty-state-text">No memories found</div></div>';
            return;
        }
        el.innerHTML = '<div class="table-wrapper"><table><thead><tr><th>ID</th><th>Content</th><th>Category</th><th>Source</th><th>Date</th><th></th></tr></thead><tbody>' +
            memories.map(function (m) {
                return '<tr>' +
                    '<td>' + m.id + '</td>' +
                    '<td style="max-width:400px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(m.content) + '</td>' +
                    '<td><span class="badge badge-blue">' + escHtml(m.category) + '</span></td>' +
                    '<td>' + escHtml(m.source) + '</td>' +
                    '<td>' + escHtml(m.created_at ? new Date(m.created_at).toLocaleDateString() : '') + '</td>' +
                    '<td><button class="btn btn-sm btn-danger" onclick="window.__deleteMemory(' + m.id + ')">Delete</button></td>' +
                    '</tr>';
            }).join('') +
            '</tbody></table></div>';
    }

    window.__deleteMemory = async function (id) {
        if (!confirm('Delete memory ' + id + '?')) return;
        await apiDelete('/api/memory/' + id);
        loadMemory();
    };

    // --- Knowledge ---

    async function loadKnowledge() {
        const el = document.getElementById('knowledgeList');
        if (!el) return;
        el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#9733;</div><div class="empty-state-text">Knowledge entries will appear here when available</div></div>';
    }

    // --- Audit ---

    async function loadAudit() {
        const el = document.getElementById('auditLogBody');
        if (!el) return;
        // Use recent events as a proxy for audit log.
        if (state.events.length === 0) {
            el.innerHTML = '<tr><td colspan="5" class="empty-state-text" style="padding:20px; text-align:center;">No audit entries yet. Events will appear here as they arrive.</td></tr>';
            return;
        }
        const filter = document.getElementById('auditFilter').value;
        const search = document.getElementById('auditSearch').value.toLowerCase();
        var events = state.events;
        if (filter) events = events.filter(function (e) { return (e.action_type || '') === filter; });
        if (search) events = events.filter(function (e) {
            return (e.detail || '').toLowerCase().includes(search) || (e.type || '').toLowerCase().includes(search);
        });
        el.innerHTML = events.slice(0, 50).map(function (e) {
            var time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
            return '<tr>' +
                '<td style="white-space:nowrap;">' + escHtml(time) + '</td>' +
                '<td>' + escHtml(e.source || '-') + '</td>' +
                '<td>' + escHtml(e.action_type || e.type || '-') + '</td>' +
                '<td><span class="badge badge-green">' + escHtml(e.outcome || 'info') + '</span></td>' +
                '<td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(e.detail || '') + '</td>' +
                '</tr>';
        }).join('');
    }

    // --- Providers ---

    async function loadProviders() {
        const providers = await apiGet('/api/system/providers');
        const metrics = await apiGet('/api/system/metrics');
        renderProviders(providers, metrics);
    }

    function renderProviders(providers, metrics) {
        var el = document.getElementById('providerCards');
        if (!el) return;
        var provs = (providers && providers.providers) || [];
        if (provs.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-text">No providers configured</div></div>';
        } else {
            el.innerHTML = provs.map(function (p) {
                var cls = p.available ? 'green' : 'red';
                return '<div class="stat-card">' +
                    '<div class="stat-value" style="font-size:18px;">' + escHtml(p.name) + '</div>' +
                    '<div class="stat-label"><span class="badge badge-' + cls + '">' + (p.available ? 'Online' : 'Offline') + '</span></div>' +
                    '</div>';
            }).join('');
        }
        // Metrics.
        var mEl = document.getElementById('metricsContent');
        if (mEl && metrics && metrics.metrics) {
            var m = metrics.metrics;
            mEl.innerHTML = '<div class="grid-3">' +
                '<div class="stat-card"><div class="stat-value">' + (m.total_requests || 0) + '</div><div class="stat-label">Total Requests</div></div>' +
                '<div class="stat-card"><div class="stat-value">' + Object.keys(m.provider_stats || {}).length + '</div><div class="stat-label">Providers Active</div></div>' +
                '<div class="stat-card"><div class="stat-value">' + Object.keys(m.tool_stats || {}).length + '</div><div class="stat-label">Tools Used</div></div>' +
                '</div>';
        }
    }

    // --- Goals ---

    async function loadGoals() {
        const data = await apiGet('/api/goals');
        renderGoals(data);
    }

    function renderGoals(data) {
        var el = document.getElementById('goalList');
        if (!el) return;
        var goals = (data && data.goals) || [];
        if (goals.length === 0) {
            el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#10003;</div><div class="empty-state-text">No active goals</div></div>';
            return;
        }
        el.innerHTML = goals.map(function (g) {
            var p = g.progress || {};
            var pct = p.percentage || 0;
            var totalTasks = p.total_tasks || 0;
            var doneTasks = p.completed_tasks || 0;
            var priorityCls = g.priority === 'high' || g.priority === 'critical' ? 'red' : g.priority === 'medium' ? 'yellow' : 'green';
            return '<div class="card">' +
                '<div class="card-header">' +
                '<div><span class="card-title">' + escHtml(g.title) + '</span>' +
                ' <span class="badge badge-' + priorityCls + '">' + escHtml(g.priority) + '</span></div>' +
                '<span class="badge badge-blue">' + escHtml(g.status) + '</span>' +
                '</div>' +
                (g.description ? '<p style="color:var(--text-secondary); font-size:13px; margin-bottom:8px;">' + escHtml(g.description) + '</p>' : '') +
                '<div class="progress-bar"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
                '<div class="progress-text">' + doneTasks + ' / ' + totalTasks + ' tasks (' + pct.toFixed(1) + '%)</div>' +
                '</div>';
        }).join('');
    }

    // --- Settings ---

    async function loadSettings() {
        const status = await apiGet('/api/system/status');
        const plugins = await apiGet('/api/plugins');
        renderSettings(status, plugins);
    }

    function renderSettings(status, plugins) {
        var sEl = document.getElementById('settingsStatus');
        if (sEl && status) {
            var subs = status.subsystems || {};
            sEl.innerHTML = '<div class="subsystem-grid">' +
                Object.keys(subs).map(function (name) {
                    var online = subs[name];
                    return '<div class="subsystem-item">' +
                        '<div class="subsystem-dot ' + (online ? 'online' : 'offline') + '"></div>' +
                        '<span class="subsystem-name">' + escHtml(name) + '</span>' +
                        '</div>';
                }).join('') +
                '</div>';
        }
        var pEl = document.getElementById('settingsPlugins');
        if (pEl) {
            var pluginList = (plugins && plugins.plugins) || [];
            if (pluginList.length === 0) {
                pEl.innerHTML = '<div class="empty-state-text">No plugins installed</div>';
            } else {
                pEl.innerHTML = pluginList.map(function (p) {
                    return '<div class="subsystem-item">' +
                        '<div class="subsystem-dot ' + (p.enabled ? 'online' : 'offline') + '"></div>' +
                        '<div><span class="subsystem-name">' + escHtml(p.name) + '</span>' +
                        '<div style="font-size:11px; color:var(--text-muted);">v' + escHtml(p.version) + '</div></div>' +
                        '</div>';
                }).join('');
            }
        }
    }

    // -----------------------------------------------------------------------
    // Uptime
    // -----------------------------------------------------------------------

    function formatUptime(seconds) {
        if (!seconds) return '0s';
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = Math.floor(seconds % 60);
        if (h > 0) return h + 'h ' + m + 'm';
        if (m > 0) return m + 'm ' + s + 's';
        return s + 's';
    }

    function updateUptime() {
        apiGet('/api/system/status').then(function (data) {
            if (data && data.uptime_seconds !== undefined) {
                document.getElementById('uptime').textContent = 'Up ' + formatUptime(data.uptime_seconds);
            }
        });
    }

    // -----------------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------------

    function escHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    // -----------------------------------------------------------------------
    // Event bindings
    // -----------------------------------------------------------------------

    function initEventBindings() {
        // Sidebar navigation.
        document.querySelectorAll('.nav-item').forEach(function (item) {
            item.addEventListener('click', function () {
                navigateTo(item.dataset.section);
            });
        });

        // Sidebar toggle.
        document.getElementById('sidebarToggle').addEventListener('click', function () {
            document.getElementById('app').classList.toggle('sidebar-collapsed');
        });

        // Logout.
        document.getElementById('logoutBtn').addEventListener('click', function () {
            clearToken();
            window.location.href = '/login';
        });

        // Memory search.
        document.getElementById('memorySearch').addEventListener('input', debounce(loadMemory, 300));
        document.getElementById('memoryCategory').addEventListener('change', loadMemory);

        // Add memory.
        document.getElementById('addMemoryBtn').addEventListener('click', function () {
            document.getElementById('addMemoryForm').style.display = 'block';
        });
        document.getElementById('cancelMemoryBtn').addEventListener('click', function () {
            document.getElementById('addMemoryForm').style.display = 'none';
        });
        document.getElementById('saveMemoryBtn').addEventListener('click', async function () {
            var content = document.getElementById('memoryContent').value.trim();
            if (!content) return;
            var category = document.getElementById('memoryNewCategory').value;
            await apiPost('/api/memory', { content: content, category: category });
            document.getElementById('memoryContent').value = '';
            document.getElementById('addMemoryForm').style.display = 'none';
            loadMemory();
        });

        // Goals.
        document.getElementById('addGoalBtn').addEventListener('click', function () {
            document.getElementById('addGoalForm').style.display = 'block';
        });
        document.getElementById('cancelGoalBtn').addEventListener('click', function () {
            document.getElementById('addGoalForm').style.display = 'none';
        });
        document.getElementById('saveGoalBtn').addEventListener('click', async function () {
            var title = document.getElementById('goalTitle').value.trim();
            if (!title) return;
            var description = document.getElementById('goalDescription').value.trim();
            var priority = document.getElementById('goalPriority').value;
            await apiPost('/api/goals', { title: title, description: description, priority: priority });
            document.getElementById('goalTitle').value = '';
            document.getElementById('goalDescription').value = '';
            document.getElementById('addGoalForm').style.display = 'none';
            loadGoals();
        });

        // Audit filters.
        document.getElementById('auditFilter').addEventListener('change', loadAudit);
        document.getElementById('auditSearch').addEventListener('input', debounce(loadAudit, 300));

        // Hash-based routing.
        window.addEventListener('hashchange', function () {
            var hash = window.location.hash.replace('#', '') || 'today';
            if (hash !== state.currentSection) {
                navigateTo(hash);
            }
        });
    }

    function debounce(fn, ms) {
        var timer;
        return function () {
            clearTimeout(timer);
            timer = setTimeout(fn, ms);
        };
    }

    // -----------------------------------------------------------------------
    // Init
    // -----------------------------------------------------------------------

    function init() {
        if (!checkAuth()) return;
        initEventBindings();
        connectWebSocket();

        // Navigate to hash section or default.
        var hash = window.location.hash.replace('#', '') || 'today';
        navigateTo(hash);

        // Auto-refresh every 30 seconds.
        state.refreshInterval = setInterval(function () {
            loadSection(state.currentSection);
            updateUptime();
        }, 30000);

        // Initial uptime.
        updateUptime();
    }

    // Start.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
