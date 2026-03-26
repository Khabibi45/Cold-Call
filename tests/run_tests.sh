#!/usr/bin/env bash
# Script de lancement des tests avec couverture de code.
# Usage : bash tests/run_tests.sh
# Exit code non-zero si un test echoue.

set -e

# Se placer a la racine du projet
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "========================================="
echo "  Cold Call Platform — Tests"
echo "========================================="
echo ""

# Variables d'environnement pour les tests
export APP_ENV=test
export DATABASE_URL="sqlite+aiosqlite:///./test.db"
export JWT_SECRET_KEY="test-secret-key-for-tests-only"
export SENTRY_DSN=""

# Lancer pytest avec couverture
python -m pytest tests/ \
    --cov=backend/app \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    -v \
    --tb=short \
    -x \
    "$@"

EXIT_CODE=$?

echo ""
echo "========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "  TOUS LES TESTS PASSENT"
else
    echo "  ECHEC — $EXIT_CODE test(s) en erreur"
fi
echo "========================================="

# Nettoyer la DB de test
rm -f test.db

exit $EXIT_CODE
