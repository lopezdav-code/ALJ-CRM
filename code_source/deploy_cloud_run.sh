#!/bin/bash
# ==============================================================================
# ALJ ESCALADE — Cloud Run deployment (0 € / month)
# Meant to run from code_source/, e.g. in Google Cloud Shell.
#
# Usage:
#   ./deploy_cloud_run.sh                     Deploy to production (100% of traffic)
#   ./deploy_cloud_run.sh --test              Deploy a test revision (0% of traffic, own URL)
#   ./deploy_cloud_run.sh --rollback [REV]    Send all traffic back to REV
#                                             (default: the revision before the live one)
# ==============================================================================

set -euo pipefail

SERVICE_NAME="alj-escalade-api"
REGION="europe-west1"
TEST_TAG="test"

usage() {
    sed -n '6,10p' "$0" | sed 's/^# \{0,1\}//'
}

MODE="prod"
ROLLBACK_TARGET=""
while [ $# -gt 0 ]; do
    case "$1" in
        --test)
            [ "$MODE" = "prod" ] || { echo "❌ --test and --rollback cannot be combined."; exit 1; }
            MODE="test"
            ;;
        --rollback)
            [ "$MODE" = "prod" ] || { echo "❌ --test and --rollback cannot be combined."; exit 1; }
            MODE="rollback"
            if [ $# -gt 1 ] && [ "${2#-}" = "$2" ]; then
                ROLLBACK_TARGET="$2"
                shift
            fi
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "❌ Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
    shift
done

if ! command -v gcloud &> /dev/null; then
    echo "❌ ERROR: the 'gcloud' command was not found."
    echo "On your PC, install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
    echo "Or run this script from Google Cloud Shell (gcloud is pre-installed)."
    exit 1
fi

CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -z "$CURRENT_PROJECT" ] || [ "$CURRENT_PROJECT" = "(unset)" ]; then
    CURRENT_PROJECT="smart-amplifier-510811-n6"
fi

GCLOUD_TARGET=(--project "$CURRENT_PROJECT" --region "$REGION")

# Revision currently receiving the largest share of traffic (empty if the service does not exist yet)
live_revision() {
    gcloud run services describe "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" \
        --flatten='status.traffic[]' \
        --format='value(status.traffic.percent,status.traffic.revisionName)' 2>/dev/null \
        | sort -rn | awk 'NR == 1 { print $2 }'
}

service_url() {
    gcloud run services describe "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" --format='value(status.url)'
}

tagged_url() {
    gcloud run services describe "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" \
        --flatten='status.traffic[]' \
        --format='value(status.traffic.tag,status.traffic.url)' \
        | awk -v tag="$1" '$1 == tag { print $2 }'
}

# Revision names, newest first
list_revisions() {
    gcloud run revisions list --service "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" \
        --sort-by='~metadata.creationTimestamp' --format='value(metadata.name)'
}

confirm() {
    read -r -p "$1 (y/N): " answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Cancelled."; exit 0; }
}

print_links() {
    echo ""
    echo "🌐 App URL:"
    echo "   $1"
    echo "   PWA (coaches) : $1/competitions"
    echo "   Health check  : $1/health"
}

echo "=============================================================================="
echo "🚀 ALJ ESCALADE — Cloud Run ($MODE)"
echo "=============================================================================="
echo "  - Google Cloud project : $CURRENT_PROJECT"
echo "  - Service              : $SERVICE_NAME"
echo "  - Region               : $REGION"

PREVIOUS_REVISION=$(live_revision || true)
echo "  - Live revision        : ${PREVIOUS_REVISION:-none}"
echo ""

