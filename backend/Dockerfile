# ============================================
# Cold Call Platform — Backend API
# Python 3.12-slim (PAS alpine)
# ============================================

FROM python:3.12.7-slim

WORKDIR /app

# Deps systeme
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Installer pip-tools et compiler les deps
COPY requirements.in .
RUN pip install --no-cache-dir pip-tools && \
    pip-compile requirements.in -o requirements.txt && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium --with-deps

# Copier l'application
COPY app/ app/

# Healthcheck Docker
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
