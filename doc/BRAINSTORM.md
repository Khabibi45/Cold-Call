# BRAINSTORM COMPLET — Cold Call Platform

> Document de recherche et decisions techniques. Ce fichier contient TOUTES les reflexions,
> recherches et decisions prises pour le projet. Il est separe des docs techniques.

---

## 1. VISION DU PROJET

**Objectif** : Plateforme SaaS tout-en-un de cold calling pour vendre des sites web aux entreprises sans presence web.

**Fonctionnalites cles** :
1. **Scraper temps reel** : Tourne 24/7, trouve des entreprises sans site web via Google Maps
2. **Power Dialer** : Appels en boucle depuis le navigateur (WebRTC), auto-dial au raccroche
3. **CRM integre** : Fiches contacts, statuts, notes, emails, planning callbacks
4. **Analytics complet** : Stats d'appels, taux de conversion, heatmaps horaires, leaderboard

---

## 2. RECHERCHE APIs SCRAPING

### Comparaison des APIs

| Service | Prix / 1K leads | Filtre "sans site" | Verdict |
|---------|-----------------|-------------------|---------|
| Outscraper | $1-3 | Oui (champ site vide) | **Meilleur rapport qualite/prix** |
| Scrap.io | 139EUR/mois flat 40K | Filtre natif | Plus cle-en-main |
| Apify | ~$4 | Actor dedie | Flexible |
| SerpAPI | ~$0.50 (150$/mois=300K) | Oui | Bon volume |
| Google Places API | $20-35 | Oui (tier Enterprise) | Trop cher bulk |
| Foursquare | GRATUIT 10K/mois | Oui | Complement parfait |

### Decision : Outscraper API + Foursquare gratuit en complement

---

## 3. SYSTEME ANTI-DOUBLON

### Architecture 5 niveaux :
```
Nouveau lead scrape
    |
[1] Normaliser telephone (E.164 via lib phonenumbers)
    |
[2] Check Bloom Filter en RAM → deja vu ? → SKIP
    |
[3] Check place_id dans Set RAM → deja vu ? → SKIP
    |
[4] INSERT PostgreSQL ON CONFLICT (phone_e164) DO NOTHING
    |
[5] Si insere → ajouter au Bloom + push WebSocket
    Si rejete → incrementer compteur "doublons evites"
```

### Normalisation telephone :
- `05 61 57 88 01` = `0561578801` = `+33561578801` = meme numero
- Lib Python : `phonenumbers` (port de libphonenumber Google)

---

## 4. STATUTS D'APPEL (DISPOSITIONS)

15 statuts professionnels :

| Code | Label FR | Couleur | Action suivante |
|------|----------|---------|-----------------|
| no_answer | Pas de reponse | Gris | Auto-relance J+2 |
| busy | Occupe | Gris | Auto-relance H+2 |
| voicemail | Messagerie vocale | Bleu | Relance J+1 |
| wrong_number | Mauvais numero | Rouge | Archiver |
| disconnected | Numero HS | Rouge | Archiver |
| gatekeeper | Standard/Accueil | Orange | Relance avec nom |
| interested | Interesse | Vert | Follow-up email |
| not_interested | Pas interesse | Rouge | Archiver |
| callback | Rappel planifie | Violet | Agenda + notif |
| meeting_booked | RDV pris | Vert vif | Agenda + email conf |
| follow_up | A relancer | Orange | Tache creee |
| not_qualified | Non qualifie | Gris | Archiver |
| already_customer | Deja client | Bleu | CRM existant |
| do_not_call | Ne plus appeler | Noir | Blocklist |
| left_company | Parti/Mauvais contact | Gris | Archiver |

---

## 5. POWER DIALER — ARCHITECTURE TECHNIQUE

### State Machine :
```
IDLE → START SESSION → LOAD NEXT → SHOW INFO (2-3s) → DIALING
    → CONNECTED → CONVERSATION → HANGUP → DISPOSITION → NEXT
    → NO ANSWER/BUSY → AUTO-DISPOSITION → NEXT
```

### Technique "Conference Room" (zero dead time) :
1. Agent rejoint une conference persistante au debut de session
2. Systeme dial le prospect dans la meme conference
3. Quand le prospect repond, il entend l'agent immediatement
4. Quand l'appel finit, prospect retire mais agent reste
5. Systeme dial immediatement le suivant