# ------------------------------------------------------------------------------
# Rollback: move traffic only, nothing is rebuilt
# ------------------------------------------------------------------------------
if [ "$MODE" = "rollback" ]; then
    mapfile -t REVISIONS < <(list_revisions)
    AUTO_TARGET=false
    if [ -z "$ROLLBACK_TARGET" ]; then
        AUTO_TARGET=true
        for i in "${!REVISIONS[@]}"; do
            if [ "${REVISIONS[$i]}" = "$PREVIOUS_REVISION" ]; then
                ROLLBACK_TARGET="${REVISIONS[$((i + 1))]:-}"
                break
            fi
        done
    fi

    echo "Most recent revisions (newest first):"
    printf '   %s\n' "${REVISIONS[@]:0:5}"
    echo ""

    if [ -z "$ROLLBACK_TARGET" ]; then
        echo "❌ No older revision found. Pass one explicitly: --rollback <revision>"
        exit 1
    fi
    if ! printf '%s\n' "${REVISIONS[@]}" | grep -qx "$ROLLBACK_TARGET"; then
        echo "❌ Unknown revision: $ROLLBACK_TARGET"
        exit 1
    fi
    if [ "$ROLLBACK_TARGET" = "$PREVIOUS_REVISION" ]; then
        echo "ℹ️  $ROLLBACK_TARGET already serves the traffic. Nothing to do."
        exit 0
    fi

    if [ "$AUTO_TARGET" = true ]; then
        echo "⚠️  $ROLLBACK_TARGET may be a test revision that was never promoted: check the list above."
    fi
    confirm "Send 100% of traffic to $ROLLBACK_TARGET?"
    gcloud run services update-traffic "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" \
        --to-revisions "$ROLLBACK_TARGET=100"

    echo ""
    echo "✅ ROLLBACK DONE: $ROLLBACK_TARGET now serves 100% of traffic."
    echo "   Undo with: $0 --rollback $PREVIOUS_REVISION"
    print_links "$(service_url)"
    exit 0
fi

# ------------------------------------------------------------------------------
# Deployment (prod or test)
# ------------------------------------------------------------------------------
echo "  - Instances min/max    : 0 (0 € when idle) / 2"
echo "  - Memory               : 1 GiB (Free Tier)"
if [ "$MODE" = "test" ]; then
    echo "  - Traffic              : 0% (reachable only through the '$TEST_TAG' URL)"
    echo ""
    echo "⚠️  The test revision uses the PRODUCTION Firestore data and secrets."
fi
echo ""
confirm "Deploy to this project?"

DEPLOY_ARGS=(
    --source .
    "${GCLOUD_TARGET[@]}"
    --platform managed
    --allow-unauthenticated
    --memory 1Gi
    --cpu 1
    --min-instances 0
    --max-instances 2
    --timeout 300
)
if [ "$MODE" = "test" ]; then
    DEPLOY_ARGS+=(--no-traffic --tag "$TEST_TAG")
fi

echo ""
echo "📦 Uploading source and building the image (Cloud Build)..."
echo ""
gcloud run deploy "$SERVICE_NAME" "${DEPLOY_ARGS[@]}"

NEW_REVISION=$(list_revisions | head -n 1)

echo ""
echo "=============================================================================="
if [ "$MODE" = "test" ]; then
    echo "✅ TEST REVISION DEPLOYED: $NEW_REVISION (0% of traffic)"
    echo "=============================================================================="
    print_links "$(tagged_url "$TEST_TAG")"
    echo ""
    echo "▶️  Promote it to production (no rebuild):"
    echo "   gcloud run services update-traffic $SERVICE_NAME --project $CURRENT_PROJECT --region $REGION --to-tags $TEST_TAG=100"
    echo ""
    echo "ℹ️  If sign-in fails on this URL, add its domain to Firebase Authentication > Authorized domains."
else
    # A previous rollback pins traffic to a fixed revision: make sure the new one serves it
    gcloud run services update-traffic "$SERVICE_NAME" "${GCLOUD_TARGET[@]}" --to-latest > /dev/null
    echo "✅ DEPLOYED TO PRODUCTION: $NEW_REVISION (100% of traffic)"
    echo "=============================================================================="
    URL=$(service_url)
    print_links "$URL"
    echo ""
    echo "🔔 HelloAsso webhook URL: $URL/webhooks/helloasso"
    if [ -n "$PREVIOUS_REVISION" ]; then
        echo ""
        echo "↩️  Roll back with: $0 --rollback $PREVIOUS_REVISION"
    fi
fi
echo "=============================================================================="
