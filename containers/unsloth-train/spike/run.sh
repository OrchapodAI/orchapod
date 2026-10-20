#!/usr/bin/env bash
# Spike 4 remote driver (runs on the rented GPU, from /workspace/spike):
#   bash run.sh MODEL TAG  ->  env setup (first run only), train.py (LoRA + 16-bit merge),
#   vLLM serve of the merged model, one chat completion. Phase timestamps go to phases.log.
set -euo pipefail
cd /workspace/spike
MODEL=$1 TAG=$2 OUT=/workspace/out/$2
mkdir -p "$OUT"
phase() { echo "PHASE $TAG $1 $(date +%s) $(date -u +%FT%TZ)" | tee -a phases.log; }
export HF_HOME=/workspace/hf HF_XET_HIGH_PERFORMANCE=1 HF_HUB_ENABLE_HF_TRANSFER=1 HF_HUB_DISABLE_TELEMETRY=1 \
  UV_CACHE_DIR=/workspace/uv-cache VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1

if [ ! -x venv/bin/python ]; then
  phase setup
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | tee -a phases.log
  python -m pip install -q --break-system-packages uv==0.11.12  # image python is PEP 668-managed
  uv venv venv --python 3.12
  uv pip install --python venv/bin/python -r requirements.lock.txt
  uv pip freeze --python venv/bin/python > freeze.txt
fi
case $MODEL in *Nemotron-3-Nano*)  # NemotronH needs the Mamba-2 kernels; prebuilt for torch 2.10 / cu12 / cp312
  uv pip install --python venv/bin/python \
    "https://github.com/state-spaces/mamba/releases/download/v2.3.2.post1/mamba_ssm-2.3.2.post1%2Bcu12torch2.10cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" \
    "https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.7.0/causal_conv1d-1.7.0%2Bcu12torch2.10cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" ;;
esac
. venv/bin/activate

if [ -z "${SKIP_TRAIN:-}" ]; then  # SKIP_TRAIN=1: serve an existing $OUT/merged only
  phase train
  python train.py "$MODEL" "$OUT"
  df -h /workspace | tail -1 | tee -a phases.log
fi

phase serve
case $MODEL in *Nemotron-3-Nano*)  # mamba_ssm's tilelang downgraded apache-tvm-ffi to 0.1.9 (training ran with it);
  # vLLM's xgrammar import then dies: "load_lib_module() got an unexpected keyword argument 'extra_lib_paths'".
  uv pip install --python venv/bin/python "$(grep '^apache-tvm-ffi==' requirements.lock.txt)" ;;
esac
vllm serve "$OUT/merged" --served-model-name "$TAG" --port 8011 --max-model-len 4096 --max-num-seqs 8 \
  --gpu-memory-utilization 0.9 --trust-remote-code > "$OUT/vllm.log" 2>&1 &
VLLM=$!
until python -c "import urllib.request as u; u.urlopen('http://localhost:8011/health', timeout=5)" 2>/dev/null; do
  kill -0 $VLLM 2>/dev/null || { tail -40 "$OUT/vllm.log"; phase serve_failed; exit 1; }
  sleep 5
done

phase chat
python - "$TAG" "$OUT/completion.json" <<'EOF'
import json, os, sys, urllib.request
tag, path = sys.argv[1:]
system = os.environ.get("SYSTEM", "detailed thinking off")
msgs = ([{"role": "system", "content": system}] if system else []) + [
    {"role": "user", "content": "In two sentences, explain what a LoRA adapter is."}]
body = {"model": tag, "messages": msgs, "temperature": 0, "max_tokens": 200,
        "chat_template_kwargs": {"enable_thinking": False}}
req = urllib.request.Request("http://localhost:8011/v1/chat/completions", json.dumps(body).encode(),
                             {"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=300))
json.dump(r, open(path, "w"), indent=2)
print("COMPLETION", json.dumps(r["choices"][0]["message"]["content"]), r["usage"])
EOF
kill $VLLM; wait $VLLM || true
phase done
