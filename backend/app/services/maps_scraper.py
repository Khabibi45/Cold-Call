"""
Scraper Google Maps via Playwright — Zero API, Zero proxy.
Anti-detection multi-couches : stealth, fingerprint, comportement humain.
"""

import asyncio
import random
import math
import re
import logging
from collections import deque
from datetime import datetime, timezone
from itertools import count
from typing import Any

from playwright.async_api import async_playwright, Page, BrowserContext

from app.core.config import get_settings
from app.core.database import async_session
from app.models.lead import Lead
from app.services.dedup import DeduplicationService

logger = logging.getLogger(__name__)
settings = get_settings()


# ============================================
# COMPORTEMENT HUMAIN
# ============================================

def _lognormal_delay(median_ms: float, sigma: float = 0.5) -> float:
    """Delai log-normal en secondes. Mode RAPIDE (x2)."""
    mu = math.log(median_ms / 2000)  # /2 = mode rapide
    delay = random.lognormvariate(mu, sigma)
    return max(0.15, min(delay, 10.0))


def _gaussian_delay(mean_ms: float, std_ms: float = 50) -> float:
    """Delai gaussien rapide pour les actions."""
    delay = random.gauss(mean_ms * 0.5, std_ms * 0.5) / 1000  # x0.5 = mode rapide
    return max(0.02, min(delay, 0.25))


async def _human_type(page: Page, selector: str, text: str):
    """Tape un texte avec des delais humains entre chaque caractere."""
    el = page.locator(selector)
    await el.click()
    await asyncio.sleep(_lognormal_delay(300))
    for char in text:
        await page.keyboard.type(char, delay=_gaussian_delay(110, 40) * 1000)
        # Micro-pause aleatoire entre les mots
        if char == ' ':
            await asyncio.sleep(_gaussian_delay(200, 80))


async def _human_scroll(page: Page, container_selector: str, amount: int = 400):
    """Scroll humain avec vitesse variable."""
    container = page.locator(container_selector)
    # Scroll par petits increments (comme une molette)
    steps = random.randint(3, 6)
    per_step = amount // steps
    for i in range(steps):
        await container.evaluate(f"el => el.scrollTop += {per_step + random.randint(-30, 30)}")
        await asyncio.sleep(_gaussian_delay(150, 50))
    # Pause lecture apres scroll
    await asyncio.sleep(_lognormal_delay(1500, 0.6))


async def _human_move_and_click(page: Page, selector: str):
    """Deplace la souris en courbe de Bezier puis clique."""
    el = page.locator(selector).first
    box = await el.bounding_box()
    if not box:
        await el.click()
        return
    # Point cible avec offset aleatoire (pas le centre exact)
    target_x = box['x'] + box['width'] * random.gauss(0.5, 0.15)
    target_y = box['y'] + box['height'] * random.gauss(0.5, 0.15)
    # Deplacer en plusieurs etapes (courbe)
    steps = random.randint(8, 15)
    for i in range(steps):
        t = (i + 1) / steps
        # Courbe bezier simple
        noise_x = random.gauss(0, 2)
        noise_y = random.gauss(0, 2)
        await page.mouse.move(target_x * t + noise_x, target_y * t + noise_y)
        await asyncio.sleep(random.uniform(0.01, 0.04))
    # Hover avant clic
    await asyncio.sleep(_gaussian_delay(120, 40))
    await page.mouse.click(target_x, target_y)
    await asyncio.sleep(_lognormal_delay(500))


# ============================================
# STEALTH PATCHES
# ============================================

