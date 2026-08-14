#!/usr/bin/env bash
#
# Copyright (C) 2024-present ScyllaDB
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.1
#
# Spin up a local SonarQube Community server (Docker) with the sonar-cxx plugin
# installed, for the ScyllaDB SonarQube POC.
#
#   https://github.com/SonarOpenCommunity/sonar-cxx
#
# All server configuration is injected through bind-mounted files under
# ./config and ./plugins, so you can switch checks on/off WITHOUT rebuilding or
# re-pulling anything:
#
#   config/sonar.properties   -> /opt/sonarqube/conf/sonar.properties   (server config)
#   plugins/*.jar             -> /opt/sonarqube/extensions/plugins/     (plugins)
#   config/disabled-rules.txt -> applied to the C++ quality profile by `provision`
#
# Usage:
#   ./sonarqube.sh up          # pull image, fetch sonar-cxx plugin, start server
#   ./sonarqube.sh wait        # block until the server API is UP
#   ./sonarqube.sh provision   # set admin password + disable rules listed in config/
#   ./sonarqube.sh status      # container + server health
#   ./sonarqube.sh logs        # follow container logs
#   ./sonarqube.sh restart     # restart (picks up edited config/sonar.properties)
#   ./sonarqube.sh down        # stop + remove the container (keeps data volumes)
#   ./sonarqube.sh destroy     # down + delete data/logs volumes (full reset)
#
# Everything is overridable via env vars (see the knobs block below), e.g.:
#   SONAR_PORT=9001 SONAR_IMAGE=sonarqube:2025.4-community ./sonarqube.sh up
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- knobs (all overridable via env) --------------------------------------
CONTAINER="${SONAR_CONTAINER:-scylla-sonarqube}"
# Default to the Community LTA line that sonar-cxx 2.3.0 is tested against
# (Community Build 25.8 / Server 2025.4 LTA). Pin a specific tag to reproduce.
IMAGE="${SONAR_IMAGE:-sonarqube:community}"
HTTP_PORT="${SONAR_PORT:-9000}"

# sonar-cxx plugin release (asset name carries a build number, hence 2.3.0.1496).
CXX_PLUGIN_TAG="${SONAR_CXX_TAG:-cxx-2.3.0}"
CXX_PLUGIN_JAR="${SONAR_CXX_JAR:-sonar-cxx-plugin-2.3.0.1496.jar}"
CXX_PLUGIN_URL="${SONAR_CXX_URL:-https://github.com/SonarOpenCommunity/sonar-cxx/releases/download/${CXX_PLUGIN_TAG}/${CXX_PLUGIN_JAR}}"

# Fresh SonarQube ships with admin/admin and forces a password change.
ADMIN_USER="${SONAR_ADMIN_USER:-admin}"
DEFAULT_ADMIN_PASSWORD="${SONAR_DEFAULT_ADMIN_PASSWORD:-admin}"
ADMIN_PASSWORD="${SONAR_ADMIN_PASSWORD:-scylla-sonar-admin}"

PLUGINS_DIR="$HERE/plugins"
CONFIG_DIR="$HERE/config"
SONAR_PROPERTIES="$CONFIG_DIR/sonar.properties"
DISABLED_RULES="$CONFIG_DIR/disabled-rules.txt"
CXX_LANG="${SONAR_CXX_LANG:-cxx}"
CXX_PROFILE_NAME="${SONAR_CXX_PROFILE:-scylla-cxx}"

DATA_VOL="${SONAR_DATA_VOL:-scylla_sonarqube_data}"
LOGS_VOL="${SONAR_LOGS_VOL:-scylla_sonarqube_logs}"

BASE_URL="http://localhost:${HTTP_PORT}"
WAIT_TIMEOUT="${SONAR_WAIT_TIMEOUT:-300}"   # seconds

