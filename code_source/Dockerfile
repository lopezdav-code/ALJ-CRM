# ==============================================================================
# Dockerfile — ALJ Escalade Manager API & PWA (Google Cloud Run)
# Architecture Cloud & Mobile (Coût 0 €/mois sur Google Cloud Free Tier)
# ==============================================================================

FROM python:3.11-slim

# Configuration de l'environnement Python et conteneur
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    ALJ_DATA_DIR=/app/data \
    PYTHONPATH=/app/src:/app

WORKDIR /app

# 1. Installation des dépendances Python conteneurisées
COPY requirements-docker.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-docker.txt

# 2. Copie du code source et des ressources web / templates
COPY src/ ./src/
COPY web/ ./web/
COPY doc/ ./doc/
COPY VERSION ./VERSION

# 3. Création d'un utilisateur non-root pour la sécurité et attribution des droits
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

USER appuser

# 4. Port d'écoute Cloud Run (défaut 8080)
EXPOSE 8080

# 5. Sonde de santé interne
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", 8080)}/health')"

# 6. Lancement du serveur FastAPI avec Uvicorn
CMD exec uvicorn server:app --app-dir /app/src --host 0.0.0.0 --port ${PORT:-8080}
