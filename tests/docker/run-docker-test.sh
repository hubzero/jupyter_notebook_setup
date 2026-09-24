#!/bin/bash
# file: tests/docker/run-docker-test.sh
#
# Runs the Rocky Linux 10 compatibility tests for jpkg, start_jupyter and start_jupyterlab in a
# throwaway container built from the stock Rocky 10 image plus the prerequisites listed in jpkg.
#
#   ./run-docker-test.sh                          everything except the Anaconda install
#   ./run-docker-test.sh TestStartJupyter         one class (or Class.test_method)
#   ./run-docker-test.sh --anaconda               also download and run the Anaconda installer
#   ./run-docker-test.sh --offline                skip the tests that need the network
#   ./run-docker-test.sh --keep                   leave the container up for poking at
#
# The base image is pulled fresh on every run rather than reusing whatever is in the local cache.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$(dirname "$here")")"

image="${JUPYTER_TEST_IMAGE:-rockylinux/rockylinux:10}"
image_tag="jupyter-setup-rocky10-test:latest"
container="${JUPYTER_TEST_CONTAINER:-jupyter-setup-rocky10-test}"
dest=/opt/jupyter_notebook_setup

keep=0
network=1
anaconda=0
selection=()
for arg in "$@"; do
    case "$arg" in
        --keep) keep=1 ;;
        --offline) network=0 ;;
        --anaconda) anaconda=1 ;;
        -h|--help) sed -n '3,13p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) selection+=("$arg") ;;
    esac
done

# The single source of truth for the prerequisites is the comment at the top of jpkg.
prereqs="$(sed -n 's/^#   dnf install -y //p' "$repo/jpkg")"
if [ -z "$prereqs" ]; then
    echo "could not find the '#   dnf install -y ...' prerequisite line in $repo/jpkg" >&2
    exit 1
fi

cleanup() {
    if [ "$keep" -eq 1 ]; then
        echo
        echo "container left running: docker exec -it -u jupytest $container bash"
        return
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== removing any container left over from a previous run"
docker rm -f "$container" >/dev/null 2>&1 || true

echo "== pulling a clean $image"
docker pull "$image"

echo "== building $image_tag with: $prereqs"
docker build --network "${JUPYTER_TEST_BUILD_NETWORK:-host}" \
    --build-arg "BASE_IMAGE=$image" --build-arg "PREREQS=$prereqs" \
    -t "$image_tag" "$here"

echo "== starting $container"
docker run -d --name "$container" --network "${JUPYTER_TEST_NETWORK_MODE:-host}" \
    "$image_tag" >/dev/null

echo "== copying the repository into the container"
docker exec "$container" mkdir -p "$dest"
tar -C "$repo" --exclude=.git -cf - . | docker exec -i "$container" tar -C "$dest" -xf -
docker exec "$container" chown -R jupytest:jupytest "$dest"

targets=("test_rocky10")
if [ "${#selection[@]}" -gt 0 ]; then
    targets=()
    for s in "${selection[@]}"; do
        targets+=("test_rocky10.$s")
    done
fi

echo "== running the tests as jupytest"
docker exec -u jupytest -w "$dest/tests/docker" \
    -e "JUPYTER_TEST_REPO=$dest" \
    -e "JUPYTER_TEST_NETWORK=$network" \
    -e "JUPYTER_TEST_ANACONDA=$anaconda" \
    "$container" python3 -W ignore::ResourceWarning -m unittest -v "${targets[@]}"
