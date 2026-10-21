# GPU node: a Nebius Serverless Job. Spike 4's proven stack (containers/unsloth-train/spike): this image, uv and its
# 203-pin lock (Python 3.12, torch 2.10 / CUDA 12.8, unsloth 2026.10.7, trl 1.15.0, peft 0.21.2, linux x86_64).
# The Mamba-2 wheels let NemotronH students train; their tilelang downgrades apache-tvm-ffi, which breaks vLLM's xgrammar
# import, so the lock's version is restored last.
FROM pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONPATH=/app HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1 \
    HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
COPY containers/unsloth-train/spike/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --break-system-packages uv==0.11.12 && uv venv /opt/venv --python 3.12 && \
    uv pip install --no-cache -r /tmp/requirements.lock.txt boto3==1.35.71 && \
    uv pip install --no-cache \
      "https://github.com/state-spaces/mamba/releases/download/v2.3.2.post1/mamba_ssm-2.3.2.post1%2Bcu12torch2.10cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" \
      "https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.7.0/causal_conv1d-1.7.0%2Bcu12torch2.10cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" && \
    uv pip install --no-cache "$(grep '^apache-tvm-ffi==' /tmp/requirements.lock.txt)"
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/unsloth-train/run.py /app/run.py
CMD ["python", "run.py"]
