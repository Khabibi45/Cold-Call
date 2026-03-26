/* ============================================
   Cold Call Platform — Application principale
   Navigation, API calls, Power Dialer, Charts
   ============================================ */

const API = '/api';

// ============================================
// NAVIGATION
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadDashboard();
    loadDispositionButtons();
    loadFilters();
    initScraperFeed();
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

            // Charger les donnees specifiques a la section
            if (section === 'leads') loadLeads();
            if (section === 'callbacks') loadCallbacksPage();
            if (section === 'stats') loadStatsPage();
        });
    });

    const toggle = document.getElementById('sidebarToggle');
    if (toggle) toggle.addEventListener('click', () => document.getElementById('sidebar').classList.toggle('mobile-open'));
}

// ============================================
// API HELPERS
// ============================================
async function apiFetch(endpoint, options = {}) {
    try {
        const res = await fetch(`${API}${endpoint}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
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
        ]);
    }

    // Charger charts + listes en parallele
    loadCallsPerDayChart();
    loadStatusBreakdownChart();
    loadRecentCalls();
    loadUpcomingCallbacks();
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

function dialCallback(leadId) {
    // Basculer vers le dialer
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector('[data-section="dialer"]').classList.add('active');
    document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
    document.getElementById('section-dialer').classList.add('active');
    document.getElementById('pageTitle').textContent = 'Power Dialer';
    // Charger ce lead specifiquement
    loadSpecificLead(leadId);
}

async function loadSpecificLead(leadId) {
    const data = await apiFetch(`/leads/?page=1&per_page=1`);
    // Idealement il faudrait un endpoint GET /leads/:id — on simule
    // Pour l'instant on lance la session normalement
    startDialerSession();
}

// ============================================
// STATS PAGE COMPLETE
// ============================================
async function loadStatsPage() {
    // Stats cards (reutilise renderStatCards)
    const stats = await apiFetch('/stats/overview');
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
            ]);
        }
    }

    // Heatmap
    loadHeatmap();
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

function startDialerSession() {
    document.getElementById('btnStartSession').style.display = 'none';
    document.getElementById('btnHangup').style.display = '';
    document.getElementById('btnSkip').style.display = '';
    document.getElementById('btnPause').style.display = '';
    document.getElementById('callStatus').textContent = 'CHARGEMENT...';
    loadNextLead();
}

async function loadNextLead() {
    const data = await apiFetch('/leads/?per_page=1&has_website=false');
    if (!data || !data.data || !data.data.length) {
        document.getElementById('callStatus').textContent = 'PLUS DE LEADS';
        return;
    }
    currentLead = data.data[0];
    displayCurrentLead(currentLead);
    startCallTimer();
    document.getElementById('callStatus').textContent = 'APPEL EN COURS...';
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
    if (lead.maps_url) {
        document.getElementById('dialerMapsLink').href = lead.maps_url;
        document.getElementById('dialerMapsLink').style.display = '';
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
    document.getElementById('callStatus').textContent = 'RACCROCHE — Choisir un statut';
}

function skipLead() {
    stopCallTimer();
    loadNextLead();
}

function pauseSession() {
    stopCallTimer();
    document.getElementById('callStatus').textContent = 'SESSION EN PAUSE';
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

    // Auto-dial suivant
    document.getElementById('callStatus').textContent = 'CHARGEMENT SUIVANT...';
    setTimeout(() => loadNextLead(), 500);
}

// ============================================
// LEADS TABLE
// ============================================
async function loadLeads(page = 1) {
    const city = document.getElementById('filterCity')?.value || '';
    const category = document.getElementById('filterCategory')?.value || '';
    const minScore = document.getElementById('filterMinScore')?.value || 0;

    const params = new URLSearchParams({ page, per_page: 50, has_website: false });
    if (city) params.set('city', city);
    if (category) params.set('category', category);
    if (minScore > 0) params.set('min_score', minScore);

    const data = await apiFetch(`/leads/?${params}`);
    if (!data) return;

    const counter = document.getElementById('leadsCounter');
    if (counter) counter.textContent = data.total;

    document.getElementById('leadsTable').innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Entreprise</th>
                    <th>Telephone</th>
                    <th>Ville</th>
                    <th>Categorie</th>
                    <th>Note</th>
                    <th>Avis</th>
                    <th>Score</th>
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
                        <td>${l.maps_url ? `<a href="${l.maps_url}" target="_blank" class="btn btn-sm btn-outline"><i class="fa-solid fa-map"></i></a>` : '—'}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;

    // Pagination
    renderPagination(data.page, data.pages, data.total);
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
    if (citySelect && cities && cities.length) {
        cities.forEach(c => {
            if (c.city) {
                const opt = document.createElement('option');
                opt.value = c.city;
                opt.textContent = `${c.city} (${c.count})`;
                citySelect.appendChild(opt);
            }
        });
    }

    const catSelect = document.getElementById('filterCategory');
    if (catSelect && categories && categories.length) {
        categories.forEach(c => {
            if (c.category) {
                const opt = document.createElement('option');
                opt.value = c.category;
                opt.textContent = `${c.category} (${c.count})`;
                catSelect.appendChild(opt);
            }
        });
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
// SCRAPER FEED (simule temps reel)
// ============================================
let scraperInterval = null;
const SCRAPER_MOCK_BUSINESSES = [
    'Boulangerie du Capitole', 'Pizzeria Bella Vita', 'Salon Coiffure Elegance',
    'Garage Auto Plus', 'Plombier Express', 'Restaurant Le Petit Bistrot',
    'Electricien Toulouse', 'Kebab Istanbul', 'Cabinet Comptable Dupont',
    'Fleuriste Rose & Lys', 'Pressing Rapide', 'Boucherie Tradition',
    'Pharmacie Centrale', 'Cordonnerie Martin', 'Taxi Toulouse Sud',
];

function initScraperFeed() {
    const statsContainer = document.getElementById('scraperStats');
    if (statsContainer) {
        statsContainer.innerHTML = renderStatCards([
            { label: 'Leads trouves', value: 0, icon: 'fa-building', color: 'var(--success)' },
            { label: 'Doublons evites', value: 0, icon: 'fa-copy', color: 'var(--warning)' },
            { label: 'En cours', value: 'Arrete', icon: 'fa-spinner', color: 'var(--text-muted)' },
        ]);
    }
}

let scraperLeadsFound = 0;
let scraperDuplicates = 0;

function startScraper() {
    const city = document.getElementById('scraperCity').value || 'Toulouse';
    const category = document.getElementById('scraperCategory').value || 'restaurant';

    document.getElementById('scraperStatus').className = 'scraper-status online';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper actif';

    scraperLeadsFound = 0;
    scraperDuplicates = 0;
    const feed = document.getElementById('scraperFeed');
    if (feed) feed.innerHTML = '';

    updateScraperStats('En cours...');

    // Simuler l'arrivee de leads toutes les 1-3 secondes
    if (scraperInterval) clearInterval(scraperInterval);
    scraperInterval = setInterval(() => {
        const isDuplicate = Math.random() < 0.2;
        const bizName = SCRAPER_MOCK_BUSINESSES[Math.floor(Math.random() * SCRAPER_MOCK_BUSINESSES.length)];
        const phone = '05 ' + String(Math.floor(10000000 + Math.random() * 90000000)).replace(/(\d{2})(\d{2})(\d{2})(\d{2})/, '$1 $2 $3 $4');

        if (isDuplicate) {
            scraperDuplicates++;
            addScraperFeedItem(bizName, city, phone, true);
        } else {
            scraperLeadsFound++;
            addScraperFeedItem(bizName, city, phone, false);
        }

        updateScraperStats('En cours...');
    }, 1500 + Math.random() * 2000);
}

function stopScraper() {
    if (scraperInterval) {
        clearInterval(scraperInterval);
        scraperInterval = null;
    }
    document.getElementById('scraperStatus').className = 'scraper-status offline';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper arrete';
    updateScraperStats('Arrete');
}

function updateScraperStats(statusText) {
    const container = document.getElementById('scraperStats');
    if (container) {
        container.innerHTML = renderStatCards([
            { label: 'Leads trouves', value: scraperLeadsFound, icon: 'fa-building', color: 'var(--success)' },
            { label: 'Doublons evites', value: scraperDuplicates, icon: 'fa-copy', color: 'var(--warning)' },
            { label: 'Statut', value: statusText, icon: 'fa-spinner', color: scraperInterval ? 'var(--success)' : 'var(--text-muted)' },
        ]);
    }
}

function addScraperFeedItem(name, city, phone, isDuplicate) {
    const feed = document.getElementById('scraperFeed');
    if (!feed) return;

    const item = document.createElement('div');
    item.className = 'scraper-item';
    item.innerHTML = `
        <i class="fa-solid ${isDuplicate ? 'fa-copy' : 'fa-building'}" style="color:${isDuplicate ? 'var(--warning)' : 'var(--success)'}; width:20px; text-align:center"></i>
        <div style="flex:1">
            <span style="font-weight:600;font-size:0.88rem">${name}</span>
            <span style="color:var(--text-muted);font-size:0.78rem;margin-left:8px">${city} - ${phone}</span>
        </div>
        <span class="badge" style="background:${isDuplicate ? 'rgba(245,158,11,0.15);color:var(--warning)' : 'rgba(34,197,94,0.15);color:var(--success)'}">
            ${isDuplicate ? 'Doublon' : 'Nouveau'}
        </span>
    `;

    // Inserer en haut
    feed.insertBefore(item, feed.firstChild);

    // Limiter a 50 items
    while (feed.children.length > 50) {
        feed.removeChild(feed.lastChild);
    }
}

// ============================================
// SCRAPER CONTROLS
// ============================================
// startScraper et stopScraper sont deja definis plus haut

// ============================================
// SETTINGS
// ============================================
function saveSettings() {
    const settings = {
        twilio_sid: document.getElementById('settingTwilioSid')?.value,
        twilio_token: document.getElementById('settingTwilioToken')?.value,
        twilio_phone: document.getElementById('settingTwilioPhone')?.value,
        outscraper_key: document.getElementById('settingOutscraperKey')?.value,
        foursquare_key: document.getElementById('settingFoursquareKey')?.value,
    };
    localStorage.setItem('coldcall_settings', JSON.stringify(settings));
    alert('Parametres enregistres');
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