### Parametres :
- Ring timeout : 25 secondes
- Wrap-up time : 15 secondes (configurable)
- Inter-call gap : <2 secondes avec conference technique
- AMD (detection repondeur) : via Twilio, 3-5s

---

## 6. TELEPHONIE — CHOIX TECHNIQUE

### Comparaison couts appel mobile FR :

| Solution | EUR/min mobile FR | Complexite |
|----------|------------------|------------|
| OVH Trunk + Asterisk | 0.012 | Haute |
| Plivo | 0.035 | Basse |
| Vonage | 0.045 | Basse |
| Twilio | 0.052 | Tres basse |

### Decision MVP : Twilio (meilleure doc, JS SDK, WebRTC natif)
### Decision Production : Migration vers Plivo ou OVH selon volume

---

## 7. SCORING DES LEADS

| Critere | Poids | Scoring |
|---------|-------|---------|
| Pas de site web | Obligatoire | Filtre binaire |
| Nombre avis Google | 25% | 0-5:2 / 5-20:5 / 20-50:8 / 50+:10 |
| Note Google | 10% | <3.5:2 / 3.5-4.2:5 / 4.2-4.7:8 / 4.7+:10 |
| Nombre photos | 15% | 0:1 / 1-5:4 / 5-15:7 / 15+:10 |
| Categorie business | 20% | Tier 1-3 (voir ci-dessous) |
| Repond aux avis | 10% | Jamais:1 / Parfois:5 / Souvent:10 |
| Concurrent a un site | 10% | Non:2 / Oui:10 |
| Reseaux sociaux | 10% | Aucun:1 / Inactif:4 / Actif:10 |

### Categories Tier 1 (appeler en premier) :
Restaurants gastro, salons coiffure/beaute, photographes, coachs sportifs, veterinaires, dentistes

### Categories Tier 2 :
Artisans, gites, auto-ecoles, fleuristes, garages

### Categories Tier 3 :
Boulangeries, epiceries, tabacs

---

## 8. COLD CALLING — MEILLEURES PRATIQUES

### Horaires legaux (France) :
- Lun-Ven 10h-13h / 14h-20h
- JAMAIS weekends / jours feries
- Max 4 tentatives par prospect

### Horaires optimaux par type :
| Type | Meilleur creneau | Eviter |
|------|-----------------|--------|
| Restaurants | 14h30-16h30 Mar-Jeu | 11h-14h, 18h-22h |
| Coiffeurs | 9h-9h30 ou mardi matin | Samedi |
| Artisans | 7h30-8h30 ou 17h-18h | 9h-17h (chantier) |

### Script d'ouverture :
> "Bonjour [Prenom], je suis [Ton prenom]. J'ai cherche [type] a [ville]
> sur Google et je suis tombe sur votre fiche — vous avez d'excellents avis.
> Question rapide, vous avez 30 secondes ?"

---

## 9. SECURITE & LEGAL

### Auth : OAuth2 Google/GitHub + JWT + Argon2
### Paiement : Stripe (1.5% + 0.25EUR EU)
### RGPD : Interet legitime B2B, opt-out obligatoire, blacklist interne
### Enregistrement appels : Legal B2B si informe avant
### ARCEP : Pas besoin si on utilise Twilio/OVH (ils ont la licence)

---

## 10. MONITORING & STABILITE LONG TERME

### Stack monitoring gratuit :
- Sentry (free tier) : erreurs/exceptions
- UptimeRobot : uptime HTTP
- Grafana Cloud (free) : metriques custom

### Stabilite 10 ans :
- Pin toutes les deps (pip-compile)
- Alembic migrations DB des jour 1
- Docker python:3.12-slim (pas alpine)
- PostgreSQL = 30+ ans de stabilite
- GitHub Actions CI/CD
- Tests integration automatises

### Bugs connus a eviter :
- passlib + bcrypt >= 4.1 → utiliser Argon2
- asyncpg pool exhaustion → pool_size=20, max_overflow=10
- SQLAlchemy async lazy loading → toujours selectinload()
- nginx WebSocket timeout 60s → configurer proxy_read_timeout + ping/pong
- Docker alpine + cryptography → utiliser slim
