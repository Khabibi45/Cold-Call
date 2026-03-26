# ============================================
# Cold Call Platform — Backend API
# Python 3.12-slim (PAS alpine — evite bugs cryptography/bcrypt)
# ============================================

FROM python:3.12.7-slim AS builder

WORKDIR /build

# Installer les deps systeme pour compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.in .

# Installer pip-tools et compiler les deps
RUN pip install --no-cache-dir pip-tools && \
    pip-compile requirements.in -o requirements.txt && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage final (leger) ---
FROM python:3.12.7-slim

WORKDIR /app

# Copier les deps compilees
COPY --from=builder /install /usr/local

# Copier l'application
COPY app/ app/

# Healthcheck Docker
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
