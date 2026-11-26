#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/../.."
root=$(pwd -P)
key=$(sha256sum <<<"$root" | cut -c1-12)
project="harness-nomad-$key"
unit="harness-nomad-client@$key.service"
source_unit="$root/dev/nomad/harness-nomad-client@.service"
server_addr=http://127.0.0.1:14646
mkdir -p .harness/nomad
exec 9>.harness/nomad/cluster.lock
flock -w 90 9

compose() { docker compose --project-name "$project" --file dev/nomad/compose.yaml "$@"; }
fail() { echo "$*" >&2; exit 1; }

start_server() {
    if ! compose up --wait --wait-timeout 60 server; then
        compose logs --tail 20 server >&2
        return 1
    fi
    compose exec -T server /bin/nomad version
}

ready_node() {
    curl -fsS --max-time 2 "$server_addr/v1/nodes" |
        jq -cer --arg name "$project-client" '
            .[] | select(.Name == $name and .Status == "ready"
                and .SchedulingEligibility == "eligible" and .Drivers.docker.Healthy)
            | {node: .ID, name: .Name, status: .Status, docker: .Drivers.docker.Healthy}'
}

start_client() {
    mkdir -p -- "$(dirname -- "$unit_link")"
    if [[ ! -e $unit_link && ! -L $unit_link ]]; then
        ln -s -- "$source_unit" "$unit_link"
    fi
    [[ $unit_link -ef $source_unit ]] || fail "Another unit already owns $unit_link."
    systemctl --user daemon-reload
    systemctl --user start "$unit"
    local deadline=$((SECONDS + 60))
    until ready_node; do
        if ! systemctl --user is-active --quiet "$unit" || (( SECONDS >= deadline )); then
            fail "Docker-capable Nomad client unavailable. Inspect: journalctl --user -u $unit"
        fi
        sleep 1
    done
}

down() {
    if [[ -L $unit_link ]]; then
        [[ $unit_link -ef $source_unit ]] || fail "Another unit already owns $unit_link."
        if [[ $(systemctl --user show "$unit" --property=LoadState --value) != not-found ]]; then
            systemctl --user stop "$unit"
        fi
        unlink "$unit_link"
        systemctl --user daemon-reload
    fi
    compose down --volumes
}

if [[ ${1:-} != server ]]; then
    unit_link="${XDG_RUNTIME_DIR:?}/systemd/user/$unit"
    systemctl --user show --property=Version >/dev/null ||
        fail "Cannot reach the host systemd user manager."
fi

case "${1:-}" in
    server) start_server ;;
    agent) start_client ;;
    down) down ;;
    identity)
        container=$(compose ps --quiet server)
        invocation=$(systemctl --user show "$unit" --property=InvocationID --value)
        [[ -n $container && -n $invocation && $unit_link -ef $source_unit ]]
        echo "server=$container client_unit=$unit client_invocation=$invocation"
        ;;
    assert-down)
        container=$(compose ps --all --quiet server)
        volumes=$(docker volume ls --quiet --filter "label=com.docker.compose.project=$project")
        [[ -z $container && -z $volumes && ! -L $unit_link ]] && ! systemctl --user is-active --quiet "$unit" ||
            fail "Cold-start evidence requires the project cluster and its data volume to be down."
        ;;
    *) fail "Expected server, agent, down, identity, or assert-down." ;;
esac
