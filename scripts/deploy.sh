#!/usr/bin/env bash
# Deploy the committed HEAD to Cloud Run and prove it answers.
#   PROJECT=<gcp-project-id> [REGION=europe-west1] [SERVICE=night-shift] \
#     [STATE_BUCKET=<PROJECT>-state] [MIN_INSTANCES=0] [DEPLOY_AS_SELF=1] [PRODUCER_TOKEN=...] [CONVERSE_AGENT_ID=...] scripts/deploy.sh
# A rehearsal deploys SERVICE=night-shift-staging, whose store sits under its own prefix.
# One-time GCP setup: scripts/bootstrap.sh. Rollback: route traffic to the previous revision
# (gcloud run services update-traffic SERVICE --to-revisions REV=100).
set -euo pipefail

: "${PROJECT:?set PROJECT to the GCP project id}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-night-shift}"
STATE_BUCKET="${STATE_BUCKET:-$PROJECT-state}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"  # set 1 for a demo: no cold start
# Required secrets: each mounts as its upper-cased name (mubit-api-key is MUBIT_API_KEY),
# and scripts/bootstrap.sh creates and grants exactly these.
SECRETS="mubit-api-key elevenlabs-api-key"
OPTIONAL_SECRETS="converse-llm-secret"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "deploy: the working tree is dirty; commit first so the commit label names what ships" >&2
  exit 1
fi
COMMIT="$(git rev-parse --short=12 HEAD)"

# Every gcloud call below runs as the deployer scripts/bootstrap.sh made, never as you: its roles
# bound what a deploy can change. DEPLOY_AS_SELF=1 is the one opt-out, said out loud.
unset CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT  # only this script decides who deploys
# The backup ElevenLabs keys, comma-separated, are a pinned version of the same secret (no new
# secret, so no new IAM grant); core/voice.py tries them once the main key's quota is gone.
# ELEVENLABS_FALLBACK_VERSION=none mounts none. A missing version stops the deploy here rather
# than ship a revision that can't start. This check reads only the version's metadata, as you:
# the deployer has no Secret Manager role.
ELEVENLABS_FALLBACK_VERSION="${ELEVENLABS_FALLBACK_VERSION:-4}"
if [[ "$ELEVENLABS_FALLBACK_VERSION" != none ]]; then
  [[ "$ELEVENLABS_FALLBACK_VERSION" =~ ^[0-9]+$ ]] || { echo "deploy: ELEVENLABS_FALLBACK_VERSION must be a version number or none" >&2; exit 1; }
  if ! gcloud secrets versions describe "$ELEVENLABS_FALLBACK_VERSION" --secret elevenlabs-api-key \
    --project "$PROJECT" >/dev/null; then
    echo "deploy: elevenlabs-api-key has no version $ELEVENLABS_FALLBACK_VERSION; add the backup keys as it, or deploy with ELEVENLABS_FALLBACK_VERSION=none" >&2
    exit 1
  fi
fi
if [[ "${DEPLOY_AS_SELF:-}" == 1 ]]; then
  echo "deploy: deploying as $(gcloud config get-value account), not the deployer"
else
  DEPLOYER="deployer@$PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$DEPLOYER" --project "$PROJECT" >/dev/null 2>&1; then
    echo "deploy: no $DEPLOYER, or you cannot see it; run \`make bootstrap\` once for $PROJECT (scripts/bootstrap.sh)" >&2
    exit 1
  fi
  export CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT="$DEPLOYER"
fi
MOUNTS="$(for s in $SECRETS; do printf '%s=%s:latest,' "$(tr 'a-z-' 'A-Z_' <<<"$s")" "$s"; done)"
# The owner's key, a pinned version of the same secret (no new secret, so no new IAM grant): the
# commentator moves to it if the demo key above runs out of credit (402).
MUBIT_FALLBACK_VERSION="${MUBIT_FALLBACK_VERSION:-3}"
[[ "$MUBIT_FALLBACK_VERSION" =~ ^[0-9]+$ ]] || { echo "deploy: MUBIT_FALLBACK_VERSION must be a version number" >&2; exit 1; }
MOUNTS+="MUBIT_FALLBACK_KEY=mubit-api-key:$MUBIT_FALLBACK_VERSION,"
if [[ "$ELEVENLABS_FALLBACK_VERSION" != none ]]; then
  MOUNTS+="ELEVENLABS_API_KEY_FALLBACKS=elevenlabs-api-key:$ELEVENLABS_FALLBACK_VERSION,"
fi
if [[ -n "${CONVERSE_AGENT_ID:-}" ]]; then
  MOUNTS+="CONVERSE_LLM_SECRET=converse-llm-secret:latest,"
fi

