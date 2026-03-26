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
    loadAgentPhone();
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
    document.getElementById('btnStartSession').style.display = 'none';
    document.getElementById('btnHangup').style.display = '';
    document.getElementById('btnSkip').style.display = '';
    document.getElementById('btnPause').style.display = '';

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
// SCRAPER CONTROLS
// ============================================
// startScraper et stopScraper sont definis dans la section SCRAPER FEED ci-dessus

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
