/* ============================================
   Cold Call Platform — Application principale
   Navigation, API calls, Power Dialer, Charts
   Tout connecte entre les onglets.
   ============================================ */

const API = '/api';

// ============================================
// AUTH — Token JWT + login/register/logout
// ============================================
let accessToken = localStorage.getItem('access_token') || null;

// ============================================
// NAVIGATION — Chargement dynamique par onglet
// ============================================
document.addEventListener('DOMContentLoaded', async () => {
    initNavigation();

    // Verifier si on a un token valide
    if (accessToken) {
        const me = await apiFetch('/auth/me');
        if (me) {
            hideAuthOverlay();
            updateUserInfo(me);
            initApp();
            return;
        }
    }
    // Pas de token ou token invalide — afficher le login
    showAuthOverlay();
});

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const section = item.dataset.section;
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
            document.getElementById(`section-${section}`).classList.add('active');
            document.getElementById('pageTitle').textContent = item.querySelector('span').textContent;

            // Synchroniser la bottom nav mobile
            document.querySelectorAll('.mobile-nav-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.section === section);
            });

            // Charger les donnees specifiques a chaque onglet
            switch (section) {
                case 'dashboard':
                    loadDashboard();
                    break;
                case 'dialer':
                    preloadDialerLead();
                    break;
                case 'leads':
                    loadLeads();
                    loadFilters();
                    break;
                case 'callbacks':
                    loadCallbacksPage();
                    break;
                case 'scraper':
                    loadScraperHistory();
                    loadScraperSuggestions();
                    break;
                case 'stats':
                    loadStatsPage();
                    break;
                case 'profil':
                    loadProfil();
                    break;
                case 'tests':
                    break;
            }
        });
    });

    // --- Sidebar toggle (hamburger) ---
    const sidebar = document.getElementById('sidebar');
    const toggle = document.getElementById('sidebarToggle');

    // Creer l'overlay une seule fois
    const overlay = document.createElement('div');
    overlay.id = 'sidebarOverlay';
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);

    function openSidebar() {
        sidebar.classList.add('mobile-open');
        overlay.classList.add('active');
    }
    function closeSidebar() {
        sidebar.classList.remove('mobile-open');
        overlay.classList.remove('active');
    }

    if (toggle) {
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (sidebar.classList.contains('mobile-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    // Fermer la sidebar en cliquant sur l'overlay
    overlay.addEventListener('click', closeSidebar);

    // Fermer la sidebar quand on clique sur un item de nav (mobile)
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', closeSidebar);
    });

    // --- Bottom nav mobile ---
    document.querySelectorAll('.mobile-nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const section = btn.dataset.section;
            const sidebarItem = document.querySelector(`.nav-item[data-section="${section}"]`);
            if (sidebarItem) sidebarItem.click();
            document.querySelectorAll('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            closeSidebar();
        });
    });
}

// ============================================
// API HELPERS — Avec token JWT automatique
// ============================================
async function apiFetch(endpoint, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    // Ajouter le token JWT si disponible
    if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`;
    }
    try {
        const res = await fetch(`${API}${endpoint}`, { ...options, headers });
        if (res.status === 401) {
            // Token expire ou invalide — tenter un refresh
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${accessToken}`;
                const retryRes = await fetch(`${API}${endpoint}`, { ...options, headers });
                if (retryRes.ok) return await retryRes.json();
            }
            // Refresh echoue — deconnecter
            logout();
            return null;
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Erreur ${res.status}`);
        }
        return await res.json();
    } catch (e) {
        console.error(`[API] ${endpoint}:`, e.message);
        return null;
    }
}

// ============================================
// AUTH — Fonctions login, register, refresh, logout
// ============================================

/**
 * Tente de renouveler l'access token via le refresh token (cookie httpOnly)
 */
async function refreshAccessToken() {
    try {
        const res = await fetch(`${API}/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
        });
        if (res.ok) {
            const data = await res.json();
            accessToken = data.access_token;
            localStorage.setItem('access_token', accessToken);
            return true;
        }
    } catch (e) {
        console.warn('[Auth] Echec refresh token:', e.message);
    }
    return false;
}

/**
 * Connexion avec email/mot de passe
 */
async function doLogin() {
    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value;
    const errEl = document.getElementById('authError');
    errEl.style.display = 'none';

    if (!email || !password) {
        errEl.textContent = 'Remplis tous les champs';
        errEl.style.display = 'block';
        return;
    }

    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email, password }),
        });
        const data = await res.json();
        if (!res.ok) {
            errEl.textContent = data.detail || 'Erreur de connexion';
            errEl.style.display = 'block';
            return;
        }
        accessToken = data.access_token;
        localStorage.setItem('access_token', accessToken);
        hideAuthOverlay();
        if (data.user) updateUserInfo(data.user);
        initApp();
    } catch (e) {
        errEl.textContent = 'Erreur reseau — verifie que le serveur est lance';
        errEl.style.display = 'block';
    }
}

/**
 * Inscription avec nom, email, mot de passe
 */