# The voice picks (docs/voice.md): VOICE_<SPORT>, VOICE_MODEL_<SPORT> and VOICE_LABEL_<SPORT>, from the environment or
# .env, go to Cloud Run only when set, so an unset one keeps the code default. .env is never
# sourced: only VOICE_* lines are read from it, so no key can ride along. Vars are split on "@"
# (gcloud's ^@^ escape), which no value may hold, so a label can have commas.
VOICE_ENV=""
# The live site runs on a separate demo key whose app must not train on these lines. The owner's
# key trains, from scripts/replay_matches.py. MUBIT_RECORD=on make deploy records live lines again.
MUBIT_RECORD="${MUBIT_RECORD:-off}"
[[ "$MUBIT_RECORD" =~ ^(on|off)$ ]] || { echo "deploy: MUBIT_RECORD must be on or off" >&2; exit 1; }
# The producer token (#232) locks POST /lines/{id}/fix. --set-env-vars replaces every var, so a token
# set on the service by hand would go at the next deploy: it comes from the deploy's environment
# (never .env), and unset leaves fixes open. No "@", which would split the list.
PRODUCER_TOKEN="${PRODUCER_TOKEN:-}"
# Talk to the commentator (#380). The bearer is provisioned through Secret Manager by
# scripts/bootstrap.sh; only its agent id is an ordinary environment variable. With no agent id,
# the secret isn't mounted and the Talk button stays off.
CONVERSE_AGENT_ID="${CONVERSE_AGENT_ID:-}"
if [[ ! "$CONVERSE_AGENT_ID" =~ ^[A-Za-z0-9_.~+/=-]*$ ]]; then
  echo "deploy: CONVERSE_AGENT_ID may hold only letters, digits and _.~+/=-" >&2
  exit 1
fi
if [[ -n "$PRODUCER_TOKEN" && ! "$PRODUCER_TOKEN" =~ ^[A-Za-z0-9_.~+/=-]+$ ]]; then
  echo "deploy: PRODUCER_TOKEN may hold only letters, digits and _.~+/=-" >&2  # never echo the value
  exit 1
fi
for name in $( (compgen -e; [[ -f .env ]] && sed -n 's/^\(VOICE_[A-Z0-9_]*\)=.*/\1/p' .env) \
  | grep -E '^VOICE_[A-Z0-9_]+$' | sort -u); do
  value="${!name:-}"
  if [[ -z "$value" && -f .env ]]; then
    value="$(sed -n "s/^$name=//p" .env | tail -1 | tr -d "\"'")"
  fi
  [[ -z "$value" ]] && continue
  if [[ "$name" == VOICE_LABEL_* ]]; then
    allowed='^[A-Za-z0-9_., -]+$'  # a name the page shows: "Raju, Cricket Commentator"
  else
    allowed='^[A-Za-z0-9_.-]+$'
  fi
  if [[ ! "$value" =~ $allowed ]]; then
    echo "deploy: $name must be a voice id, model name or label ($allowed)" >&2
    exit 1
  fi
  VOICE_ENV+="@$name=$value"
done

# The store is JSON-lines objects in GCS under gs://STATE_BUCKET/SERVICE/ (core/store.py), so it
# survives a redeploy. A replay lives in the process that started it, so the stream must reach
# the same instance: one instance (IDEA.md ceiling: one server process), CPU kept on between
# requests so a replay runs while nobody is streaming, and an hour per request for a whole match.
# 1 GiB: replays and their audio live in memory (capped in core/app.py and core/voice.py).
gcloud run deploy "$SERVICE" --source . --region "$REGION" --project "$PROJECT" \
  --allow-unauthenticated \
  --set-secrets "${MOUNTS%,}" \
  --set-env-vars "^@^MODE=cloud@STORE_URL=gs://$STATE_BUCKET/$SERVICE@MUBIT_RECORD=$MUBIT_RECORD$VOICE_ENV${PRODUCER_TOKEN:+@PRODUCER_TOKEN=$PRODUCER_TOKEN}${CONVERSE_AGENT_ID:+@CONVERSE_AGENT_ID=$CONVERSE_AGENT_ID}" \
  --labels "commit=$COMMIT" \
  --min-instances "$MIN_INSTANCES" \
  --max-instances 1 \
  --memory 1Gi \
  --no-cpu-throttling \
  --timeout 3600 \
  --quiet

RELEASE="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format 'value(status.url,status.latestReadyRevisionName)')"
URL="${RELEASE%%$'\t'*}"
# The release record, one line: what is live, by commit, revision and URL.
echo "release: commit=$COMMIT revision=${RELEASE#*$'\t'} url=$URL"
curl -fsS --max-time 30 "$URL/health"
echo

# The live smoke on the real URL: one sample replay streams moments and lines, and the service's
# store grows by the lines it streamed (core/smoke.py live).
BASE_URL="$URL" timeout 300 uv run python -m core.smoke
