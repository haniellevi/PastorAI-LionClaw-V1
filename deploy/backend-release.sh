#!/usr/bin/env bash
# Run on the VPS only after a separately authorized database release.
set -Eeuo pipefail
BACKEND_RELEASE_SAFETY_VERSION=3

configuration=.env
health_port=8000
if [[ "${BACKEND_RELEASE_TEST_MODE:-}" == 1 ]]; then
  configuration=${BACKEND_RELEASE_TEST_CONFIG:?}
  [[ "$configuration" == *.fixture && "$configuration" != */* ]] || exit 2
  # Synthetic rehearsals publish their own loopback port; never in production.
  health_port=${BACKEND_RELEASE_TEST_PORT:-8000}
  [[ "$health_port" =~ ^[1-9][0-9]{3,4}$ ]] || exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Use the candidate's own migration selection rule. A missing ledger entry
# blocks the release even when /health and /ready would still answer 200.
migration_manifest() {
  python3 - "$1" <<'MANIFEST'
import json
from pathlib import Path
import re
import runpy
import sys
backend = Path(sys.argv[1]).resolve()
files = runpy.run_path(str(backend / "scripts/migrate.py"))["migration_files"](backend / "migrations")
if (
    not isinstance(files, list)
    or not files
    or not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]+\.sql", name) for name in files)
    or len(files) != len(set(files))
):
    raise SystemExit("release has no valid active migration manifest")
print(json.dumps(files, separators=(",", ":")))
MANIFEST
}
expected_migrations=$(migration_manifest "$script_dir/../backend")
if [[ "${1:-}" == "--dry-run" ]]; then
  EXPECTED_MIGRATIONS="$expected_migrations" \
    "${BACKEND_RELEASE_PYTHON:-python3}" "$script_dir/check_backend_schema.py"
  echo "dry-run OK: schema ready; build and restart were not run"
  exit 0
fi

release_sha=${1:-}
if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "expected an exact 40-character release SHA" >&2
  exit 2
fi

if [[ "${BACKEND_RELEASE_TEST_MODE:-}" == 1 ]]; then
  release_root="${BACKEND_RELEASE_TEST_ROOT:?}/releases"
  active_link="$BACKEND_RELEASE_TEST_ROOT/current"
else
  release_root=/opt/pastorai-releases
  active_link=/opt/pastorai-current
fi
# Every release mode shares the same lock through activation, recovery and
# cleanup. Resolve the active release only after entering this critical section.
command -v flock >/dev/null || { echo "release lock unavailable" >&2; exit 1; }
[[ -d "$release_root" && ! -L "$release_root/.backend-release.lock" ]] || {
  echo "release lock path unavailable" >&2; exit 1;
}
exec 9>"$release_root/.backend-release.lock"
flock -n 9 || { echo "another backend release is in progress" >&2; exit 1; }
candidate="$release_root/$release_sha"
active=$(readlink -f -- "$active_link")
if [[ "$(readlink -f -- "$candidate")" != "$candidate" || -L "$candidate/deploy" ||
      -e "$candidate/deploy/$configuration" || -L "$candidate/deploy/$configuration" ]]; then
  echo "candidate path is aliased or contains an existing private configuration" >&2
  exit 1
fi
if [[ "$active" != "$release_root/"* || ! -d "$active/deploy" || ! -d "$candidate/deploy" || "$active" == "$candidate" ]]; then
  echo "release paths are missing, outside the release root, or already active" >&2
  exit 1
fi
active_release_sha=${active##*/}
if [[ ! "$active_release_sha" =~ ^[0-9a-f]{40}$ || "$active" != "$release_root/$active_release_sha" ]]; then
  echo "active release revision unverifiable; exact SHA required for rollback" >&2
  exit 1
fi
if [[ ! -f "$active/deploy/$configuration" || ! -f "$candidate/deploy/check_backend_schema.py" ]]; then
  echo "active configuration or candidate schema check is missing" >&2
  exit 1
fi
if [[ ! -f "$active/deploy/check_backend_schema.py" ]] ||
   ! previous_migrations=$(migration_manifest "$active/backend"); then
  echo "rollback schema compatibility unverifiable before release; previous checker or manifest unavailable" >&2
  exit 1
fi

# Permanent topology is adopted only from the active release, never from the
# candidate tarball. A project marker without a valid contract refuses; an
# install with neither keeps the compatible single-project path.
topology_tool="$script_dir/release_topology.py"
topology_contract=
topology_project=
topology_dir=
topology_overlay=
topology_persisted=0
for name in release-topology.json compose-project.name; do
  if [[ -e "$candidate/deploy/$name" || -L "$candidate/deploy/$name" ]]; then
    echo "candidate contains an untrusted release topology" >&2
    exit 1
  fi
done
if [[ -e "$candidate/deploy/docker-compose.override.yml" || -L "$candidate/deploy/docker-compose.override.yml" ]]; then
  echo "candidate contains an existing Compose override" >&2
  exit 1
fi
active_marker="$active/deploy/compose-project.name"
if [[ -e "$active/deploy/release-topology.json" || -L "$active/deploy/release-topology.json" ||
      -e "$active_marker" || -L "$active_marker" ]]; then
  marker=()
  [[ ! -e "$active_marker" && ! -L "$active_marker" ]] || marker=(--marker "$active_marker")
  if [[ -L "$active/deploy" ]] ||
     ! topology_project=$(python3 -I "$topology_tool" validate \
       --contract "$active/deploy/release-topology.json" "${marker[@]}"); then
    echo "active release topology missing or invalid; release refused before effects" >&2
    exit 1
  fi
  topology_contract="$active/deploy/release-topology.json"
fi

export PASTORAI_ENV_FILE="$configuration"
services=(backend queue-worker cron-worker broadcast-worker)
restart_started=0
candidate_configuration_needed=0
checker_override=
image_override_candidate=
image_override_previous=
release_image=${RELEASE_IMAGE_REF:-}
pinned_override_path="$candidate/deploy/docker-compose.override.yml"
pinned_override_created=0
candidate_image_id=
previous_image_id=
compatibility_bundle=${RELEASE_SCHEMA_BUNDLE:-}
rollback_manifest=$previous_migrations
if [[ -n "$compatibility_bundle" ]]; then
  [[ "$compatibility_bundle" == /*.json && ! -L "$compatibility_bundle" &&
     "${RELEASE_SCHEMA_BUNDLE_SHA256:-}" =~ ^[0-9a-f]{64}$ &&
     -f "$candidate/deploy/emit_schema_check.py" && -f "$candidate/deploy/schema_compatibility.py" ]] || {
    echo "reviewed nominal compatibility bundle unavailable" >&2
    exit 1
  }
  rollback_manifest=$expected_migrations
fi

# Optional artifact promotion. No image tags or on-target rebuild are used.
compose() {
  local overlay=
  local -a files=() extra=()
  # Pins exist only for digest promotion or an adopted topology.
  case "$PWD" in
    "$candidate/deploy") overlay=$image_override_candidate ;;
    "$active/deploy") overlay=$image_override_previous ;;
  esac
  # Keep explicit checker files in order, then pin only image/revision fields.
  while [[ "${1:-}" == -f ]]; do extra+=(-f "$2"); shift 2; done
  [[ -z "$overlay" ]] || extra+=(-f "$overlay")
  if [[ -n "$topology_overlay" ]]; then
    # Explicit project and files on every call: base -> topology -> checker -> pin.
    files=(-p "$topology_project" -f docker-compose.yml -f "$topology_overlay" "${extra[@]}")
  elif (( ${#extra[@]} )); then
    files=(-f docker-compose.yml "${extra[@]}")
  fi
  docker compose "${files[@]}" "$@"
}

# Docker state of the adopted topology (no-op on the compatible path).
topology_guard() {
  [[ -n "$topology_contract" ]] || return 0
  local -a revision=()
  if [[ "$1" != replace ]]; then
    revision=(--revision "${2:-$release_sha}")
    [[ -n "${2:-}" || "$PWD" != "$active/deploy" ]] || revision=(--revision "$active_release_sha")
  fi
  python3 -I "$topology_tool" guard --contract "$topology_contract" --phase "$1" "${revision[@]}"
}

require_local_docker() {
  [[ -z "${DOCKER_HOST:-}${DOCKER_CONTEXT:-}${DOCKER_TLS_VERIFY:-}${DOCKER_CERT_PATH:-}" ]] || {
    echo "Docker endpoint override refused for image promotion or adopted topology" >&2; return 1;
  }
  local endpoint
  endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}') || return 1
  [[ "$endpoint" == unix:///var/run/docker.sock || "$endpoint" =~ ^unix:///run/user/[0-9]+/docker.sock$ ]] || {
    echo "local Docker socket required for image promotion or adopted topology" >&2; return 1;
  }
}

image_revision() {
  docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1"
}
write_pin() {
  python3 - "$1" "$2" "$3" <<'PIN'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'services': {
    name: {'image': sys.argv[2], 'environment': {'PASTORAI_RELEASE_SHA': sys.argv[3]}}
    for name in ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
}}))
PIN
}
# Digest promotion and every adopted topology record the predecessor's verified
# immutable image ID before any pull or build: recovery reuses that ID and
# never rebuilds the previous tree (an initial layout carries no build source).
prepare_pinned_images() {
  [[ -n "$release_image" || -n "$topology_contract" ]] || return 0
  if [[ -n "$release_image" ]]; then
    [[ ! -e "$pinned_override_path" && ! -L "$pinned_override_path" ]] || {
      echo "candidate contains an existing Compose override" >&2; return 1;
    }
    [[ "$release_image" =~ ^ghcr\.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:[0-9a-f]{64}$ ]] || {
      echo "nominal backend image digest required" >&2; return 1;
    }
  fi
  [[ "$(readlink -f -- "$active_link")" == "$active" ]] || {
    echo "active release changed during preflight" >&2; return 1;
  }
  require_local_docker || return 1
  local container image service
  cd -- "$active/deploy"
  for service in "${services[@]}"; do
    container=$(compose ps -aq "$service") || return 1
    [[ -n "$container" && "$container" != *$'\n'* ]] || return 1
    image=$(docker inspect --format '{{.Image}}' "$container") || return 1
    [[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    if [[ -z "$previous_image_id" ]]; then previous_image_id=$image; fi
    [[ "$image" == "$previous_image_id" ]] || {
      echo "previous consumers have inconsistent image identities" >&2; return 1;
    }
  done
  [[ "$(image_revision "$previous_image_id")" == "$active_release_sha" ]] || {
    echo "previous image revision unverifiable" >&2; return 1;
  }
  retain_image "$previous_image_id" "$active_release_sha" || return 1
  image_override_previous=$(mktemp /tmp/backend-previous-image.XXXXXXXX.json) || return 1
  write_pin "$image_override_previous" "$previous_image_id" "$active_release_sha" || return 1
  [[ -n "$release_image" ]] || return 0
  docker pull "$release_image" >/dev/null || return 1
  [[ "$(image_revision "$release_image")" == "$release_sha" ]] || {
    echo "candidate image revision mismatch" >&2; return 1;
  }
  candidate_image_id=$(docker image inspect --format '{{.Id}}' "$release_image") || return 1
  [[ "$candidate_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  image_override_candidate=$(mktemp /tmp/backend-candidate-image.XXXXXXXX.json) || return 1
  write_pin "$image_override_candidate" "$release_image" "$release_sha"
}
# With the containerd image store an image whose last tag moves (the next build
# retags the mutable build tag) is no longer usable by ID. An adopted topology
# therefore keeps a per-revision local tag on every image it may recover to.
retain_image() {
  [[ -n "$topology_contract" ]] || return 0
  local tag
  tag=$(compose config --format json --no-env-resolution |
        python3 -I "$topology_tool" image-name --contract "$topology_contract") || return 1
  docker image tag "$1" "${tag%:*}-release:$2" || return 1
  [[ "$(docker image inspect --format '{{.Id}}' "${tag%:*}-release:$2")" == "$1" ]] || {
    echo "retained image reference unverifiable" >&2; return 1;
  }
}
# Built candidate of an adopted topology: pin the exact local ID just built,
# after verifying its revision label, so no mutable tag is used from here on.
pin_built_candidate() {
  local tag
  tag=$(compose config --format json --no-env-resolution |
        python3 -I "$topology_tool" image-name --contract "$topology_contract") || return 1
  candidate_image_id=$(docker image inspect --format '{{.Id}}' "$tag") || return 1
  [[ "$candidate_image_id" =~ ^sha256:[0-9a-f]{64}$ &&
     "$(image_revision "$candidate_image_id")" == "$release_sha" ]] || {
    echo "built candidate image revision unverifiable" >&2; return 1;
  }
  retain_image "$candidate_image_id" "$release_sha" || return 1
  image_override_candidate=$(mktemp /tmp/backend-candidate-image.XXXXXXXX.json) || return 1
  write_pin "$image_override_candidate" "$candidate_image_id" "$release_sha"
}
prepare_release_image() {
  if [[ "$PWD" == "$active/deploy" && -n "$previous_image_id" ]]; then
    [[ "$(image_revision "$previous_image_id")" == "$active_release_sha" ]]
  elif [[ -n "$release_image" ]]; then
    [[ "$(image_revision "$release_image")" == "$release_sha" ]]
  else
    local sha=$release_sha
    [[ "$PWD" != "$active/deploy" ]] || sha=$active_release_sha
    compose build --build-arg "PASTORAI_RELEASE_SHA=$sha" backend || return 1
    [[ -z "$topology_contract" ]] || pin_built_candidate
  fi
}

emit_compatibility_check() {
  local -a args=(--bundle "$compatibility_bundle" --sha256 "$RELEASE_SCHEMA_BUNDLE_SHA256"
    --previous-sha "$active_release_sha" --candidate-sha "$release_sha"
    --previous-migrations "$previous_migrations" --candidate-migrations "$expected_migrations")
  [[ -z "${1:-}" ]] || args+=(--legacy-checker "$1")
  python3 "$candidate/deploy/emit_schema_check.py" "${args[@]}"
}

check_compose_gates() {
  if [[ -n "$topology_contract" ]]; then
    # Topology model without resolving env_file: no private value is read here.
    compose "$@" config --format json --no-env-resolution |
      python3 -I "$topology_tool" check-config --contract "$topology_contract" || return 1
  fi
  compose "$@" config --format json | python3 -c '
import json
import sys

try:
    services = json.load(sys.stdin)["services"]
except (KeyError, TypeError, ValueError):
    print("effective Compose gates unverifiable", file=sys.stderr)
    sys.exit(1)

expected = {
    "ALLOW_REAL_SENDS": "false",
    "ASAAS_BILLING_ENABLED": "false",
    "BREVO_SEND_MODE": "off",
    "BROADCAST_ASYNC_ENABLED": "false",
}
for name in ("backend", "queue-worker", "cron-worker", "broadcast-worker"):
    environment = services.get(name, {}).get("environment")
    if not isinstance(environment, dict) or any(
        environment.get(key) != value for key, value in expected.items()
    ):
        print(f"effective Compose gates open or unverifiable: {name}", file=sys.stderr)
        sys.exit(1)
'
}

check_external_gates() {
  local service
  for service in "${services[@]}"; do
    if ! compose exec -T "$service" sh -c '
      [ "${ALLOW_REAL_SENDS+x}" = x ] && [ "$ALLOW_REAL_SENDS" = false ] &&
      [ "${ASAAS_BILLING_ENABLED+x}" = x ] && [ "$ASAAS_BILLING_ENABLED" = false ] &&
      [ "${BREVO_SEND_MODE+x}" = x ] && [ "$BREVO_SEND_MODE" = off ] &&
      [ "${BROADCAST_ASYNC_ENABLED+x}" = x ] && [ "$BROADCAST_ASYNC_ENABLED" = false ]
    ' >/dev/null; then
      echo "external-effect gates open or unverifiable: $service" >&2
      return 1
    fi
  done
}

# Containers are inspected while stopped, before any application entrypoint.
inspect_stopped_gates() {
  local service container
  for service in "$@"; do
    container=$(compose ps -aq "$service") || return 1
    [[ -n "$container" && "$container" != *$'\n'* ]] || return 1
    docker inspect --format '{{json .Config.Env}}' "$container" | python3 -c '
import json, sys
try:
    entries = json.load(sys.stdin)
    env = dict(item.split("=", 1) for item in entries)
    expected = {"ALLOW_REAL_SENDS": "false", "ASAAS_BILLING_ENABLED": "false",
                "BREVO_SEND_MODE": "off", "BROADCAST_ASYNC_ENABLED": "false"}
    if len(env) != len(entries) or not all(env.get(k) == v for k, v in expected.items()):
        raise ValueError("invalid gates")
except Exception:
    sys.exit("stopped container gates open or unverifiable")
' || return 1
    if [[ -n "$release_image" || -n "$topology_contract" ]]; then
      local expected=$candidate_image_id
      [[ "$PWD" != "$active/deploy" ]] || expected=$previous_image_id
      [[ "$(docker inspect --format '{{.Image}}' "$container")" == "$expected" ]] || {
        echo "stopped container image mismatch" >&2; return 1;
      }
    fi
  done
}

# Adopted topology: stop only IDs proven ours (contracted name for its own
# service, never a reserved legacy ID), whatever the network or dependency
# health, and verify each exit. A stranger member is never touched: the
# release then stops in human recovery with configuration and topology kept.
contain_owned() {
  local owned status=0 id
  local -a ids=()
  owned=$(python3 -I "$topology_tool" owned --contract "$topology_contract") || status=$?
  (( status == 0 || status == 3 )) || { echo "consumer containment unverifiable" >&2; return 1; }
  [[ -z "$owned" ]] || mapfile -t ids <<< "$owned"
  if (( ${#ids[@]} )); then
    docker stop "${ids[@]}" >/dev/null || return 1
  fi
  for id in "${ids[@]}"; do
    [[ "$(docker inspect --format '{{.State.Running}}' "$id")" == false ]] || {
      echo "consumer containment unverifiable" >&2; return 1;
    }
  done
  (( status == 0 )) || {
    echo "stranger project member left untouched; human recovery required" >&2; return 1;
  }
}

contain_consumers() {
  # Explicit status: a bare return inside the ERR trap reports the trapped failure.
  if [[ -n "$topology_contract" ]]; then contain_owned; return $?; fi
  compose stop "${services[@]}" || return 1
  [[ -n "$release_image" ]] || return 0
  local service container
  for service in "${services[@]}"; do
    container=$(compose ps -aq "$service") || return 1
    [[ -n "$container" ]] || continue
    [[ "$container" != *$'\n'* ]] || return 1
    [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == false ]] || {
      echo "consumer containment unverifiable" >&2; return 1;
    }
  done
}

create_and_start() {
  topology_guard replace || return 1
  compose up --no-start --no-build --no-deps --pull never --force-recreate "${services[@]}" || return 1
  inspect_stopped_gates "${services[@]}" || return 1
  topology_guard created || return 1
  compose start --wait --wait-timeout 180 "${services[@]}"
}

# A stopped backend is temporarily dedicated to the previous release's checker.
# No application command or restart policy may run until its exit is verified.
check_previous_schema() {
  local container checker_status
  checker_override=$(mktemp /tmp/backend-rollback-compose.XXXXXXXX.json) || return 1
  python3 - "$checker_override" "$1" <<'OVERRIDE'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"services": {"backend": {
    "entrypoint": ["python", "/tmp/backend-rollback-schema.py"],
    "command": [],
    "restart": "no",
    "healthcheck": {"disable": True},
    "environment": {"EXPECTED_MIGRATIONS": sys.argv[2]},
}}}))
OVERRIDE
  [[ $? == 0 ]] || return 1
  local -a checker_compose=(-f "$checker_override")
  check_compose_gates "${checker_compose[@]}" || return 1
  topology_guard replace || return 1
  compose "${checker_compose[@]}" up --no-start --no-build --no-deps --pull never --force-recreate backend || return 1
  inspect_stopped_gates backend || return 1
  topology_guard checker || return 1
  container=$(compose ps -aq backend) || return 1
  [[ -n "$container" && "$container" != *$'\n'* ]] || return 1
  if [[ -n "$compatibility_bundle" ]]; then
    local emitted
    emitted=$(mktemp /tmp/backend-schema-verified.XXXXXXXX.py) || return 1
    if ! emit_compatibility_check "$active/deploy/check_backend_schema.py" > "$emitted"; then
      rm -f -- "$emitted"
      return 1
    fi
    chmod 644 "$emitted" # reviewed schema metadata/code, never runtime secrets
    docker cp "$emitted" "$container:/tmp/backend-rollback-schema.py" || { rm -f -- "$emitted"; return 1; }
    rm -f -- "$emitted"
  else
    docker cp check_backend_schema.py "$container:/tmp/backend-rollback-schema.py" || return 1
  fi
  compose "${checker_compose[@]}" start backend || return 1
  checker_status=$(timeout --signal=TERM --kill-after=5s 180s docker wait "$container") || return 1
  [[ "$checker_status" == 0 ]] || return 1
  rm -f -- "$checker_override"
  checker_override=
}

# Supported floor, not a claim about the first historical flag implementation.
check_compose_capabilities() {
  local version help
  command -v timeout >/dev/null || {
    echo "timeout command required for bounded rollback schema check" >&2
    return 1
  }
  timeout --signal=TERM --kill-after=5s 1s true >/dev/null 2>&1 || {
    echo "timeout options unavailable; release blocked before effects" >&2
    return 1
  }
  version=$(compose version --short) || return 1
  if [[ ! "$version" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] ||
     (( 10#${BASH_REMATCH[1]} < 5 )); then
    echo "Docker Compose >= 5.0.0 required" >&2
    return 1
  fi
  help=$(compose start --help) || return 1
  grep -Eq -- '(^|[[:space:]])--wait([[:space:]]|$)' <<< "$help" &&
    grep -Eq -- '(^|[[:space:]])--wait-timeout([[:space:]]|$)' <<< "$help" || {
      echo "Compose start wait capabilities unavailable" >&2
      return 1
    }
}

cleanup() {
  local status=$?
  if (( ! candidate_configuration_needed )) && [[ "$(readlink -f -- "$active_link")" != "$candidate" ]]; then
    rm -f -- "$candidate/deploy/$configuration"
  fi
  [[ -z "$checker_override" ]] || rm -f -- "$checker_override"
  [[ -z "$image_override_candidate" ]] || rm -f -- "$image_override_candidate"
  [[ -z "$image_override_previous" ]] || rm -f -- "$image_override_previous"
  # Failed containment of an adopted topology keeps its public topology files
  # next to the preserved configuration for human recovery.
  local keep_topology=0
  if [[ -n "$topology_contract" ]] && (( candidate_configuration_needed )); then keep_topology=1; fi
  if (( pinned_override_created && ! keep_topology )) && [[ "$(readlink -f -- "$active_link")" != "$candidate" ]]; then
    rm -f -- "$pinned_override_path"
  fi
  if (( topology_persisted && ! keep_topology )) && [[ "$(readlink -f -- "$active_link")" != "$candidate" ]]; then
    rm -f -- "$candidate/deploy/release-topology.json"
  fi
  [[ -z "$topology_dir" ]] || rm -rf -- "$topology_dir"
  rm -f -- "$active_link.next.$$"
  exit "$status"
}
trap cleanup EXIT
rollback() {
  local original_status=${1:-$?} previous_migrations
  trap - ERR
  trap '' INT TERM
  if [[ "$(readlink -f -- "$active_link")" == "$candidate" ]]; then
    echo "release already activated; preserve healthy active containers and configuration" >&2
    exit "$original_status"
  fi
  if (( restart_started )); then
    # Stop first: a rejected rollback must never leave candidate workers running.
    contain_consumers || {
      candidate_configuration_needed=1
      echo "containment failed; preserve candidate configuration for human recovery" >&2
      exit "$original_status"
    }
    cd -- "$active/deploy"
    if [[ ! -f check_backend_schema.py ]] ||
       ! previous_migrations=$(migration_manifest "$active/backend"); then
      echo "rollback schema compatibility unverifiable; keep gates closed and use a reviewed forward fix" >&2
      exit "$original_status"
    fi
    if ! check_compose_gates ||
       ! prepare_release_image ||
       ! check_previous_schema "$rollback_manifest" ||
       ! create_and_start ||
       ! check_external_gates ||
       ! curl -fsS --max-time 5 http://127.0.0.1:$health_port/health >/dev/null ||
       ! curl -fsS --max-time 5 http://127.0.0.1:$health_port/ready >/dev/null; then
      contain_consumers || {
        echo "rollback containment failed; preserve previous configuration and require human recovery" >&2
      }
      echo "rollback of code is unhealthy or schema incompatible; keep gates closed and use a reviewed forward fix" >&2
    fi
  else
    echo "deploy stopped before restart; previous containers remain active" >&2
  fi
  exit "$original_status"
}
trap rollback ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

if [[ -n "$topology_contract" ]]; then
  topology_dir=$(mktemp -d /tmp/backend-topology.XXXXXXXX)
  python3 -I "$topology_tool" overlay --contract "$topology_contract" --out "$topology_dir/topology.yml"
  topology_overlay="$topology_dir/topology.yml"
fi

# Capability failure must leave the active services and configuration untouched.
check_compose_capabilities
if [[ -n "$topology_contract" ]]; then
  # True predecessor: the four services of the adopted project, nothing else.
  require_local_docker
  topology_guard predecessor "$active_release_sha"
fi
prepare_pinned_images

# Keep secrets on the VPS; never include them in the Git archive or logs.
cp -p -- "$active/deploy/$configuration" "$candidate/deploy/$configuration"
chmod 600 "$candidate/deploy/$configuration"
cd -- "$candidate/deploy"
compose config --quiet
check_compose_gates

# Check each release with its own manifest before replacing the active services.
# Both checkers query catalog metadata and the ledger in read-only transactions.
cd -- "$active/deploy"
check_compose_gates
check_external_gates
if [[ -n "$compatibility_bundle" ]]; then
  emit_compatibility_check | compose exec -T backend python -
fi
compose exec -T -e "EXPECTED_MIGRATIONS=$rollback_manifest" backend python - \
  < "$active/deploy/check_backend_schema.py"
compose exec -T -e "EXPECTED_MIGRATIONS=$expected_migrations" backend python - \
  < "$candidate/deploy/check_backend_schema.py"

cd -- "$candidate/deploy"
prepare_release_image
if [[ -n "$topology_contract" ]]; then
  # Before the first effect, once the candidate image ID is verified: the
  # candidate carries its own project/network/names and immutable pin, so a
  # contained failure leaves usable recovery files next to its configuration
  # (never the legacy project, never a mutable tag). Both paths were proven
  # absent before effects and are written exclusively (O_EXCL).
  [[ "$candidate_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
  pinned_override_created=1
  python3 -I "$topology_tool" overlay --contract "$topology_contract" \
    --image "${release_image:-$candidate_image_id}" --sha "$release_sha" --out "$pinned_override_path"
  topology_persisted=1
  python3 -I "$topology_tool" persist --contract "$topology_contract" --out "$candidate/deploy/release-topology.json"
fi
# Fresh ownership and readiness while the predecessor still serves.
topology_guard predecessor "$active_release_sha"
restart_started=1
if [[ -n "$release_image" ]]; then contain_consumers; fi
create_and_start
check_external_gates
curl -fsS --max-time 5 http://127.0.0.1:$health_port/health >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:$health_port/ready >/dev/null

# Persist the public pin for subsequent ordinary Compose maintenance, without
# modifying the private environment file. No mutable tag can reappear on up.
# With an adopted topology the override and the carried-forward contract were
# already written before the first effect.
if [[ -z "$topology_contract" && -n "$release_image" ]]; then
  [[ ! -e "$pinned_override_path" && ! -L "$pinned_override_path" ]]
  cp -- "$image_override_candidate" "$pinned_override_path"
  chmod 644 "$pinned_override_path"
  pinned_override_created=1
fi

# Only a healthy candidate becomes the stable release. The old tree remains
# available for code rollback; its database schema is never rolled back here.
ln -s -- "$candidate" "$active_link.next.$$"
mv -Tf -- "$active_link.next.$$" "$active_link"
trap - ERR
echo "backend release healthy: $release_sha"
