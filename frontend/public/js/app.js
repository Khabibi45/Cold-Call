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
    if (!stats) {
        document.getElementById('dashboardStats').innerHTML = renderStatCards([
            { label: 'Total leads', value: 0, icon: 'fa-database', color: 'var(--accent)' },
            { label: 'Sans site web', value: 0, icon: 'fa-globe', color: 'var(--danger)' },
            { label: 'Appels passes', value: 0, icon: 'fa-phone', color: 'var(--info)' },
            { label: 'RDV pris', value: 0, icon: 'fa-calendar-check', color: 'var(--success)' },
            { label: 'Interesses', value: 0, icon: 'fa-thumbs-up', color: 'var(--warning)' },
            { label: 'Taux conversion', value: '0%', icon: 'fa-chart-line', color: '#a855f7' },
        ]);
        return;
    }
    document.getElementById('dashboardStats').innerHTML = renderStatCards([
        { label: 'Total leads', value: stats.total_leads, icon: 'fa-database', color: 'var(--accent)' },
        { label: 'Sans site web', value: stats.leads_sans_site, icon: 'fa-globe', color: 'var(--danger)' },
        { label: 'Appels passes', value: stats.total_calls, icon: 'fa-phone', color: 'var(--info)' },
        { label: 'RDV pris', value: stats.total_meetings, icon: 'fa-calendar-check', color: 'var(--success)' },
        { label: 'Interesses', value: stats.total_interested, icon: 'fa-thumbs-up', color: 'var(--warning)' },
        { label: 'Taux conversion', value: stats.conversion_rate + '%', icon: 'fa-chart-line', color: '#a855f7' },
    ]);
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
}

// ============================================
// SCRAPER CONTROLS
// ============================================
async function startScraper() {
    const city = document.getElementById('scraperCity').value;
    const category = document.getElementById('scraperCategory').value;
    document.getElementById('scraperStatus').className = 'scraper-status online';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper actif';
    // TODO: WebSocket connection pour resultats temps reel
    console.log(`[Scraper] Lancement: ${category} a ${city}`);
}

function stopScraper() {
    document.getElementById('scraperStatus').className = 'scraper-status offline';
    document.getElementById('scraperStatus').innerHTML = '<i class="fa-solid fa-circle"></i> Scraper arrete';
}

// ============================================
// EXPORT
// ============================================
async function exportLeads(format) {
    // TODO: appel API export avec streaming
    console.log(`[Export] Format: ${format}`);
}

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