STEALTH_SCRIPT = """
// Supprimer navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Faux plugins Chrome
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ]
});

// Faux languages
Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr', 'en-US', 'en'] });

// Cacher l'automation
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

// Chrome runtime fake
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };

// Permissions fake
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// WebGL vendor spoof
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""


# ============================================
# SCRAPER GOOGLE MAPS
# ============================================

class GoogleMapsScraper:
    """Scrape Google Maps directement via Playwright.
    Zero API, zero proxy, zero cout.
    Anti-detection : stealth + fingerprint + comportement humain."""

    MAX_PER_SESSION = 40  # Recherches max par session (mode rapide)
    PAUSE_BETWEEN_SESSIONS = 300  # 5 minutes entre les sessions (mode rapide)

    def __init__(self):
        self._running = False
        self._should_stop = False
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._stats = {"total": 0, "inserted": 0, "duplicates": 0, "errors": 0, "no_phone": 0, "has_website": 0, "skipped_known": 0}
        self._current_query = ""
        self._current_city = ""
        self._step = ""
        # Logs : deque thread-safe, taille max 500
        self._logs: deque[dict] = deque(maxlen=500)
        self._log_counter = count(1)  # Compteur auto-increment pour log_id
        self._progress = 0
        self._total_queries = 0
        self._current_query_index = 0
        self._current_fiche_index = 0
        self._total_fiches = 0
        # Memoire : noms deja en base (charge au demarrage du scrape)
        self._known_names: set[str] = set()
        # Parallelisme : pages multiples
        self._pages: list[Page] = []
        self._num_workers = 3  # Nombre d'agents paralleles (1-5)

    def _log(self, message: str, level: str = "info", agent_id: int = 0, data: dict | None = None):
        """Ajoute un log temps reel et broadcast via WebSocket.
        agent_id=0 : processus principal, 1+ : workers paralleles."""
        entry = {
            "log_id": next(self._log_counter),
            "time": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "agent_id": agent_id,
            "message": message,
            "step": self._step,
            "stats": self._stats.copy(),
            "progress": self._progress,
        }
        if data:
            entry["data"] = data
        self._logs.append(entry)  # deque(maxlen=500) gere la taille automatiquement
        logger.info("[Maps][agent:%d] %s", agent_id, message)
        # Broadcast WebSocket
        try:
            from app.api.websocket import manager
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(manager.broadcast({
                    "type": "maps_log",
                    "data": entry,
                }))
        except Exception:
            pass

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "query": self._current_query,
            "city": self._current_city,
            "step": self._step,
            "progress": self._progress,
            "num_workers": self._num_workers,
            "stats": self._stats.copy(),
            "logs": list(self._logs)[-20:],  # 20 derniers logs par defaut
        }

    def stop(self):
        self._should_stop = True

    # --- Lancement navigateur stealth ---
    async def _start_browser(self):
        """Lance Chrome reel (pas Chromium) avec stealth complet."""
        self._step = "Lancement du navigateur..."
        self._log("Lancement de Chrome stealth")
        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ],
        )
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            locale='fr-FR',
            timezone_id='Europe/Paris',
            geolocation={'latitude': 43.6047, 'longitude': 1.4442},
            permissions=['geolocation'],
        )
        self._page = await self._context.new_page()
        # Injecter le stealth script AVANT toute navigation
        await self._page.add_init_script(STEALTH_SCRIPT)
        self._log("Navigateur Chrome stealth pret")

    async def _close_browser(self):
        """Ferme proprement le navigateur."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
            logger.info("Navigateur ferme")

    # --- Warm-up session (se comporter comme un vrai utilisateur) ---
    async def _warmup(self):
        """Visite Google Maps et accepte les cookies."""
        self._step = "Warm-up : ouverture Google Maps..."
        self._log("Navigation vers Google Maps")
        page = self._page

        # Aller directement sur Google Maps
        await page.goto('https://www.google.fr/maps', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(_lognormal_delay(2000))

        # Accepter les cookies — essayer plusieurs selecteurs
        for attempt in range(3):
            try:
                for selector in [
                    'button:has-text("Tout accepter")',
                    'button:has-text("Accept all")',
                    'button:has-text("Accepter tout")',
                    'form[action*="consent"] button',
                    '[aria-label*="Accept"]',
                    '[aria-label*="Accepter"]',
                ]:
                    btn = page.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        logger.info("Cookies acceptes via '%s'", selector)
                        await asyncio.sleep(_lognormal_delay(2000))
                        break
                break
            except Exception:
                await asyncio.sleep(1)

        # Verifier que Maps est charge (carte visible)
        try:
            await page.wait_for_selector('canvas, #scene, div[aria-label="Google Maps"]', timeout=15000)
            logger.info("Warm-up termine — Google Maps charge")
        except Exception:
            await page.screenshot(path='/app/debug_warmup.png')
            logger.warning("Warm-up : Maps pas completement charge — on continue quand meme")

    # --- Recherche sur Google Maps ---
    async def _search(self, query: str, city: str, page: Page = None, agent_id: int = 0) -> int:
        """Lance une recherche via URL directe (plus fiable que la saisie)."""
        self._step = f"Recherche : {query} a {city}..."
        self._log(f"Recherche Google Maps : '{query} {city}'", agent_id=agent_id)
        if page is None:
            page = self._page
        search_text = f"{query} {city}"

        # Methode URL directe — contourne les problemes de saisie
        encoded = search_text.replace(' ', '+')
        url = f"https://www.google.fr/maps/search/{encoded}/?hl=fr"
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._log("Page chargee, attente des resultats...", agent_id=agent_id)
        await asyncio.sleep(_lognormal_delay(4000, 0.4))

        # Attendre le feed de resultats
        try:
            await page.wait_for_selector('div[role="feed"]', timeout=15000)
        except Exception:
            # Peut-etre un consent screen sur la page de resultats
            for selector in ['button:has-text("Tout accepter")', 'button:has-text("Accept all")']:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(3)
                    break
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=10000)
            except Exception:
                await page.screenshot(path='/app/debug_search.png')
                logger.warning("Pas de feed pour '%s' — screenshot sauve", search_text)
                return 0

        # Scroller pour charger plus de resultats
        self._log("Scroll pour charger plus de resultats...", agent_id=agent_id)
        feed = page.locator('div[role="feed"]')
        loaded_count = 0
        max_scrolls = 15
        for i in range(max_scrolls):
            if self._should_stop:
                break
            # Compter les resultats actuels
            results = page.locator('div[role="feed"] > div > div > a')
            current_count = await results.count()
            if current_count == loaded_count and i > 2:
                break
            loaded_count = current_count
            self._step = f"Scroll {i+1}/{max_scrolls} — {loaded_count} resultats charges"
            # Scroll humain
            await _human_scroll(page, 'div[role="feed"]', random.randint(300, 500))
            if i > 0 and i % 6 == 0:
                await asyncio.sleep(_lognormal_delay(2000, 0.4))

        self._log(f"{loaded_count} resultats charges pour '{search_text}'", agent_id=agent_id)
        return loaded_count

    # --- Extraire les donnees d'une fiche ---
    async def _extract_business(self, page: Page = None) -> dict | None:
        """Extrait les donnees d'une fiche business ouverte."""
        if page is None:
            page = self._page
        await asyncio.sleep(_lognormal_delay(2000, 0.4))

        data = {}

        # Nom — attendre le panneau de detail puis extraire
        try:
            # Attendre le vrai h1 du business (pas "Resultats")
            await page.wait_for_selector('h1.DUwDvf', timeout=8000)
            name_el = page.locator('h1.DUwDvf').first
            if await name_el.count() > 0:
                data['name'] = (await name_el.text_content()).strip()
        except Exception:
            pass

        # Fallback : aria-label du panneau principal
        if not data.get('name'):
            try:
                mains = page.locator('div[role="main"][aria-label]')
                count = await mains.count()
                for i in range(count):
                    label = (await mains.nth(i).get_attribute('aria-label') or '').strip()
                    if label and label.lower() not in ('résultats', 'results', 'google maps', ''):
                        data['name'] = label
                        break
            except Exception:
                pass

        if not data.get('name'):
            return None

        # Site web : a[data-item-id="authority"] — ABSENT = pas de site
        try:
            website_el = page.locator('a[data-item-id="authority"]')
            if await website_el.count() > 0:
                data['website'] = await website_el.get_attribute('href') or ''
                data['has_website'] = True
            else:
                data['website'] = ''
                data['has_website'] = False
        except Exception:
            data['website'] = ''
            data['has_website'] = False

        # Telephone : button[data-item-id^="phone"]
        try:
            phone_el = page.locator('button[data-item-id^="phone"]')
            if await phone_el.count() > 0:
                data['phone'] = (await phone_el.get_attribute('data-item-id')).replace('phone:tel:', '')
            else:
                data['phone'] = ''
        except Exception:
            data['phone'] = ''

        # Adresse : button[data-item-id="address"]
        try:
            addr_el = page.locator('button[data-item-id="address"]')
            if await addr_el.count() > 0:
                addr_text = await addr_el.locator('div.fontBodyMedium').text_content()
                data['address'] = addr_text.strip() if addr_text else ''
            else:
                data['address'] = ''
        except Exception:
            data['address'] = ''

        # Note : span avec aria-label contenant "etoile" ou "star"
        try:
            rating_el = page.locator('div.F7nice span[aria-hidden="true"]').first
            if await rating_el.count() > 0:
                rating_text = await rating_el.text_content()
                data['rating'] = float(rating_text.replace(',', '.')) if rating_text else None
            else:
                data['rating'] = None
        except Exception:
            data['rating'] = None

        # Nombre d'avis
        try:
            reviews_el = page.locator('div.F7nice span[aria-label]').first
            if await reviews_el.count() > 0:
                aria = await reviews_el.get_attribute('aria-label') or ''
                # Extraire le nombre : "1 234 avis" ou "1,234 reviews"
                nums = re.findall(r'[\d\s.,]+', aria)
                if nums:
                    data['reviews'] = int(nums[0].replace(' ', '').replace('.', '').replace(',', ''))
                else:
                    data['reviews'] = 0
            else:
                data['reviews'] = 0
        except Exception:
            data['reviews'] = 0

        # Categorie
        try:
            cat_el = page.locator('button[jsaction*="category"]').first
            if await cat_el.count() > 0:
                data['category'] = (await cat_el.text_content()).strip()
            else:
                data['category'] = ''
        except Exception:
            data['category'] = ''

        # URL Google Maps actuelle
        data['maps_url'] = page.url

        return data

    # --- Pipeline : scraper une recherche complete ---
    async def _load_known_names(self):
        """Charge tous les noms deja en base dans un set pour eviter de re-scraper."""
        try:
            async with async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Lead.business_name).where(Lead.business_name.isnot(None))
                )
                names = {row[0].strip().lower() for row in result.all() if row[0]}
                self._known_names = names
                self._log(f"Memoire chargee : {len(names)} fiches connues en base")
        except Exception as e:
            logger.warning("Erreur chargement memoire noms : %s", e)
            self._known_names = set()

    def _is_known(self, name: str) -> bool:
        """Verifie si un nom est deja connu (en base ou scrape cette session)."""
        if not name:
            return False
        return name.strip().lower() in self._known_names

    def _remember(self, name: str):
        """Ajoute un nom a la memoire de session."""
        if name:
            self._known_names.add(name.strip().lower())

    async def _extract_names_from_list(self, page: Page = None) -> list[dict]:
        """Extrait les noms et aria-labels depuis la LISTE de resultats (sans cliquer).
        Retourne une liste de {index, name, aria_label} pour pre-filtrer."""
        if page is None:
            page = self._page
        items = []
        links = page.locator('div[role="feed"] a.hfpxzc')
        count = await links.count()
        for i in range(count):
            try:
                link = links.nth(i)
                aria = (await link.get_attribute('aria-label') or '').strip()
                items.append({"index": i, "name": aria})
            except Exception:
                items.append({"index": i, "name": ""})
        return items

    async def scrape_query(self, query: str, city: str, page: Page = None, agent_id: int = 0) -> list[dict]:
        """Scrape une recherche avec pre-filtrage memoire (skip les fiches deja connues).
        page : page Playwright a utiliser (defaut = self._page).
        agent_id : identifiant de l'agent/worker (0 = principal, 1+ = workers)."""
        if page is None:
            page = self._page
        self._current_query = query
        self._current_city = city

        # Lancer la recherche
        result_count = await self._search(query, city, page=page, agent_id=agent_id)
        if result_count == 0:
            return []

        # ETAPE 1 : Extraire les noms depuis la liste SANS cliquer
        self._step = f"Pre-scan des noms ({query})..."
        list_items = await self._extract_names_from_list(page=page)
        self._total_fiches = len(list_items)

        # ETAPE 2 : Pre-filtrer les noms deja connus
        to_check = []
        for item in list_items:
            if self._is_known(item['name']):
                self._stats['skipped_known'] += 1
                self._log(f"⏭️ {item['name']} — deja en base, skip", level="skip", agent_id=agent_id)
            else:
                to_check.append(item)

        if not to_check:
            self._log(f"Toutes les fiches de '{query}' sont deja connues", level="info", agent_id=agent_id)
            return []

        self._log(f"{len(to_check)} fiches a verifier sur {len(list_items)} ({len(list_items)-len(to_check)} deja connues)", agent_id=agent_id)

        # ETAPE 3 : Cliquer uniquement sur les fiches INCONNUES
        extracted = []
        for idx, item in enumerate(to_check):
            if self._should_stop:
                break

            fiche_pct = round((idx + 1) / len(to_check) * 100)
            self._step = f"Fiche {idx+1}/{len(to_check)} — {query} ({fiche_pct}%)"
            self._progress = round(
                (self._current_query_index / max(self._total_queries, 1)) * 100
                + (fiche_pct / max(self._total_queries, 1))
            )

            try:
                link = page.locator('div[role="feed"] a.hfpxzc').nth(item['index'])
                if await link.count() == 0:
                    continue

                await link.click()
                await asyncio.sleep(_lognormal_delay(2500, 0.5))

                biz = await self._extract_business(page=page)
                if biz:
                    self._stats['total'] += 1
                    # Ajouter a la memoire pour eviter les doublons dans la meme session
                    self._remember(biz['name'])

                    if biz['has_website']:
                        self._stats['has_website'] += 1
                        self._log(f"❌ {biz['name']} — a un site web", level="skip", agent_id=agent_id)
                        continue

                    if not biz['phone']:
                        self._stats['no_phone'] += 1
                        self._log(f"⚠️ {biz['name']} — pas de telephone", level="skip", agent_id=agent_id)
                        continue

                    extracted.append(biz)
                    self._log(
                        f"✅ LEAD : {biz['name']} | {biz['phone']} | {biz.get('rating', '?')}/5",
                        level="success",
                        agent_id=agent_id,
                        data={"name": biz['name'], "phone": biz['phone'], "rating": biz.get('rating')},
                    )

                # Micro-pause toutes les 8 fiches
                if idx > 0 and idx % 8 == 0:
                    await asyncio.sleep(_lognormal_delay(3000, 0.5))

            except Exception as e:
                self._stats['errors'] += 1
                logger.warning("Erreur extraction fiche %d: %s", item['index'], str(e)[:100])
                continue

        return extracted

    # --- Insertion en base avec dedup ---
    async def _insert_leads(self, leads: list[dict], city: str):
        """Insere les leads en base avec anti-doublon complet."""
        dedup = DeduplicationService.get_instance()

        async with async_session() as session:
            for lead_data in leads:
                try:
                    phone_raw = lead_data.get('phone', '')
                    phone_e164 = dedup.normalize_phone(phone_raw, 'FR')

                    if not phone_e164:
                        self._stats['no_phone'] += 1
                        continue

                    # Check dedup RAM (Bloom + place_id)
                    if dedup.is_duplicate(phone_e164=phone_e164):
                        self._stats['duplicates'] += 1
                        continue

                    # INSERT avec ON CONFLICT
                    from sqlalchemy import text
                    await session.execute(text("""
                        INSERT INTO leads (business_name, phone, phone_e164, address, city, category,
                                         rating, review_count, maps_url, has_website, source, lead_score, scraped_at, updated_at)
                        VALUES (:name, :phone, :phone_e164, :address, :city, :category,
                                :rating, :reviews, :maps_url, false, 'google_maps', :score,
                                :now, :now)
                        ON CONFLICT (phone_e164) DO NOTHING
                    """), {
                        'name': lead_data['name'],
                        'phone': phone_raw,
                        'phone_e164': phone_e164,
                        'address': lead_data.get('address', ''),
                        'city': city,
                        'category': lead_data.get('category', ''),
                        'rating': lead_data.get('rating'),
                        'reviews': lead_data.get('reviews', 0),
                        'maps_url': lead_data.get('maps_url', ''),
                        'score': self._calculate_score(lead_data),
                        'now': datetime.now(timezone.utc),
                    })

                    # Enregistrer dans le Bloom filter
                    dedup.register(phone_e164=phone_e164, place_id=None)
                    self._stats['inserted'] += 1

                except Exception as e:
                    self._stats['errors'] += 1
                    logger.warning("Erreur insertion: %s", str(e)[:100])
                    continue

            await session.commit()

    def _calculate_score(self, data: dict) -> int:
        """Calcule le score d'un lead (0-100)."""
        score = 0
        # Pas de site web = +15
        if not data.get('has_website'):
            score += 15
        # Avis
        reviews = data.get('reviews', 0)
        if reviews >= 50:
            score += 25
        elif reviews >= 20:
            score += 20
        elif reviews >= 5:
            score += 12
        else:
            score += 5
        # Note
        rating = data.get('rating') or 0
        if rating >= 4.5:
            score += 10
        elif rating >= 4.0:
            score += 8
        elif rating >= 3.5:
            score += 5
        else:
            score += 2
        # Categorie
        cat = (data.get('category', '') or '').lower()
        if any(t in cat for t in ['restaurant', 'coiffeur', 'beauté', 'dentiste', 'vétérinaire']):
            score += 20
        elif any(t in cat for t in ['artisan', 'plombier', 'électricien', 'garage']):
            score += 15
        else:
            score += 10
        return min(score, 100)

    # --- Lancement complet multi-queries ---
    async def run(self, queries: list[str], city: str):
        """Lance un scrape complet sur plusieurs categories."""
        self._running = True
        self._should_stop = False
        self._stats = {"total": 0, "inserted": 0, "duplicates": 0, "errors": 0, "no_phone": 0, "has_website": 0, "skipped_known": 0}
        self._logs = deque(maxlen=500)
        self._log_counter = count(1)  # Reset du compteur de logs
        self._total_queries = len(queries)
        self._progress = 0

        self._log(f"Demarrage scrape : {len(queries)} categories pour {city}")
        self._log(f"Categories : {', '.join(queries)}")

        try:
            # Charger la memoire des noms deja en base
            await self._load_known_names()

            await self._start_browser()
            await self._warmup()

            searches_this_session = 0

            # Scraper les categories par paquets en parallele (selon num_workers)
            batch_size = self._num_workers
            for batch_start in range(0, len(queries), batch_size):
                if self._should_stop:
                    self._log("Arret demande par l'utilisateur", level="warning")
                    break

                batch = queries[batch_start:batch_start + batch_size]
                self._current_query_index = batch_start
                self._progress = round(batch_start / len(queries) * 100)

                # Limite par session
                if searches_this_session >= self.MAX_PER_SESSION:
                    self._step = "Pause securite (5 minutes)..."
                    self._log("Pause de 5 minutes (anti-detection)")
                    await self._close_browser()
                    for remaining in range(self.PAUSE_BETWEEN_SESSIONS, 0, -30):
                        self._step = f"Pause securite — reprise dans {remaining}s"
                        await asyncio.sleep(30)
                    await self._start_browser()
                    await self._warmup()
                    searches_this_session = 0

                if len(batch) == 1:
                    # Une seule categorie : sequentiel classique
                    self._log(f"[{batch_start+1}/{len(queries)}] {batch[0]}")
                    leads = await self.scrape_query(batch[0], city)
                    if leads:
                        self._step = f"Insertion de {len(leads)} leads..."
                        await self._insert_leads(leads, city)
                        self._log(f"{len(leads)} leads inseres pour '{batch[0]}'", level="success")
                    else:
                        self._log(f"0 lead pour '{batch[0]}'", level="info")
                    searches_this_session += 1
                else:
                    # Plusieurs categories : scrape PARALLELE avec pages multiples
                    self._log(f"🚀 Batch parallele : {', '.join(batch)} ({len(batch)} en simultane)")

                    async def _scrape_one(query_name: str, page_obj: Page, worker_id: int):
                        """Scrape une categorie sur une page donnee avec un agent identifie."""
                        try:
                            leads = await self.scrape_query(query_name, city, page=page_obj, agent_id=worker_id)
                            return query_name, leads
                        except Exception as e:
                            self._log(f"Erreur parallele '{query_name}': {str(e)[:100]}", level="error", agent_id=worker_id)
                            return query_name, []

                    # Creer des pages supplementaires pour le batch
                    extra_pages = []
                    for _ in range(len(batch) - 1):
                        try:
                            p = await self._context.new_page()
                            await p.add_init_script(STEALTH_SCRIPT)
                            extra_pages.append(p)
                        except Exception:
                            break

                    # Assigner les pages : page principale + pages extras
                    # agent_id 1-based pour les workers paralleles
                    all_pages = [self._page] + extra_pages
                    tasks = []
                    for i, q in enumerate(batch):
                        if i < len(all_pages):
                            tasks.append(_scrape_one(q, all_pages[i], worker_id=i + 1))

                    # Lancer en parallele
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Fermer les pages extras
                    for p in extra_pages:
                        try:
                            await p.close()
                        except Exception:
                            pass

                    # Traiter les resultats
                    for result in results:
                        if isinstance(result, Exception):
                            self._stats['errors'] += 1
                            continue
                        q_name, leads = result
                        if leads:
                            self._step = f"Insertion de {len(leads)} leads ({q_name})..."
                            await self._insert_leads(leads, city)
                            self._log(f"{len(leads)} leads inseres pour '{q_name}'", level="success")
                        else:
                            self._log(f"0 lead pour '{q_name}'", level="info")

                    searches_this_session += len(batch)

                # Pause entre les batchs
                pause = _lognormal_delay(3000, 0.4)
                self._step = f"Pause ({pause:.0f}s)..."
                await asyncio.sleep(pause)

        except Exception as e:
            self._log(f"ERREUR : {str(e)[:200]}", level="error")
        finally:
            await self._close_browser()
            self._running = False
            self._progress = 100
            self._step = "Termine"
            self._log(
                f"Scrape termine : {self._stats['inserted']} inseres / {self._stats['total']} scannes / {self._stats['has_website']} avec site / {self._stats['duplicates']} doublons",
                level="success",
            )

    def start_background(self, queries: list[str], city: str, num_workers: int = 3):
        """Lance le scrape en tache de fond.
        num_workers : nombre d'agents paralleles (1-5)."""
        if self._running:
            raise RuntimeError("Scrape deja en cours")
        self._num_workers = max(1, min(num_workers, 5))
        asyncio.create_task(self.run(queries, city))


# Singleton
_maps_scraper: GoogleMapsScraper | None = None


def get_maps_scraper() -> GoogleMapsScraper:
    global _maps_scraper
    if _maps_scraper is None:
        _maps_scraper = GoogleMapsScraper()
    return _maps_scraper
