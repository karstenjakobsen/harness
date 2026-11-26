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
    python3 dev/nomad/client-config.py .harness/nomad/worker.hcl
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

client_session() {
    if [[ -z ${XDG_RUNTIME_DIR:-} ]]; then
        echo "Missing XDG_RUNTIME_DIR for the systemd user session." >&2
        return 1
    fi
    unit_link="$XDG_RUNTIME_DIR/systemd/user/$unit"
    systemctl --user show --property=Version >/dev/null
}

stop_client() {
    client_session || return 1
    local loaded
    loaded=$(systemctl --user show "$unit" --property=LoadState --value) || [[ $loaded == not-found ]] || return 1
    if [[ ! -L $unit_link && $loaded == not-found ]]; then return 0; fi
    if [[ ! $unit_link -ef $source_unit ]]; then
        echo "Cannot identify $unit as this checkout's client." >&2
        return 1
    fi
    if [[ $loaded != not-found ]]; then systemctl --user stop "$unit" || return 1; fi
    unlink "$unit_link" || return 1
    systemctl --user daemon-reload
}

down() {
    local status=0
    if ! stop_client; then
        echo "Nomad client cleanup could not be verified. Retry from the checkout's systemd user session." >&2
        status=1
    fi
    compose --profile worker down --volumes || return 1
    return "$status"
}

case "${1:-}" in
    server) start_server ;;
    worker-image)
        compose up -d worker-registry
        image=127.0.0.1:14661/harness-worker
        docker build --tag "$image:local" dev/worker
        docker push "$image:local"
        ref=$(docker image inspect "$image:local" | jq -er --arg prefix "$image@" '.[0].RepoDigests[] | select(startswith($prefix))')
        test -n "$ref"
        echo "$ref" > .harness/nomad/worker-image.tmp
        mv .harness/nomad/worker-image.tmp .harness/nomad/worker-image
        echo "$ref"
        ;;
    agent) client_session && start_client ;;
    down) down ;;
    identity)
        client_session
        container=$(compose ps --quiet server)
        invocation=$(systemctl --user show "$unit" --property=InvocationID --value)
        [[ -n $container && -n $invocation && $unit_link -ef $source_unit ]]
        echo "server=$container client_unit=$unit client_invocation=$invocation"
        ;;
    assert-down)
        client_session
        container=$(compose ps --all --quiet server)
        volumes=$(docker volume ls --quiet --filter "label=com.docker.compose.project=$project")
        [[ -z $container && -z $volumes && ! -L $unit_link ]] && ! systemctl --user is-active --quiet "$unit" ||
            fail "Cold-start evidence requires the project cluster and its data volume to be down."
        ;;
    *) fail "Expected server, agent, worker-image, down, identity, or assert-down." ;;
esac