log()  { printf '%s [sonarqube] %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required but not installed"; }

# ---------------------------------------------------------------------------
ensure_sysctl() {  # Elasticsearch (bundled in SonarQube) needs a high mmap count
    local cur
    cur="$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)"
    if (( cur < 524288 )); then
        log "vm.max_map_count=$cur is below the required 524288; trying to raise it"
        if sysctl -w vm.max_map_count=524288 >/dev/null 2>&1 \
           || sudo sysctl -w vm.max_map_count=524288 >/dev/null 2>&1; then
            log "raised vm.max_map_count to 524288 (add it to /etc/sysctl.conf to persist)"
        else
            log "WARNING: could not raise vm.max_map_count. The server may fail to start."
            log "         Run manually: sudo sysctl -w vm.max_map_count=524288"
        fi
    fi
}

fetch_plugin() {
    mkdir -p "$PLUGINS_DIR"
    local dest="$PLUGINS_DIR/$CXX_PLUGIN_JAR"
    if [[ -s "$dest" ]]; then
        log "sonar-cxx plugin already present: ${dest#$HERE/}"
        return 0
    fi
    log "downloading sonar-cxx plugin: $CXX_PLUGIN_URL"
    curl -fSL --retry 3 --retry-delay 2 -o "$dest.tmp" "$CXX_PLUGIN_URL" \
        || fail "failed to download sonar-cxx plugin from $CXX_PLUGIN_URL"
    mv -f "$dest.tmp" "$dest"
    log "installed plugin -> ${dest#$HERE/}"
}

container_exists() { docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; }
container_running() { docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; }

# ---------------------------------------------------------------------------
cmd_up() {
    need docker
    need curl
    [[ -f "$SONAR_PROPERTIES" ]] || fail "missing $SONAR_PROPERTIES"
    ensure_sysctl
    fetch_plugin

    if container_running; then
        log "container '$CONTAINER' is already running"
        return 0
    fi
    if container_exists; then
        log "starting existing container '$CONTAINER'"
        docker start "$CONTAINER" >/dev/null
        return 0
    fi

    log "starting SonarQube ($IMAGE) on ${BASE_URL}"
    docker run -d --name "$CONTAINER" \
        -p "${HTTP_PORT}:9000" \
        -v "${DATA_VOL}:/opt/sonarqube/data" \
        -v "${LOGS_VOL}:/opt/sonarqube/logs" \
        -v "${PLUGINS_DIR}:/opt/sonarqube/extensions/plugins" \
        -v "${SONAR_PROPERTIES}:/opt/sonarqube/conf/sonar.properties:ro" \
        "$IMAGE" >/dev/null
    log "container started. Follow startup with: $0 logs   (or: $0 wait)"
}

cmd_wait() {
    need curl
    log "waiting up to ${WAIT_TIMEOUT}s for ${BASE_URL} to come UP ..."
    local deadline=$(( $(date +%s) + WAIT_TIMEOUT )) status
    while (( $(date +%s) < deadline )); do
        status="$(curl -sS "${BASE_URL}/api/system/status" 2>/dev/null \
                  | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)"
        if [[ "$status" == "UP" ]]; then
            log "SonarQube is UP at ${BASE_URL}"
            return 0
        fi
        [[ -n "$status" ]] && log "  status=$status ..."
        sleep 5
    done
    fail "SonarQube did not become UP within ${WAIT_TIMEOUT}s (see: $0 logs)"
}

cmd_status() {
    need docker
    if container_exists; then
        docker ps -a --filter "name=^${CONTAINER}$" \
            --format 'container: {{.Names}} | {{.Status}} | {{.Ports}}'
    else
        log "container '$CONTAINER' does not exist"
    fi
    if command -v curl >/dev/null 2>&1; then
        local status
        status="$(curl -sS "${BASE_URL}/api/system/status" 2>/dev/null || true)"
        [[ -n "$status" ]] && echo "server:    $status"
    fi
}

cmd_logs()    { need docker; docker logs -f "$CONTAINER"; }
cmd_restart() { need docker; container_exists || fail "container '$CONTAINER' does not exist"; docker restart "$CONTAINER" >/dev/null; log "restarted '$CONTAINER'"; }

cmd_down() {
    need docker
    container_exists || { log "nothing to remove"; return 0; }
    docker rm -f "$CONTAINER" >/dev/null
    log "removed container '$CONTAINER' (data volumes kept)"
}

cmd_destroy() {
    cmd_down
    docker volume rm -f "$DATA_VOL" "$LOGS_VOL" >/dev/null 2>&1 || true
    log "removed data/logs volumes ($DATA_VOL, $LOGS_VOL)"
}

# ---- provisioning: password + rule toggles --------------------------------
try_auth() {  # try_auth <password> -> 0 if it authenticates as admin
    local pw="$1" code
    code="$(curl -sS -o /dev/null -w '%{http_code}' \
            -u "${ADMIN_USER}:${pw}" "${BASE_URL}/api/system/health" 2>/dev/null || echo 000)"
    [[ "$code" == "200" ]]
}

sonar_api() {  # sonar_api <METHOD> <path> [extra curl args...]
    local method="$1" path="$2"; shift 2
    curl -sS -u "${ADMIN_USER}:${API_PASSWORD}" -X "$method" "${BASE_URL}${path}" "$@"
}

resolve_admin_password() {
    if try_auth "$ADMIN_PASSWORD"; then
        API_PASSWORD="$ADMIN_PASSWORD"
        log "authenticated with configured admin password"
        return 0
    fi
    if try_auth "$DEFAULT_ADMIN_PASSWORD"; then
        log "changing default admin password"
        curl -sS -u "${ADMIN_USER}:${DEFAULT_ADMIN_PASSWORD}" -X POST \
            "${BASE_URL}/api/users/change_password" \
            --data-urlencode "login=${ADMIN_USER}" \
            --data-urlencode "previousPassword=${DEFAULT_ADMIN_PASSWORD}" \
            --data-urlencode "password=${ADMIN_PASSWORD}" >/dev/null \
            || fail "failed to change admin password"
        API_PASSWORD="$ADMIN_PASSWORD"
        return 0
    fi
    fail "could not authenticate to the SonarQube admin API (tried configured + default passwords)"
}

apply_disabled_rules() {
    if [[ ! -f "$DISABLED_RULES" ]]; then
        log "no $DISABLED_RULES; skipping rule toggles"
        return 0
    fi
    local rules=()
    while IFS= read -r line; do
        line="${line%%#*}"; line="${line//[[:space:]]/}"
        [[ -n "$line" ]] && rules+=("$line")
    done < "$DISABLED_RULES"
    if (( ${#rules[@]} == 0 )); then
        log "no rules listed in $DISABLED_RULES; nothing to disable"
        return 0
    fi

    # Find the current default C++ profile, copy it to our editable profile
    # (built-in profiles can't be modified), and make the copy the default.
    local from_key
    from_key="$(sonar_api GET "/api/qualityprofiles/search?language=${CXX_LANG}" \
        | python3 -c 'import json,sys
d=json.load(sys.stdin); ps=d.get("profiles",[])
df=[p for p in ps if p.get("isDefault")] or ps
print(df[0]["key"] if df else "")' 2>/dev/null || true)"
    [[ -n "$from_key" ]] || fail "no C++ (${CXX_LANG}) quality profile found; is the sonar-cxx plugin loaded?"

    local our_key
    our_key="$(sonar_api GET "/api/qualityprofiles/search?language=${CXX_LANG}" \
        | python3 -c "import json,sys
d=json.load(sys.stdin)
print(next((p['key'] for p in d.get('profiles',[]) if p.get('name')=='${CXX_PROFILE_NAME}'), ''))" 2>/dev/null || true)"
    if [[ -z "$our_key" ]]; then
        log "creating quality profile '${CXX_PROFILE_NAME}' (copy of the default C++ profile)"
        our_key="$(sonar_api POST "/api/qualityprofiles/copy" \
            --data-urlencode "fromKey=${from_key}" \
            --data-urlencode "toName=${CXX_PROFILE_NAME}" \
            | python3 -c 'import json,sys;print(json.load(sys.stdin).get("key",""))' 2>/dev/null || true)"
    fi
    [[ -n "$our_key" ]] || fail "could not create/find profile '${CXX_PROFILE_NAME}'"

    log "setting '${CXX_PROFILE_NAME}' as the default ${CXX_LANG} profile"
    sonar_api POST "/api/qualityprofiles/set_default" \
        --data-urlencode "language=${CXX_LANG}" \
        --data-urlencode "qualityProfile=${CXX_PROFILE_NAME}" >/dev/null || true

    local r ok=0 bad=0
    for r in "${rules[@]}"; do
        if sonar_api POST "/api/qualityprofiles/deactivate_rule" \
            --data-urlencode "key=${our_key}" \
            --data-urlencode "rule=${r}" >/dev/null 2>&1; then
            log "  disabled rule: $r"; ok=$((ok+1))
        else
            log "  WARNING: could not disable rule '$r' (unknown key or already off)"; bad=$((bad+1))
        fi
    done
    log "rule toggles applied: ${ok} disabled, ${bad} skipped"
}

cmd_provision() {
    need curl
    cmd_wait
    resolve_admin_password
    apply_disabled_rules
    log "provisioning done. Admin: ${ADMIN_USER} / (SONAR_ADMIN_PASSWORD)"
}

# ---------------------------------------------------------------------------
usage() {
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
    up)       cmd_up ;;
    wait)     cmd_wait ;;
    provision) cmd_provision ;;
    status)   cmd_status ;;
    logs)     cmd_logs ;;
    restart)  cmd_restart ;;
    down)     cmd_down ;;
    destroy)  cmd_destroy ;;
    ""|-h|--help|help) usage ;;
    *) fail "unknown command '$1' (try: $0 --help)" ;;
esac