async function doRegister() {
    const name = document.getElementById('authRegName').value.trim();
    const email = document.getElementById('authRegEmail').value.trim();
    const password = document.getElementById('authRegPassword').value;
    const errEl = document.getElementById('authError');
    errEl.style.display = 'none';

    if (!email || !password) {
        errEl.textContent = 'Remplis au moins l\'email et le mot de passe';
        errEl.style.display = 'block';
        return;
    }

    try {
        const res = await fetch(`${API}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name || undefined, email, password }),
        });
        const data = await res.json();
        if (!res.ok) {
            errEl.textContent = data.detail || 'Erreur d\'inscription';
            errEl.style.display = 'block';
            return;
        }
        // Auto-login apres inscription reussie
        document.getElementById('authEmail').value = email;
        document.getElementById('authPassword').value = password;
        showLogin();
        await doLogin();
    } catch (e) {
        errEl.textContent = 'Erreur reseau';
        errEl.style.display = 'block';
    }
}

/**
 * Bascule vers le formulaire d'inscription
 */
function showRegister() {
    document.getElementById('authLoginForm').style.display = 'none';
    document.getElementById('authRegisterForm').style.display = 'block';
    document.getElementById('authError').style.display = 'none';
    document.getElementById('authRegName').focus();
}

/**
 * Bascule vers le formulaire de connexion
 */
function showLogin() {
    document.getElementById('authLoginForm').style.display = 'block';
    document.getElementById('authRegisterForm').style.display = 'none';
    document.getElementById('authError').style.display = 'none';
    document.getElementById('authEmail').focus();
}

/**
 * Cache l'overlay de login et affiche l'app
 */
function hideAuthOverlay() {
    const overlay = document.getElementById('authOverlay');
    if (overlay) overlay.style.display = 'none';
}

/**
 * Affiche l'overlay de login
 */
function showAuthOverlay() {
    const overlay = document.getElementById('authOverlay');
    if (overlay) overlay.style.display = 'flex';
    // Auto-focus sur le champ email
    setTimeout(() => {
        const emailField = document.getElementById('authEmail');
        if (emailField) emailField.focus();
    }, 100);
}

/**
 * Deconnexion — supprime le token et affiche le login
 */
function logout() {
    accessToken = null;
    localStorage.removeItem('access_token');
    fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => {});
    showAuthOverlay();
}

/**
 * Met a jour les infos utilisateur dans la sidebar
 */
function updateUserInfo(user) {
    const el = document.getElementById('userInfo');
    if (el && user) {
        el.innerHTML = `<i class="fa-solid fa-circle-user"></i> <span>${user.name || user.email}</span>
            <button onclick="logout()" title="Deconnexion" style="margin-left:auto;background:none;border:none;color:var(--danger);cursor:pointer;font-size:0.85rem"><i class="fa-solid fa-right-from-bracket"></i></button>`;
    }
}

/**
 * Initialise toute l'application apres login
 */
function initApp() {
    loadDashboard();
    loadDispositionButtons();
    loadFilters();
    initScraperFeed();
    loadAgentPhone();
}

// ============================================
// DASHBOARD
// ============================================
async function loadDashboard() {
    const stats = await apiFetch('/stats/overview');
    const defaultCards = [
        { label: 'Total leads', value: 0, icon: 'fa-database', color: 'var(--accent)' },
        { label: 'Sans site web', value: 0, icon: 'fa-globe', color: 'var(--danger)' },
        { label: 'Appels passes', value: 0, icon: 'fa-phone', color: 'var(--info)' },
        { label: 'RDV pris', value: 0, icon: 'fa-calendar-check', color: 'var(--success)' },
        { label: 'Interesses', value: 0, icon: 'fa-thumbs-up', color: 'var(--warning)' },
        { label: 'Taux conversion', value: '0%', icon: 'fa-chart-line', color: '#a855f7' },
        { label: 'Leads aujourd\'hui', value: 0, icon: 'fa-plus', color: '#14b8a6' },
        { label: 'Appels aujourd\'hui', value: 0, icon: 'fa-headset', color: '#f97316' },
    ];

    if (!stats) {
        document.getElementById('dashboardStats').innerHTML = renderStatCards(defaultCards);
    } else {
        document.getElementById('dashboardStats').innerHTML = renderStatCards([
            { label: 'Total leads', value: stats.total_leads, icon: 'fa-database', color: 'var(--accent)' },
            { label: 'Sans site web', value: stats.leads_sans_site, icon: 'fa-globe', color: 'var(--danger)' },
            { label: 'Appels passes', value: stats.total_calls, icon: 'fa-phone', color: 'var(--info)' },
            { label: 'RDV pris', value: stats.total_meetings, icon: 'fa-calendar-check', color: 'var(--success)' },
            { label: 'Interesses', value: stats.total_interested, icon: 'fa-thumbs-up', color: 'var(--warning)' },
            { label: 'Taux conversion', value: stats.conversion_rate + '%', icon: 'fa-chart-line', color: '#a855f7' },
            { label: 'Leads aujourd\'hui', value: stats.leads_today || 0, icon: 'fa-plus', color: '#14b8a6' },
            { label: 'Appels aujourd\'hui', value: stats.calls_today || 0, icon: 'fa-headset', color: '#f97316' },
        ]);

        // Afficher les top villes et categories si disponibles
        renderDashboardTopLists(stats);
    }

    // Charger charts + listes en parallele
    loadCallsPerDayChart();
    loadStatusBreakdownChart();
    loadRecentCalls();
    loadUpcomingCallbacks();
}

/**
 * Affiche les top villes et categories dans le dashboard
 */
function renderDashboardTopLists(stats) {
    // Top villes dans la carte des appels recents (ajout d'info)
    const recentCard = document.getElementById('recentCallsCard');
    if (recentCard && stats.top_cities && stats.top_cities.length) {
        let topCitiesHtml = '<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08)">';
        topCitiesHtml += '<h4 style="font-size:0.8rem;color:var(--text-muted);margin-bottom:8px"><i class="fa-solid fa-city"></i> Top villes</h4>';
        stats.top_cities.forEach(c => {
            topCitiesHtml += `<span class="badge" style="background:rgba(99,102,241,0.12);color:var(--accent);margin:2px">${c.city} (${c.count})</span>`;
        });
        topCitiesHtml += '</div>';
        // Ajouter apres le contenu existant
        const existingContent = recentCard.querySelector('#recentCallsList');
        if (existingContent) existingContent.insertAdjacentHTML('afterend', topCitiesHtml);
    }

    // Top categories dans la carte callbacks
    const callbackCard = document.getElementById('upcomingCallbacksCard');
    if (callbackCard && stats.top_categories && stats.top_categories.length) {
        let topCatHtml = '<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08)">';
        topCatHtml += '<h4 style="font-size:0.8rem;color:var(--text-muted);margin-bottom:8px"><i class="fa-solid fa-tags"></i> Top categories</h4>';
        stats.top_categories.forEach(c => {
            topCatHtml += `<span class="badge" style="background:rgba(34,197,94,0.12);color:var(--success);margin:2px">${c.category} (${c.count})</span>`;
        });
        topCatHtml += '</div>';
        const existingContent = callbackCard.querySelector('#upcomingCallbacksList');
        if (existingContent) existingContent.insertAdjacentHTML('afterend', topCatHtml);
    }
}

// ============================================
// STAT CARDS HELPER (DRY — utilise partout)
// ============================================
function renderStatCards(cards) {
    return cards.map(c => `
        <div class="stat-card">
            <div class="stat-icon"><i class="fa-solid ${c.icon}" style="color:${c.color}"></i></div>
            <div class="stat-value">${c.value}</div>
            <div class="stat-label">${c.label}</div>
        </div>
    `).join('');
}

// ============================================
// DASHBOARD CHARTS
// ============================================
let callsChartInstance = null;
let statusChartInstance = null;

async function loadCallsPerDayChart() {
    const data = await apiFetch('/stats/calls-per-day?days=30');
    const canvas = document.getElementById('callsChart');
    if (!canvas) return;

    if (callsChartInstance) callsChartInstance.destroy();

    const labels = data && data.length ? data.map(d => {
        const dt = new Date(d.date);
        return dt.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
    }) : ['Aucune donnee'];
    const values = data && data.length ? data.map(d => d.count) : [0];

    callsChartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Appels',
                data: values,
                backgroundColor: 'rgba(99, 102, 241, 0.6)',
                borderColor: '#6366f1',
                borderWidth: 1,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#71717a', maxRotation: 45 },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#71717a', stepSize: 1 },
                },
            },
        },
    });
}

async function loadStatusBreakdownChart() {
    const data = await apiFetch('/stats/status-breakdown?days=30');
    const canvas = document.getElementById('statusChart');
    if (!canvas) return;

    if (statusChartInstance) statusChartInstance.destroy();

    if (!data || !data.length) {
        statusChartInstance = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: ['Aucun appel'],
                datasets: [{ data: [1], backgroundColor: ['#2a2a35'] }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#71717a' } } } },
        });
        return;
    }

    const labels = data.map(d => CALL_STATUSES[d.status]?.label || d.status);
    const values = data.map(d => d.count);
    const colors = data.map(d => CALL_STATUSES[d.status]?.color || '#6b7280');

    statusChartInstance = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderColor: '#1a1a1f',
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#e4e4e7',
                        padding: 12,
                        usePointStyle: true,
                        pointStyleWidth: 10,
                        font: { size: 11 },
                    },
                },
            },
        },
    });
}

// ============================================
// DERNIERS APPELS (Dashboard)
// ============================================
async function loadRecentCalls() {
    const container = document.getElementById('recentCallsList');
    if (!container) return;

    const data = await apiFetch('/calls/recent?limit=10');
    if (!data || !data.length) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">Aucun appel enregistre</p>';
        return;
    }

    container.innerHTML = data.map(call => {
        const st = CALL_STATUSES[call.status] || { label: call.status, color: '#6b7280' };
        const duration = call.duration_seconds ? formatDuration(call.duration_seconds) : '—';
        const date = call.started_at ? formatDate(call.started_at) : '—';
        return `
            <div class="recent-call-item">
                <div class="recent-call-info">
                    <span class="recent-call-name">${call.business_name || 'Lead #' + call.lead_id}</span>
                    <span class="recent-call-meta">${duration} - ${date}</span>
                </div>
                <span class="badge" style="background:${st.color}22;color:${st.color}">${st.label}</span>
            </div>
        `;
    }).join('');
}

// ============================================
// PROCHAINS RAPPELS (Dashboard + Onglet)
// ============================================
async function loadUpcomingCallbacks() {
    const data = await apiFetch('/calls/callbacks');
    const dashList = document.getElementById('upcomingCallbacksList');
    const counter = document.getElementById('callbacksCounter');

    if (counter) counter.textContent = data ? data.length : 0;

    if (dashList) {
        if (!data || !data.length) {
            dashList.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">Aucun rappel planifie</p>';
        } else {
            dashList.innerHTML = renderCallbackItems(data.slice(0, 5), true);
        }
    }
}

async function loadCallbacksPage() {
    const container = document.getElementById('callbacksList');
    if (!container) return;

    const data = await apiFetch('/calls/callbacks');
    if (!data || !data.length) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px">Aucun rappel planifie</p>';
        return;
    }

    container.innerHTML = renderCallbackItems(data, false);
}

function renderCallbackItems(callbacks, compact) {
    return callbacks.map(cb => {
        const cbDate = cb.callback_at ? formatDate(cb.callback_at) : '—';
        const cbTime = cb.callback_at ? formatTime(cb.callback_at) : '';
        return `
            <div class="callback-item">
                <div class="callback-info">
                    <span class="callback-name">${cb.business_name || 'Lead #' + cb.lead_id}</span>
                    <span class="callback-phone">${cb.phone || '—'}</span>
                    <span class="callback-date"><i class="fa-solid fa-clock"></i> ${cbDate} ${cbTime}</span>
                    ${!compact && cb.notes ? `<span class="callback-notes">${cb.notes}</span>` : ''}
                </div>
                <button class="btn btn-sm btn-success" onclick="dialCallback(${cb.lead_id})">
                    <i class="fa-solid fa-phone"></i> Appeler
                </button>
            </div>
        `;
    }).join('');
}

async function dialCallback(leadId) {
    // Switcher vers l'onglet dialer
    document.querySelector('.nav-item[data-section="dialer"]').click();

    // Charger le lead specifique
    const lead = await apiFetch(`/leads/${leadId}`);
    if (lead) {
        currentLead = lead;
        displayCurrentLead(lead);

        // Montrer les controles
        document.getElementById('btnStartSession').style.display = 'none';
        document.getElementById('btnHangup').style.display = '';
        document.getElementById('btnSkip').style.display = '';
        document.getElementById('btnPause').style.display = '';

        // Lancer l'appel
        makeRealCall();
    }
}

// ============================================
// STATS PAGE COMPLETE
// ============================================
async function loadStatsPage() {
    // Stats cards (reutilise renderStatCards)
    const [stats, leadsStats] = await Promise.all([
        apiFetch('/stats/overview'),
        apiFetch('/leads/stats'),
    ]);

    const container = document.getElementById('fullStats');
    if (container) {
        if (!stats) {
            container.innerHTML = renderStatCards([
                { label: 'Total leads', value: 0, icon: 'fa-database', color: 'var(--accent)' },
                { label: 'Appels passes', value: 0, icon: 'fa-phone', color: 'var(--info)' },
                { label: 'RDV pris', value: 0, icon: 'fa-calendar-check', color: 'var(--success)' },
                { label: 'Taux conversion', value: '0%', icon: 'fa-chart-line', color: '#a855f7' },
            ]);
        } else {
            container.innerHTML = renderStatCards([
                { label: 'Total leads', value: stats.total_leads, icon: 'fa-database', color: 'var(--accent)' },
                { label: 'Appels passes', value: stats.total_calls, icon: 'fa-phone', color: 'var(--info)' },
                { label: 'RDV pris', value: stats.total_meetings, icon: 'fa-calendar-check', color: 'var(--success)' },
                { label: 'Taux conversion', value: stats.conversion_rate + '%', icon: 'fa-chart-line', color: '#a855f7' },
                { label: 'Score moyen', value: leadsStats ? leadsStats.avg_score : 0, icon: 'fa-trophy', color: '#f59e0b' },
                { label: 'Avec telephone', value: leadsStats ? leadsStats.with_phone : 0, icon: 'fa-phone-volume', color: '#22c55e' },
            ]);
        }
    }

    // Afficher les repartitions detaillees des leads
    if (leadsStats) renderLeadsStatsDetails(leadsStats);

    // Heatmap
    loadHeatmap();
}

/**
 * Affiche les stats detaillees des leads (villes, categories, tranches de score)
 */
function renderLeadsStatsDetails(leadsStats) {
    const container = document.getElementById('heatmapContainer');
    if (!container) return;

    // Preparer le HTML des details avant la heatmap
    let detailsHtml = '';

    // Par ville
    if (leadsStats.by_city && leadsStats.by_city.length) {
        detailsHtml += '<div style="margin-bottom:20px"><h4 style="color:var(--text-muted);margin-bottom:8px"><i class="fa-solid fa-city"></i> Leads par ville</h4>';
        leadsStats.by_city.forEach(c => {
            const pct = leadsStats.total > 0 ? Math.round(c.count / leadsStats.total * 100) : 0;
            detailsHtml += `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                    <span style="width:120px;font-size:0.85rem">${c.city}</span>
                    <div style="flex:1;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden">
                        <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:4px"></div>
                    </div>
                    <span style="font-size:0.78rem;color:var(--text-muted)">${c.count}</span>
                </div>`;
        });
        detailsHtml += '</div>';
    }

    // Par categorie
    if (leadsStats.by_category && leadsStats.by_category.length) {
        detailsHtml += '<div style="margin-bottom:20px"><h4 style="color:var(--text-muted);margin-bottom:8px"><i class="fa-solid fa-tags"></i> Leads par categorie</h4>';
        leadsStats.by_category.forEach(c => {
            const pct = leadsStats.total > 0 ? Math.round(c.count / leadsStats.total * 100) : 0;
            detailsHtml += `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                    <span style="width:120px;font-size:0.85rem">${c.category}</span>
                    <div style="flex:1;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden">
                        <div style="width:${pct}%;height:100%;background:var(--success);border-radius:4px"></div>
                    </div>
                    <span style="font-size:0.78rem;color:var(--text-muted)">${c.count}</span>
                </div>`;
        });
        detailsHtml += '</div>';
    }

    // Par tranche de score
    if (leadsStats.by_score_range && leadsStats.by_score_range.length) {
        detailsHtml += '<div style="margin-bottom:20px"><h4 style="color:var(--text-muted);margin-bottom:8px"><i class="fa-solid fa-trophy"></i> Leads par score</h4>';
        leadsStats.by_score_range.forEach(s => {
            const pct = leadsStats.total > 0 ? Math.round(s.count / leadsStats.total * 100) : 0;
            detailsHtml += `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                    <span style="width:120px;font-size:0.85rem">${s.range}</span>
                    <div style="flex:1;height:8px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden">
                        <div style="width:${pct}%;height:100%;background:#f59e0b;border-radius:4px"></div>
                    </div>
                    <span style="font-size:0.78rem;color:var(--text-muted)">${s.count}</span>
                </div>`;
        });
        detailsHtml += '</div>';
    }

    // Inserer avant la heatmap
    container.insertAdjacentHTML('beforebegin', `<div id="leadsStatsDetails" class="card" style="margin-bottom:16px">${detailsHtml}</div>`);
}

async function loadHeatmap() {
    const container = document.getElementById('heatmapContainer');
    if (!container) return;

    const data = await apiFetch('/stats/hourly-heatmap?days=30');

    // Construire la matrice 7 jours x 24h
    const DAYS_FR = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
    // Reordonner pour commencer par Lundi (1=Lun -> 0=Dim)
    const DAY_ORDER = [1, 2, 3, 4, 5, 6, 0]; // Lun, Mar, Mer, Jeu, Ven, Sam, Dim

    const matrix = {};
    let maxCount = 1;
    if (data && data.length) {
        data.forEach(d => {
            const key = `${d.day}-${d.hour}`;
            matrix[key] = d.count;
            if (d.count > maxCount) maxCount = d.count;
        });
    }

    // Header avec les heures
    let html = '<div class="heatmap-grid">';
    html += '<div class="heatmap-label"></div>';
    for (let h = 8; h <= 20; h++) {
        html += `<div class="heatmap-hour-label">${String(h).padStart(2, '0')}h</div>`;
    }

    // Lignes par jour
    DAY_ORDER.forEach(dayIdx => {
        html += `<div class="heatmap-day-label">${DAYS_FR[dayIdx]}</div>`;
        for (let h = 8; h <= 20; h++) {
            const count = matrix[`${dayIdx}-${h}`] || 0;
            const intensity = maxCount > 0 ? count / maxCount : 0;
            const bgColor = getHeatmapColor(intensity);
            const tooltip = `${DAYS_FR[dayIdx]} ${h}h : ${count} appel${count > 1 ? 's' : ''} connecte${count > 1 ? 's' : ''}`;
            html += `<div class="heatmap-cell" style="background:${bgColor}" title="${tooltip}">${count > 0 ? count : ''}</div>`;
        }
    });

    html += '</div>';
    container.innerHTML = html;
}

function getHeatmapColor(intensity) {
    if (intensity === 0) return 'rgba(99, 102, 241, 0.05)';
    if (intensity < 0.25) return 'rgba(99, 102, 241, 0.15)';
    if (intensity < 0.5) return 'rgba(99, 102, 241, 0.35)';
    if (intensity < 0.75) return 'rgba(99, 102, 241, 0.55)';
    return 'rgba(99, 102, 241, 0.85)';
}

// ============================================
// POWER DIALER
// ============================================
const CALL_STATUSES = {
    no_answer: { label: 'Pas de reponse', color: '#6b7280' },
    busy: { label: 'Occupe', color: '#6b7280' },
    voicemail: { label: 'Messagerie', color: '#3b82f6' },
    wrong_number: { label: 'Mauvais num.', color: '#ef4444' },
    disconnected: { label: 'Numero HS', color: '#ef4444' },
    gatekeeper: { label: 'Standard', color: '#f97316' },
    interested: { label: 'Interesse', color: '#22c55e' },
    not_interested: { label: 'Pas interesse', color: '#ef4444' },
    callback: { label: 'Rappel', color: '#a855f7' },
    meeting_booked: { label: 'RDV pris', color: '#10b981' },
    follow_up: { label: 'A relancer', color: '#f59e0b' },
    not_qualified: { label: 'Non qualifie', color: '#6b7280' },
    already_customer: { label: 'Deja client', color: '#3b82f6' },
    do_not_call: { label: 'Ne plus appeler', color: '#000' },
    left_company: { label: 'Parti', color: '#6b7280' },
};

let selectedDisposition = null;
let currentLead = null;
let callTimerInterval = null;
let callStartTime = null;

// ============================================
// TWILIO VOICE SDK — Variables globales
// ============================================
let twilioDevice = null;
let currentConnection = null;
let twilioReady = false;       // true si le Device est enregistre
let simulationMode = true;     // fallback si Twilio non configure
let twilioRetryCount = 0;      // compteur retry pour connexion echouee

// ============================================
// CLICK-TO-CALL — Variables globales
// ============================================
let dialMode = localStorage.getItem('dialMode') || 'phone'; // 'phone' (Click-to-Call) ou 'browser' (WebRTC)
let currentCallSid = null;     // SID de l'appel Click-to-Call en cours
let currentConference = null;  // Nom de la conference Click-to-Call en cours

// ============================================
// DIALER — Pre-chargement au switch d'onglet
// ============================================
async function preloadDialerLead() {
    // Pre-charger le prochain lead quand on arrive sur l'onglet dialer
    const data = await apiFetch('/dialer/next');
    if (data && data.id) {
        currentLead = data;
        displayCurrentLead(data);
        updateCallStatus('PRET — Lead charge');
    } else {
        updateCallStatus('AUCUN LEAD DISPONIBLE');
    }
}

// ============================================
// TWILIO — Initialisation du Device
// ============================================
async function initTwilioDevice() {
    try {
        // 1. Recuperer le token JWT depuis le backend
        const tokenData = await apiFetch('/twilio/token', { method: 'POST' });
        if (!tokenData || !tokenData.token) {
            console.warn('[Twilio] Pas de token — mode simulation active');
            enableSimulationMode();
            return false;
        }

        // 2. Creer le Device Twilio Voice SDK v2
        twilioDevice = new Twilio.Device(tokenData.token, {
            // Codec preferentiel pour meilleure qualite
            codecPreferences: ['opus', 'pcmu'],
            // Fermer les connexions proprement
            closeProtection: true,
        });

        // 3. Ecouter les evenements du Device
        twilioDevice.on('registered', () => {
            console.log('[Twilio] Device enregistre — pret a appeler');
            twilioReady = true;
            simulationMode = false;
            hideSimulationBanner();
            updateCallStatus('PRET');
        });

        twilioDevice.on('error', (error) => {
            console.error('[Twilio] Erreur Device:', error.message);
            updateCallStatus('ERREUR TWILIO');
            // Si erreur de permission micro
            if (error.message && error.message.includes('permission')) {
                updateCallStatus('AUTORISEZ LE MICRO');
                alert('Autorisez le micro pour passer des appels');
            }
        });

        twilioDevice.on('incoming', (call) => {
            console.log('[Twilio] Appel entrant — acceptation auto');
            // Accepter automatiquement les appels entrants (mode power dialer)
            call.accept();
            currentConnection = call;
            setupCallEventListeners(call);
        });

        twilioDevice.on('tokenWillExpire', async () => {
            // Renouveler le token avant expiration
            console.log('[Twilio] Renouvellement du token...');
            const refreshData = await apiFetch('/twilio/token', { method: 'POST' });
            if (refreshData && refreshData.token) {
                twilioDevice.updateToken(refreshData.token);
            }
        });

        // 4. Enregistrer le Device pour recevoir des appels entrants
        await twilioDevice.register();
        return true;

    } catch (e) {
        console.error('[Twilio] Echec initialisation:', e.message);
        enableSimulationMode();
        return false;
    }
}

// Configurer les listeners sur une connexion d'appel active
function setupCallEventListeners(call) {
    call.on('accept', () => {
        console.log('[Twilio] Appel connecte');
        startCallTimer();
        updateCallStatus('CONNECTE');
        showMicIndicator(true);
    });

    call.on('disconnect', () => {
        console.log('[Twilio] Appel termine');
        stopCallTimer();
        updateCallStatus('RACCROCHE — Choisir un statut');
        showMicIndicator(false);
        currentConnection = null;
    });

    call.on('cancel', () => {
        console.log('[Twilio] Appel annule');
        stopCallTimer();
        updateCallStatus('ANNULE — Choisir un statut');
        showMicIndicator(false);
        currentConnection = null;
    });

    call.on('error', (error) => {
        console.error('[Twilio] Erreur appel:', error.message);
        stopCallTimer();
        updateCallStatus('ERREUR APPEL');
        showMicIndicator(false);
        currentConnection = null;

        // Retry automatique 1 fois
        if (twilioRetryCount < 1 && currentLead) {
            twilioRetryCount++;
            console.log('[Twilio] Retry automatique...');
            setTimeout(() => makeRealCall(), 2000);
        } else {
            twilioRetryCount = 0;
        }
    });

    call.on('ringing', () => {
        console.log('[Twilio] Ca sonne...');
        updateCallStatus('CA SONNE...');
    });
}

// ============================================
// TWILIO — Passer un vrai appel
// ============================================
async function makeRealCall() {
    if (!currentLead || !currentLead.phone) {
        updateCallStatus('PAS DE NUMERO');
        return;
    }

    // Mode simulation : on simule juste le timer
    if (simulationMode && dialMode === 'browser') {
        console.log('[Simulation] Appel simule vers', currentLead.phone);
        startCallTimer();
        updateCallStatus('APPEL EN COURS (simulation)');
        return;
    }

    // ---- Mode Click-to-Call (telephone) ----
    if (dialMode === 'phone') {
        try {
            updateCallStatus('APPEL VERS VOTRE TELEPHONE...');
            const res = await apiFetch('/twilio/click-to-call', {
                method: 'POST',
                body: JSON.stringify({ lead_id: currentLead.id }),
            });
            if (res) {
                currentCallSid = res.agent_call_sid;
                currentConference = res.conference;
                startCallTimer();
                updateCallStatus('VOTRE TELEPHONE SONNE...');
                console.log('[Click-to-Call] Appel lance', res);
            } else {
                updateCallStatus('ECHEC CLICK-TO-CALL');
            }
        } catch (e) {
            console.error('[Click-to-Call] Erreur:', e.message);
            updateCallStatus('ECHEC CLICK-TO-CALL');
        }
        return;
    }

    // ---- Mode WebRTC (navigateur) ----
    try {
        updateCallStatus('CONNEXION...');
        twilioRetryCount = 0;

        const params = {
            To: currentLead.phone,
            LeadId: String(currentLead.id),
        };

        currentConnection = await twilioDevice.connect({ params });
        setupCallEventListeners(currentConnection);

    } catch (e) {
        console.error('[Twilio] Echec appel:', e.message);
        updateCallStatus('ECHEC APPEL');

        // Retry automatique 1 fois
        if (twilioRetryCount < 1 && currentLead) {
            twilioRetryCount++;
            console.log('[Twilio] Retry automatique...');
            setTimeout(() => makeRealCall(), 2000);
        }
    }
}

// ============================================
// TWILIO — UI helpers
// ============================================
function updateCallStatus(status) {
    const el = document.getElementById('callStatus');
    if (!el) return;
    el.textContent = status;

    // Couleurs selon le statut
    if (status.includes('CONNECTE')) {
        el.style.color = 'var(--success)';
    } else if (status.includes('ERREUR') || status.includes('ECHEC')) {
        el.style.color = 'var(--danger)';
    } else if (status.includes('RACCROCHE') || status.includes('ANNULE')) {
        el.style.color = 'var(--warning)';
    } else if (status.includes('SONNE') || status.includes('CONNEXION')) {
        el.style.color = 'var(--info)';
    } else {
        el.style.color = 'var(--text-muted)';
    }
}

function showMicIndicator(visible) {
    const el = document.getElementById('micIndicator');
    if (el) el.style.display = visible ? '' : 'none';
}

function enableSimulationMode() {
    simulationMode = true;
    twilioReady = false;
    const banner = document.getElementById('simulationBanner');
    if (banner) banner.style.display = '';
    console.warn('[Twilio] Mode simulation active — aucun appel reel ne partira');
}

function hideSimulationBanner() {
    const banner = document.getElementById('simulationBanner');
    if (banner) banner.style.display = 'none';
}

function loadDispositionButtons() {
    const container = document.getElementById('dispositionButtons');
    if (!container) return;
    container.innerHTML = Object.entries(CALL_STATUSES).map(([code, cfg]) => `
        <button class="disposition-btn" data-status="${code}"
            style="border-left:3px solid ${cfg.color}"
            onclick="selectDisposition('${code}')">
            ${cfg.label}
        </button>
    `).join('');
}

function selectDisposition(code) {
    selectedDisposition = code;
    document.querySelectorAll('.disposition-btn').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.status === code);
    });
}

async function startDialerSession() {
    const isMobileDevice = window.innerWidth <= 480;

    document.getElementById('btnStartSession').style.display = 'none';
    document.getElementById('btnHangup').style.display = '';
    document.getElementById('btnSkip').style.display = '';
    document.getElementById('btnPause').style.display = '';

    if (isMobileDevice) {
        // Mode mobile : on utilise le lien tel: natif, pas de Twilio
        simulationMode = false;
        hideSimulationBanner();
        updateCallStatus('MODE MOBILE — PRET');
        // Charger le premier lead (le bouton tel: sera mis a jour automatiquement)
        const lead = await apiFetch('/dialer/next');
        if (lead && lead.id) {
            currentLead = lead;
            displayCurrentLead(lead);
            updateCallStatus('PRET — Appuyez sur APPELER');
        } else {
            updateCallStatus('AUCUN LEAD DISPONIBLE');
        }
        return;
    }

    if (dialMode === 'phone') {
        // Mode Click-to-Call : pas besoin du SDK Twilio dans le navigateur
        updateCallStatus('MODE TELEPHONE — PRET');
        simulationMode = false;
        hideSimulationBanner();
    } else {
        // Mode WebRTC : initialiser le SDK Twilio
        updateCallStatus('INITIALISATION TWILIO...');
        if (!twilioDevice) {
            await initTwilioDevice();
        }
    }

    updateCallStatus('CHARGEMENT...');
    loadNextLead();
}

async function loadNextLead() {
    // Essayer d'abord le endpoint dialer dedie, sinon fallback sur leads
    let lead = null;
    const dialerData = await apiFetch('/dialer/next');
    if (dialerData && dialerData.id) {
        lead = dialerData;
    } else {
        // Fallback : recuperer un lead depuis la liste classique
        const data = await apiFetch('/leads/?per_page=1&has_website=false');
        if (data && data.data && data.data.length) {
            lead = data.data[0];
        }
    }

    if (!lead) {
        updateCallStatus('PLUS DE LEADS');
        return;
    }

    currentLead = lead;
    displayCurrentLead(currentLead);

    // Sur mobile, ne pas auto-lancer l'appel (l'utilisateur tape le lien tel:)
    const isMobileDevice = window.innerWidth <= 480;
    if (isMobileDevice) {
        updateCallStatus('PRET — Appuyez sur APPELER');
        return;
    }

    // Auto-lancer l'appel (reel ou simulation)
    makeRealCall();
}

function displayCurrentLead(lead) {
    document.getElementById('dialerBusinessName').textContent = lead.business_name || '—';
    document.getElementById('dialerCategory').textContent = lead.category || '';
    document.getElementById('dialerPhone').textContent = lead.phone || '—';
    document.getElementById('dialerAddress').textContent = lead.address || '—';
    document.getElementById('dialerCity').textContent = lead.city || '—';
    document.getElementById('dialerRating').textContent = lead.rating || '—';
    document.getElementById('dialerReviews').textContent = lead.review_count || 0;
    document.getElementById('dialerScore').textContent = lead.lead_score || 0;
    const mapsLink = document.getElementById('dialerMapsLink');
    if (lead.maps_url) {
        mapsLink.href = lead.maps_url;
        mapsLink.style.display = '';
    } else {
        mapsLink.style.display = 'none';
    }
    // Mettre a jour le bouton d'appel mobile (lien tel:)
    const mobileCallBtn = document.getElementById('btnMobileCall');
    if (mobileCallBtn && lead.phone) {
        const cleanPhone = lead.phone.replace(/\s/g, '');
        mobileCallBtn.href = `tel:${cleanPhone}`;
        document.getElementById('btnMobileCallNumber').textContent = lead.phone;
    } else if (mobileCallBtn) {
        mobileCallBtn.href = 'tel:';
        document.getElementById('btnMobileCallNumber').textContent = 'Pas de numero';
    }

    // Reset disposition
    selectedDisposition = null;
    document.querySelectorAll('.disposition-btn').forEach(b => b.classList.remove('selected'));
    document.getElementById('callNotes').value = '';
    document.getElementById('callEmail').value = '';
    document.getElementById('callbackDate').value = '';
}

function startCallTimer() {
    callStartTime = Date.now();
    const timerEl = document.getElementById('callTimer');
    if (callTimerInterval) clearInterval(callTimerInterval);
    callTimerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
        const min = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const sec = String(elapsed % 60).padStart(2, '0');
        timerEl.textContent = `${min}:${sec}`;
    }, 1000);
}

function stopCallTimer() {
    if (callTimerInterval) clearInterval(callTimerInterval);
    return callStartTime ? (Date.now() - callStartTime) / 1000 : 0;
}

function hangupCall() {
    const duration = stopCallTimer();
    showMicIndicator(false);

    // Mode Click-to-Call : raccrocher via l'API backend
    if (dialMode === 'phone' && currentCallSid) {
        apiFetch('/twilio/hangup', {
            method: 'POST',
            body: JSON.stringify({ call_sid: currentCallSid }),
        }).catch((e) => console.warn('[Click-to-Call] Erreur raccrochage:', e));
        currentCallSid = null;
        currentConference = null;
        updateCallStatus('RACCROCHE — Choisir un statut');
        return;
    }

    // Mode WebRTC : raccrocher l'appel reel si une connexion existe
    if (currentConnection) {
        try {
            currentConnection.disconnect();
        } catch (e) {
            console.warn('[Twilio] Erreur lors du raccrochage:', e.message);
        }
        currentConnection = null;
    } else if (!simulationMode) {
        // Fallback : demander au backend de raccrocher
        apiFetch('/twilio/hangup', { method: 'POST' }).catch(() => {});
    }

    updateCallStatus('RACCROCHE — Choisir un statut');
}

function skipLead() {
    stopCallTimer();
    showMicIndicator(false);

    // Raccrocher l'appel en cours avant de passer au suivant
    if (dialMode === 'phone' && currentCallSid) {
        apiFetch('/twilio/hangup', {
            method: 'POST',
            body: JSON.stringify({ call_sid: currentCallSid }),
        }).catch(() => {});
        currentCallSid = null;
        currentConference = null;
    } else if (currentConnection) {
        try { currentConnection.disconnect(); } catch (e) {}
        currentConnection = null;
    }

    loadNextLead();
}

function pauseSession() {
    stopCallTimer();
    showMicIndicator(false);

    // Raccrocher l'appel en cours si actif
    if (dialMode === 'phone' && currentCallSid) {
        apiFetch('/twilio/hangup', {
            method: 'POST',
            body: JSON.stringify({ call_sid: currentCallSid }),
        }).catch(() => {});
        currentCallSid = null;
        currentConference = null;
    } else if (currentConnection) {
        try { currentConnection.disconnect(); } catch (e) {}
        currentConnection = null;
    }

    updateCallStatus('SESSION EN PAUSE');
    document.getElementById('btnStartSession').style.display = '';
    document.getElementById('btnStartSession').innerHTML = '<i class="fa-solid fa-play"></i> Reprendre';
    document.getElementById('btnHangup').style.display = 'none';
    document.getElementById('btnSkip').style.display = 'none';
    document.getElementById('btnPause').style.display = 'none';
}

async function submitDisposition() {
    if (!currentLead) return;
    if (!selectedDisposition) {
        alert('Choisissez un statut avant de valider');
        return;
    }

    const duration = stopCallTimer();
    const data = {
        lead_id: currentLead.id,
        status: selectedDisposition,
        duration_seconds: duration,
        notes: document.getElementById('callNotes').value || null,
        contact_email: document.getElementById('callEmail').value || null,
        callback_at: document.getElementById('callbackDate').value || null,
    };

    await apiFetch('/calls/', { method: 'POST', body: JSON.stringify(data) });

    // Nettoyer la connexion en cours
    showMicIndicator(false);
    if (dialMode === 'phone' && currentCallSid) {
        apiFetch('/twilio/hangup', {
            method: 'POST',
            body: JSON.stringify({ call_sid: currentCallSid }),
        }).catch(() => {});
        currentCallSid = null;
        currentConference = null;
    } else if (currentConnection) {
        try { currentConnection.disconnect(); } catch (e) {}
        currentConnection = null;
    }

    // Auto-dial suivant
    updateCallStatus('CHARGEMENT SUIVANT...');
    setTimeout(() => loadNextLead(), 500);
}

// ============================================
// LEADS TABLE — Avec tri avance
// ============================================
let currentSortBy = 'score';
let currentSortOrder = 'desc';
let searchDebounce = null;

/**
 * Debounce sur la recherche texte pour eviter de spammer l'API
 */
function debounceLoadLeads() {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => loadLeads(), 300);
}

async function loadLeads(page = 1) {
    const city = document.getElementById('filterCity')?.value || '';
    const category = document.getElementById('filterCategory')?.value || '';
    const minScore = document.getElementById('filterMinScore')?.value || 0;

    const search = document.getElementById('filterSearch')?.value || '';

    const params = new URLSearchParams({
        page,
        per_page: 50,
        has_website: false,
        sort_by: currentSortBy,
        sort_order: currentSortOrder,
    });
    if (city) params.set('city', city);
    if (category) params.set('category', category);
    if (minScore > 0) params.set('min_score', minScore);
    if (search) params.set('search', search);

    const data = await apiFetch(`/leads/?${params}`);
    if (!data) return;

    const counter = document.getElementById('leadsCounter');
    if (counter) counter.textContent = data.total;

    // Detection mobile pour affichage en cartes
    const isMobile = window.innerWidth <= 480;

    if (isMobile) {
        // Mode cartes pour mobile — chaque lead = une carte tactile
        document.getElementById('leadsTable').innerHTML = data.data.map(l => `
            <div class="card" style="margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:start">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:700;font-size:0.95rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.business_name}</div>
                        <div style="font-size:0.8rem;color:var(--text-muted);margin-top:2px">${l.category || ''} — ${l.city || ''}</div>
                    </div>
                    <span style="background:var(--accent);color:#fff;padding:2px 8px;border-radius:6px;font-size:0.75rem;font-weight:700;flex-shrink:0;margin-left:8px">${l.lead_score}</span>
                </div>
                ${l.phone ? `<a href="tel:${l.phone.replace(/\\s/g, '')}" style="display:flex;align-items:center;gap:6px;margin-top:10px;padding:10px;background:rgba(34,197,94,0.1);border-radius:8px;color:var(--success);font-weight:600;text-decoration:none;font-size:0.95rem;min-height:44px"><i class="fa-solid fa-phone"></i> ${l.phone}</a>` : ''}
                <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
                    ${l.rating ? `<span style="font-size:0.8rem;color:var(--warning)"><i class="fa-solid fa-star"></i> ${l.rating}/5</span>` : ''}
                    ${l.review_count ? `<span style="font-size:0.75rem;color:var(--text-muted)">(${l.review_count} avis)</span>` : ''}
                    ${l.maps_url ? `<a href="${l.maps_url}" target="_blank" style="display:inline-flex;align-items:center;gap:4px;margin-left:auto;font-size:0.8rem;color:var(--accent);text-decoration:none;min-height:44px;padding:0 8px"><i class="fa-solid fa-map"></i> Maps</a>` : ''}
                </div>
            </div>
        `).join('');
    } else {
        // Mode tableau classique pour desktop
        const sortArrow = (col) => {
            if (col === currentSortBy) return currentSortOrder === 'desc' ? ' ↓' : ' ↑';
            return '';
        };

        document.getElementById('leadsTable').innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th onclick="sortLeads('business_name')" style="cursor:pointer">Entreprise${sortArrow('business_name')}</th>
                        <th>Telephone</th>
                        <th onclick="sortLeads('city')" style="cursor:pointer">Ville${sortArrow('city')}</th>
                        <th onclick="sortLeads('category')" style="cursor:pointer">Categorie${sortArrow('category')}</th>
                        <th onclick="sortLeads('rating')" style="cursor:pointer">Note${sortArrow('rating')}</th>
                        <th onclick="sortLeads('review_count')" style="cursor:pointer">Avis${sortArrow('review_count')}</th>
                        <th onclick="sortLeads('score')" style="cursor:pointer">Score${sortArrow('score')}</th>
                        <th onclick="sortLeads('scraped_at')" style="cursor:pointer">Date${sortArrow('scraped_at')}</th>
                        <th>Maps</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.data.map(l => `
                        <tr>
                            <td style="font-weight:600">${l.business_name}</td>
                            <td>${l.phone ? `<a href="tel:${l.phone}" style="color:var(--accent)">${l.phone}</a>` : '—'}</td>
                            <td>${l.city || '—'}</td>
                            <td><span class="badge" style="background:rgba(99,102,241,0.12);color:var(--accent)">${l.category || '—'}</span></td>
                            <td>${l.rating ? l.rating + '/5' : '—'}</td>
                            <td>${l.review_count || 0}</td>
                            <td><strong>${l.lead_score}</strong></td>
                            <td style="font-size:0.78rem;color:var(--text-muted)">${l.scraped_at ? formatDate(l.scraped_at) : '—'}</td>
                            <td>${l.maps_url ? `<a href="${l.maps_url}" target="_blank" class="btn btn-sm btn-outline"><i class="fa-solid fa-map"></i></a>` : '—'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    // Pagination
    renderPagination(data.page, data.pages, data.total);
}

/**
 * Change le tri et recharge les leads
 */
function sortLeads(column) {
    if (currentSortBy === column) {
        // Toggle l'ordre
        currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
    } else {
        currentSortBy = column;
        currentSortOrder = 'desc';
    }
    loadLeads(1);
}

function renderPagination(currentPage, totalPages, total) {
    const container = document.getElementById('leadsPagination');
    if (!container || totalPages <= 1) {
        if (container) container.innerHTML = '';
        return;
    }

    let html = '';
    // Bouton precedent
    if (currentPage > 1) {
        html += `<button class="btn btn-sm btn-outline" onclick="loadLeads(${currentPage - 1})"><i class="fa-solid fa-chevron-left"></i></button>`;
    }

    // Pages
    const start = Math.max(1, currentPage - 2);
    const end = Math.min(totalPages, currentPage + 2);
    for (let p = start; p <= end; p++) {
        const active = p === currentPage ? 'btn-primary' : 'btn-outline';
        html += `<button class="btn btn-sm ${active}" onclick="loadLeads(${p})">${p}</button>`;
    }

    // Bouton suivant
    if (currentPage < totalPages) {
        html += `<button class="btn btn-sm btn-outline" onclick="loadLeads(${currentPage + 1})"><i class="fa-solid fa-chevron-right"></i></button>`;
    }

    html += `<span style="color:var(--text-muted);font-size:0.78rem;margin-left:8px">${total} leads</span>`;
    container.innerHTML = html;
}

// ============================================
// FILTRES DYNAMIQUES
// ============================================
async function loadFilters() {
    const [cities, categories] = await Promise.all([
        apiFetch('/leads/cities'),
        apiFetch('/leads/categories'),
    ]);

    const citySelect = document.getElementById('filterCity');
    if (citySelect) {
        const currentVal = citySelect.value;
        // Garder la premiere option "Toutes les villes" et remplacer le reste
        citySelect.innerHTML = '<option value="">Toutes les villes</option>';
        if (cities && cities.length) {
            cities.forEach(c => {
                if (c.city) {
                    const opt = document.createElement('option');
                    opt.value = c.city;
                    opt.textContent = `${c.city} (${c.count})`;
                    citySelect.appendChild(opt);
                }
            });
        }
        citySelect.value = currentVal;
    }

    const catSelect = document.getElementById('filterCategory');
    if (catSelect) {
        const currentVal = catSelect.value;
        catSelect.innerHTML = '<option value="">Toutes les categories</option>';
        if (categories && categories.length) {
            categories.forEach(c => {
                if (c.category) {
                    const opt = document.createElement('option');
                    opt.value = c.category;
                    opt.textContent = `${c.category} (${c.count})`;
                    catSelect.appendChild(opt);
                }
            });
        }
        catSelect.value = currentVal;
    }
}

// ============================================
// EXPORT CSV
// ============================================
async function exportLeads(format) {
    if (format !== 'csv') return;

    // Recuperer tous les leads (max 10000)
    const params = new URLSearchParams({ page: 1, per_page: 200, has_website: false });
    const city = document.getElementById('filterCity')?.value || '';
    const category = document.getElementById('filterCategory')?.value || '';
    const minScore = document.getElementById('filterMinScore')?.value || 0;
    if (city) params.set('city', city);
    if (category) params.set('category', category);
    if (minScore > 0) params.set('min_score', minScore);

    let allLeads = [];
    let page = 1;
    let totalPages = 1;

    // Pagination automatique (max 50 pages = 10000 leads)
    while (page <= totalPages && page <= 50) {
        params.set('page', page);
        const data = await apiFetch(`/leads/?${params}`);
        if (!data || !data.data || !data.data.length) break;
        allLeads = allLeads.concat(data.data);
        totalPages = data.pages;
        page++;
    }

    if (!allLeads.length) {
        alert('Aucun lead a exporter');
        return;
    }

    // Generer le CSV
    const headers = ['Entreprise', 'Telephone', 'Adresse', 'Ville', 'Categorie', 'Note', 'Score', 'Maps URL'];
    const rows = allLeads.map(l => [
        escapeCsv(l.business_name || ''),
        escapeCsv(l.phone || ''),
        escapeCsv(l.address || ''),
        escapeCsv(l.city || ''),
        escapeCsv(l.category || ''),
        l.rating || '',
        l.lead_score || 0,
        escapeCsv(l.maps_url || ''),
    ]);

    const csvContent = '\uFEFF' + [headers.join(';'), ...rows.map(r => r.join(';'))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `leads_export_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function escapeCsv(str) {
    if (typeof str !== 'string') return str;
    if (str.includes(';') || str.includes('"') || str.includes('\n')) {
        return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
}

// ============================================
// SCRAPER FEED (temps reel via WebSocket)
// ============================================
let scraperWs = null;
let scraperPingInterval = null;
let scraperLeadsFound = 0;
let scraperDuplicates = 0;
let scraperErrors = 0;

function initScraperFeed() {
    const statsContainer = document.getElementById('scraperStats');
    if (statsContainer) {
        statsContainer.innerHTML = renderStatCards([
            { label: 'Leads trouves', value: 0, icon: 'fa-building', color: 'var(--success)' },
            { label: 'Doublons evites', value: 0, icon: 'fa-copy', color: 'var(--warning)' },
            { label: 'Statut', value: 'Arrete', icon: 'fa-spinner', color: 'var(--text-muted)' },
        ]);
    }
}

/**
 * Ouvre une connexion WebSocket vers le backend pour recevoir les leads en temps reel.
 */
function connectScraperWebSocket() {
    // Determiner le protocole ws/wss selon la page
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/api/ws/scraper`;

    try {
        scraperWs = new WebSocket(wsUrl);
    } catch (e) {
        console.error('[WS] Erreur creation WebSocket :', e);
        return;
    }

    scraperWs.onopen = () => {
        console.log('[WS] Connexion scraper etablie');
        // Heartbeat ping toutes les 30s pour eviter le timeout nginx
        if (scraperPingInterval) clearInterval(scraperPingInterval);
        scraperPingInterval = setInterval(() => {
            if (scraperWs && scraperWs.readyState === WebSocket.OPEN) {
                scraperWs.send('ping');
            }
        }, 30000);
    };

    scraperWs.onmessage = (event) => {
        // Ignorer les pong texte
        if (event.data === 'pong') return;

        try {
            const msg = JSON.parse(event.data);

            if (msg.type === 'new_lead' && msg.data) {
                // Nouveau lead insere — l'ajouter au feed
                scraperLeadsFound++;
                addScraperFeedItem(
                    msg.data.business_name || 'Inconnu',
                    msg.data.city || '',
                    msg.data.phone || '',
                    false
                );
                updateScraperStats('En cours...');
            }

            // Support du batch de leads
            if (msg.type === 'new_leads_batch' && msg.data) {
                msg.data.forEach(lead => {
                    scraperLeadsFound++;
                    addScraperFeedItem(
                        lead.business_name || 'Inconnu',
                        lead.city || '',
                        lead.phone || '',
                        false
                    );
                });
                updateScraperStats('En cours...');
            }

            if (msg.type === 'stats' && msg.data) {
                // Mise a jour des stats depuis le backend
                scraperLeadsFound = msg.data.inserted || 0;
                scraperDuplicates = msg.data.duplicates || 0;
                scraperErrors = msg.data.errors || 0;
                updateScraperStats('En cours...');
            }
        } catch (e) {
            console.warn('[WS] Message non JSON recu :', event.data);
        }
    };

    scraperWs.onclose = () => {
        console.log('[WS] Connexion scraper fermee');
        if (scraperPingInterval) {
            clearInterval(scraperPingInterval);
            scraperPingInterval = null;
        }
    };

    scraperWs.onerror = (err) => {
        console.error('[WS] Erreur WebSocket scraper :', err);
    };
}

/**
 * Ferme proprement la connexion WebSocket du scraper.
 */
function disconnectScraperWebSocket() {
    if (scraperPingInterval) {
        clearInterval(scraperPingInterval);
        scraperPingInterval = null;
    }
    if (scraperWs) {
        try { scraperWs.close(); } catch (e) { /* ignore */ }
        scraperWs = null;
    }
}

async function startScraper() {
    const city = document.getElementById('scraperCity').value || 'Toulouse';
    const category = document.getElementById('scraperCategory').value || 'restaurant';

    document.getElementById('scraperStatus').className = 'scraper-status online';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper actif';

    scraperLeadsFound = 0;
    scraperDuplicates = 0;
    scraperErrors = 0;
    const feed = document.getElementById('scraperFeed');
    if (feed) feed.innerHTML = '';

    updateScraperStats('Demarrage...');

    // Ouvrir la connexion WebSocket pour le feed temps reel
    connectScraperWebSocket();

    // Lancer le scrape cote backend
    const result = await apiFetch('/scraper/start', {
        method: 'POST',
        body: JSON.stringify({ query: category, city: city, limit: 100 }),
    });

    if (!result) {
        updateScraperStats('Erreur demarrage');
        disconnectScraperWebSocket();
        document.getElementById('scraperStatus').className = 'scraper-status offline';
        document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Erreur';
    }
}

async function stopScraper() {
    // Arreter le scrape cote backend
    await apiFetch('/scraper/stop', { method: 'POST' });

    // Fermer le WebSocket
    disconnectScraperWebSocket();

    document.getElementById('scraperStatus').className = 'scraper-status offline';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper arrete';
    updateScraperStats('Arrete');

    // Rafraichir l'historique des jobs
    loadScraperHistory();
}

function updateScraperStats(statusText) {
    const container = document.getElementById('scraperStats');
    if (container) {
        const isActive = scraperWs && scraperWs.readyState === WebSocket.OPEN;
        container.innerHTML = renderStatCards([
            { label: 'Leads inseres', value: scraperLeadsFound, icon: 'fa-building', color: 'var(--success)' },
            { label: 'Doublons evites', value: scraperDuplicates, icon: 'fa-copy', color: 'var(--warning)' },
            { label: 'Statut', value: statusText, icon: 'fa-spinner', color: isActive ? 'var(--success)' : 'var(--text-muted)' },
        ]);
    }
}

function addScraperFeedItem(name, city, phone, isDuplicate) {
    const feed = document.getElementById('scraperFeed');
    if (!feed) return;

    const item = document.createElement('div');
    item.className = 'scraper-item';
    // Animation d'apparition
    item.style.opacity = '0';
    item.style.transform = 'translateY(-10px)';
    item.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    item.innerHTML = `
        <i class="fa-solid ${isDuplicate ? 'fa-copy' : 'fa-building'}" style="color:${isDuplicate ? 'var(--warning)' : 'var(--success)'}; width:20px; text-align:center"></i>
        <div style="flex:1">
            <span style="font-weight:600;font-size:0.88rem">${name}</span>
            <span style="color:var(--text-muted);font-size:0.78rem;margin-left:8px">${city}${phone ? ' - ' + phone : ''}</span>
        </div>
        <span class="badge" style="background:${isDuplicate ? 'rgba(245,158,11,0.15);color:var(--warning)' : 'rgba(34,197,94,0.15);color:var(--success)'}">
            ${isDuplicate ? 'Doublon' : 'Nouveau'}
        </span>
    `;

    // Inserer en haut avec animation
    feed.insertBefore(item, feed.firstChild);
    requestAnimationFrame(() => {
        item.style.opacity = '1';
        item.style.transform = 'translateY(0)';
    });

    // Limiter a 50 items
    while (feed.children.length > 50) {
        feed.removeChild(feed.lastChild);
    }
}

// ============================================
// SCRAPER — Historique des ScrapeJobs
// ============================================
async function loadScraperHistory() {
    const container = document.getElementById('scraperHistory');
    if (!container) return;

    const data = await apiFetch('/scraper/history?limit=20');
    if (!data || !data.data || !data.data.length) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">Aucun scrape effectue</p>';
        return;
    }

    const statusColors = {
        completed: 'var(--success)',
        running: 'var(--info)',
        failed: 'var(--danger)',
        pending: 'var(--text-muted)',
    };
    const statusLabels = {
        completed: 'Termine',
        running: 'En cours',
        failed: 'Echoue',
        pending: 'En attente',
    };

    container.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Query</th>
                    <th>Ville</th>
                    <th>Statut</th>
                    <th>Trouves</th>
                    <th>Inseres</th>
                    <th>Doublons</th>
                    <th>Offset</th>
                    <th>Date</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                ${data.data.map(j => `
                    <tr>
                        <td style="font-weight:600">${j.query}</td>
                        <td>${j.city}</td>
                        <td>
                            <span class="badge" style="background:${statusColors[j.status] || '#6b7280'}22;color:${statusColors[j.status] || '#6b7280'}">
                                ${statusLabels[j.status] || j.status}
                            </span>
                        </td>
                        <td>${j.total_found || 0}</td>
                        <td style="color:var(--success)">${j.total_inserted || 0}</td>
                        <td style="color:var(--warning)">${j.total_duplicates || 0}</td>
                        <td style="color:var(--text-muted)">${j.last_offset || 0}</td>
                        <td style="font-size:0.78rem;color:var(--text-muted)">${j.created_at ? formatDate(j.created_at) : '—'}</td>
                        <td>
                            <button class="btn btn-sm btn-outline" onclick="rerunScrapeJob('${j.query}', '${j.city}')">
                                <i class="fa-solid fa-rotate-right"></i>
                            </button>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

/**
 * Relancer un scrape depuis l'historique (reprend avec l'offset memoire)
 */
function rerunScrapeJob(query, city) {
    document.getElementById('scraperCategory').value = query;
    document.getElementById('scraperCity').value = city;
    startScraper();
}

// ============================================
// SCRAPER — Suggestions de queries
// ============================================
async function loadScraperSuggestions() {
    const container = document.getElementById('scraperSuggestions');
    if (!container) return;

    const city = document.getElementById('scraperCity')?.value || 'Toulouse';
    const data = await apiFetch(`/scraper/suggestions?city=${encodeURIComponent(city)}`);
    if (!data || !data.data || !data.data.length) {
        container.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">Aucune suggestion disponible</p>';
        return;
    }

    container.innerHTML = data.data.slice(0, 10).map(s => `
        <button class="btn btn-sm btn-outline" style="margin:3px" onclick="applySuggestion('${s.query}', '${s.city}')">
            ${s.query} <span style="font-size:0.7rem;color:var(--text-muted)">${s.city}</span>
        </button>
    `).join('');
}

/**
 * Applique une suggestion dans les champs du scraper
 */
function applySuggestion(query, city) {
    document.getElementById('scraperCategory').value = query;
    document.getElementById('scraperCity').value = city;
}

// ============================================
// SETTINGS
// ============================================
function saveSettings() {
    // Les cles API sont sensibles — on les affiche dans l'UI mais on les envoie au backend
    // Pour l'instant on les garde en localStorage (TODO: endpoint backend)
    const settings = {
        twilio_sid: document.getElementById('settingTwilioSid')?.value || '',
        twilio_token: document.getElementById('settingTwilioToken')?.value || '',
        twilio_phone: document.getElementById('settingTwilioPhone')?.value || '',
        outscraper_key: document.getElementById('settingOutscraperKey')?.value || '',
        foursquare_key: document.getElementById('settingFoursquareKey')?.value || '',
    };
    localStorage.setItem('coldcall_settings', JSON.stringify(settings));

    // Feedback visuel au lieu d'un alert()
    const btn = event.target.closest('.btn');
    if (btn) {
        const old = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Enregistre !';
        btn.style.background = 'var(--success)';
        setTimeout(() => { btn.innerHTML = old; btn.style.background = ''; }, 2000);
    }
}

// ============================================
// CLICK-TO-CALL — Sauvegarde numero agent
// ============================================
async function saveAgentPhone() {
    const phone = document.getElementById('settingAgentPhone')?.value;
    if (!phone) {
        alert('Entrez un numero de telephone');
        return;
    }
    const res = await apiFetch('/auth/me/phone', {
        method: 'PATCH',
        body: JSON.stringify({ phone_number: phone }),
    });
    if (res) {
        alert('Numero de telephone enregistre');
    }
}

async function loadAgentPhone() {
    const me = await apiFetch('/auth/me');
    if (me && me.phone_number) {
        const el = document.getElementById('settingAgentPhone');
        if (el) el.value = me.phone_number;
    }
    // Restaurer le mode d'appel depuis le localStorage
    const savedMode = localStorage.getItem('dialMode');
    if (savedMode) {
        dialMode = savedMode;
        const selectEl = document.getElementById('settingDialMode');
        if (selectEl) selectEl.value = savedMode;
    }
}

// ============================================
// PROFIL
// ============================================
async function loadProfil() {
    const me = await apiFetch('/auth/me');
    if (!me) return;

    // Remplir les champs
    document.getElementById('profilName').value = me.name || '';
    document.getElementById('profilEmail').value = me.email || '';
    document.getElementById('profilPhone').value = me.phone_number || '';

    // Mode d'appel depuis localStorage
    const mode = localStorage.getItem('dialMode') || 'phone';
    document.getElementById('profilDialMode').value = mode;

    // Stats personnelles
    const stats = await apiFetch('/stats/overview');
    if (stats) {
        document.getElementById('profilStats').innerHTML = renderStatCards([
            { label: 'Appels passes', value: stats.total_calls, icon: 'fa-phone', color: 'var(--accent)' },
            { label: 'RDV pris', value: stats.total_meetings, icon: 'fa-calendar-check', color: 'var(--success)' },
            { label: 'Taux conversion', value: stats.conversion_rate + '%', icon: 'fa-chart-line', color: '#a855f7' },
            { label: 'Appels aujourd\'hui', value: stats.calls_today || 0, icon: 'fa-clock', color: 'var(--warning)' },
        ]);
    }

    // Activite recente
    const recent = await apiFetch('/calls/recent?limit=5');
    if (recent && recent.length) {
        document.getElementById('profilRecentActivity').innerHTML = recent.map(c => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
                <div>
                    <div style="font-weight:600;font-size:0.88rem">${c.business_name || 'Inconnu'}</div>
                    <div style="font-size:0.75rem;color:var(--text-muted)">${c.started_at ? new Date(c.started_at).toLocaleString('fr-FR') : ''}</div>
                </div>
                <span style="padding:2px 8px;border-radius:6px;font-size:0.72rem;font-weight:600;background:${(CALL_STATUSES[c.status]||{}).color || '#6b7280'}22;color:${(CALL_STATUSES[c.status]||{}).color || '#6b7280'}">${(CALL_STATUSES[c.status]||{}).label || c.status}</span>
            </div>
        `).join('');
    } else {
        document.getElementById('profilRecentActivity').innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">Aucune activite recente</p>';
    }
}

async function saveProfile() {
    const name = document.getElementById('profilName').value;
    const phone = document.getElementById('profilPhone').value;
    const mode = document.getElementById('profilDialMode').value;

    // Sauvegarder le telephone
    await apiFetch('/auth/me/phone', {
        method: 'PATCH',
        body: JSON.stringify({ phone_number: phone })
    });

    // Sauvegarder le mode d'appel
    dialMode = mode;
    localStorage.setItem('dialMode', mode);

    // Feedback visuel (pas d'alert())
    const status = document.getElementById('profilSaveStatus');
    if (status) {
        status.style.display = 'inline';
        setTimeout(() => status.style.display = 'none', 2500);
    }
}

async function changePassword() {
    const newPw = document.getElementById('profilNewPassword').value;
    const confirm = document.getElementById('profilConfirmPassword').value;

    if (!newPw || newPw.length < 6) {
        alert('Le mot de passe doit faire au moins 6 caracteres');
        return;
    }
    if (newPw !== confirm) {
        alert('Les mots de passe ne correspondent pas');
        return;
    }

    // TODO: implementer l'endpoint PATCH /auth/me/password dans le backend
    alert('Fonctionnalite bientot disponible');
}

// ============================================
// UTILS
// ============================================
function formatDuration(seconds) {
    if (!seconds || seconds < 1) return '< 1s';
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    if (min === 0) return `${sec}s`;
    return `${min}m ${sec}s`;
}

function formatDate(isoStr) {
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
    } catch {
        return isoStr;
    }
}

function formatTime(isoStr) {
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch {
        return '';
    }
}

// ============================================
// TESTS FONCTIONNELS
// ============================================
async function runAllTests() {
    const btn = document.getElementById('btnRunTests');
    const summaryEl = document.getElementById('testsSummary');
    const resultsEl = document.getElementById('testsResults');

    // Loading state
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Tests en cours...';
    summaryEl.innerHTML = '<div class="skeleton" style="height:80px;width:100%"></div>';
    resultsEl.innerHTML = '';

    const data = await apiFetch('/tests/run');

    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-play"></i> Relancer les tests';

    if (!data) {
        summaryEl.innerHTML = '<div class="card" style="border-left:3px solid var(--danger)"><p style="color:var(--danger)"><i class="fa-solid fa-xmark"></i> Impossible de lancer les tests (erreur API)</p></div>';
        return;
    }

    const s = data.summary;
    const allPassed = s.failed === 0;

    // Resume
    summaryEl.innerHTML = `
        <div class="stats-grid">
            ${renderStatCards([
                { label: 'Total tests', value: s.total, icon: 'fa-flask-vial', color: 'var(--accent)' },
                { label: 'Reussis', value: s.passed, icon: 'fa-circle-check', color: 'var(--success)' },
                { label: 'Echoues', value: s.failed, icon: 'fa-circle-xmark', color: 'var(--danger)' },
                { label: 'Taux', value: s.success_rate, icon: 'fa-percentage', color: allPassed ? 'var(--success)' : 'var(--warning)' },
                { label: 'Duree', value: s.duration_ms + 'ms', icon: 'fa-stopwatch', color: 'var(--info)' },
            ])}
        </div>
        <div class="card" style="border-left:3px solid ${allPassed ? 'var(--success)' : 'var(--danger)'}; margin-top:12px">
            <p style="font-size:0.95rem;font-weight:600;color:${allPassed ? 'var(--success)' : 'var(--danger)'}">
                ${allPassed
                    ? '<i class="fa-solid fa-circle-check"></i> Tous les tests sont passes — la plateforme est fonctionnelle'
                    : `<i class="fa-solid fa-triangle-exclamation"></i> ${s.failed} test(s) en echec — voir les details ci-dessous`
                }
            </p>
            <p style="font-size:0.78rem;color:var(--text-muted);margin-top:4px">
                Execute le ${new Date(s.timestamp).toLocaleString('fr-FR')}
            </p>
        </div>
    `;

    // Details par test
    resultsEl.innerHTML = `
        <div class="card">
            <h3><i class="fa-solid fa-list-check"></i> Detail des tests</h3>
            <table style="width:100%;border-collapse:collapse">
                <thead>
                    <tr style="border-bottom:2px solid var(--border)">
                        <th style="padding:8px;text-align:left;color:var(--text-muted);font-size:0.78rem">Statut</th>
                        <th style="padding:8px;text-align:left;color:var(--text-muted);font-size:0.78rem">Test</th>
                        <th style="padding:8px;text-align:left;color:var(--text-muted);font-size:0.78rem">Description</th>
                        <th style="padding:8px;text-align:left;color:var(--text-muted);font-size:0.78rem">Detail</th>
                        <th style="padding:8px;text-align:right;color:var(--text-muted);font-size:0.78rem">Duree</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.tests.map(t => {
                        const isPassed = t.status === 'PASS';
                        const icon = isPassed ? 'fa-circle-check' : 'fa-circle-xmark';
                        const color = isPassed ? 'var(--success)' : 'var(--danger)';
                        const bg = isPassed ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)';
                        return `
                            <tr style="border-bottom:1px solid var(--border);background:${bg}">
                                <td style="padding:8px"><i class="fa-solid ${icon}" style="color:${color};font-size:1.1rem"></i></td>
                                <td style="padding:8px;font-weight:600;font-size:0.85rem;font-family:monospace">${t.name}</td>
                                <td style="padding:8px;font-size:0.85rem;color:var(--text-muted)">${t.description}</td>
                                <td style="padding:8px;font-size:0.8rem;color:${isPassed ? 'var(--text-muted)' : 'var(--danger)'}; max-width:300px;word-break:break-all">${t.detail}</td>
                                <td style="padding:8px;text-align:right;font-size:0.78rem;color:var(--text-muted)">${t.duration_ms}ms</td>
                            </tr>`;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;

    // Log en console pour debug
    console.group('%c[TESTS] Resultats', 'color:#6366f1;font-weight:bold');
    console.log(`%c${s.passed}/${s.total} passes (${s.success_rate}) en ${s.duration_ms}ms`, allPassed ? 'color:green' : 'color:red');
    data.tests.forEach(t => {
        const style = t.status === 'PASS' ? 'color:green' : 'color:red;font-weight:bold';
        console.log(`%c${t.status === 'PASS' ? '✓' : '✗'} ${t.name}%c — ${t.detail}`, style, 'color:gray');
    });
    console.groupEnd();
}
