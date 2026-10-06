#!/bin/bash
# ==============================================================================
# ALJ ESCALADE — Déploiement Cloud Run (0 € / mois)
# Idéal pour exécution directe dans Google Cloud Shell
# ==============================================================================

set -e

SERVICE_NAME="alj-escalade-api"
REGION="europe-west1"

echo "=============================================================================="
echo "🚀 ALJ ESCALADE — Déploiement Cloud Run (0 € / mois)"
echo "=============================================================================="
echo ""

if ! command -v gcloud &> /dev/null; then
    echo "❌ ERREUR : La commande 'gcloud' est introuvable."
    echo "Si vous êtes sur votre PC, installez le Google Cloud SDK :"
    echo "https://cloud.google.com/sdk/docs/install"
    echo "Ou utilisez directement Google Cloud Shell (gcloud pré-installé)."
    exit 1
fi

CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$CURRENT_PROJECT" ] || [ "$CURRENT_PROJECT" = "(unset)" ]; then
    CURRENT_PROJECT="smart-amplifier-510811-n6"
fi

echo "Configuration détectée :"
echo "  - Projet Google Cloud : $CURRENT_PROJECT"
echo "  - Service             : $SERVICE_NAME"
echo "  - Région              : $REGION"
echo "  - Instances min/max   : 0 min (0€ au repos) / 2 max"
echo "  - Mémoire             : 512 MiB (Free Tier)"
echo ""

read -p "Lancer le déploiement sur ce projet ? (O/n) : " CONFIRM
if [ "$CONFIRM" = "n" ] || [ "$CONFIRM" = "N" ]; then
    echo "Déploiement annulé."
    exit 0
fi

echo ""
echo "📦 Envoi du code source et construction de l'image (Cloud Build)..."
echo ""

gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$CURRENT_PROJECT" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 2 \
    --timeout 60

echo ""
echo "=============================================================================="
echo "✅ DÉPLOIEMENT RÉUSSI SUR GOOGLE CLOUD RUN !"
echo "=============================================================================="

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$CURRENT_PROJECT" --region "$REGION" --format="value(status.url)" 2>/dev/null || true)

echo ""
echo "🌐 URL publique du service :"
echo "   $SERVICE_URL"
echo ""
echo "📱 Application PWA Mobile Coachs :"
echo "   $SERVICE_URL/competitions"
echo ""
echo "🔔 URL du Webhook à copier dans HelloAsso :"
echo "   $SERVICE_URL/webhooks/helloasso"
echo ""
echo "🏥 Sonde de santé :"
echo "   $SERVICE_URL/health"
echo ""
echo "=============================================================================="
