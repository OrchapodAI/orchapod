#!/bin/bash
# Build and push every node image (one per containers/*/Dockerfile, so it always matches the CI matrix)
# to the registry CI pushes to (contracts R4). Run from the repo root: bash scripts/build-and-push-containers.sh
#
# Prerequisites:
#   docker login ghcr.io -u YOUR_GITHUB_USERNAME -p YOUR_GITHUB_PAT
#   export ORCHAPOD_IMAGE_PREFIX=ghcr.io/your-org   # optional; default ghcr.io/bangadpurva

set -e

REGISTRY="${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}"
TAG="${IMAGE_TAG:-latest}"

for dockerfile in containers/*/Dockerfile; do
  node=$(basename "$(dirname "$dockerfile")")
  echo "Building $node..."
  docker build \
    -t "$REGISTRY/$node:$TAG" \
    -f "$dockerfile" \
    .
  echo "Pushing $node..."
  docker push "$REGISTRY/$node:$TAG"
  echo "$node done: $REGISTRY/$node:$TAG"
done

echo "All containers pushed to $REGISTRY"
