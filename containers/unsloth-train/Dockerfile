# STUB=1 only (the stub stack: `docker build --target stub`): the SDK and run.py, whose GPU imports are lazy, so it builds
# on any machine. It stays first: the last stage, the CUDA image below, is the default target for CI, the build script
# and Nebius Jobs.
FROM python:3.12-slim AS stub
WORKDIR /app
RUN pip install --no-cache-dir boto3==1.35.71
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/unsloth-train/run.py /app/run.py
CMD ["python", "run.py"]

# GPU node: a Nebius Serverless Job. Spike 4's proven stack (containers/unsloth-train/spike): this image, uv and its
# 203-pin lock (Python 3.12, torch 2.10 / CUDA 12.8, unsloth 2026.10.7, trl 1.15.0, peft 0.21.2, linux x86_64).
# No Mamba-2 wheels: with mamba_ssm installed, `import unsloth` imports it (transformers' is_mamba_2_ssm_available), and
# its tilelang TVM fails against the lock's apache-tvm-ffi (live golden run fa20d166, 2026-10-25). The golden path's student
# is LlamaForCausalLM; spike 4 installed the wheels only for the NemotronH 30B, which this image no longer trains.
FROM pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONPATH=/app HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1 \
    HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
COPY containers/unsloth-train/spike/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --break-system-packages uv==0.11.12 && uv venv /opt/venv --python 3.12 && \
    uv pip install --no-cache -r /tmp/requirements.lock.txt boto3==1.35.71
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/unsloth-train/run.py /app/run.py
CMD ["python", "run.py"]
