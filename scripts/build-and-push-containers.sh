#!/bin/bash
# Build and push all 6 node container images to GHCR.
# Run from repo root: bash scripts/build-and-push-containers.sh
#
# Prerequisites:
#   docker login ghcr.io -u YOUR_GITHUB_USERNAME -p YOUR_GITHUB_PAT
#   export GITHUB_ORG=orchapod  # your GitHub org/username

set -e

REGISTRY="ghcr.io/${GITHUB_ORG:-orchapod}"
TAG="${IMAGE_TAG:-latest}"

NODES=(data-prep unsloth-train distill-sft quantize lm-eval vllm-serve)

for node in "${NODES[@]}"; do
  echo "Building $node..."
  docker build \
    -t "$REGISTRY/$node:$TAG" \
    -f "containers/$node/Dockerfile" \
    .
  echo "Pushing $node..."
  docker push "$REGISTRY/$node:$TAG"
  echo "$node done: $REGISTRY/$node:$TAG"
done

echo "All containers pushed to $REGISTRY"
