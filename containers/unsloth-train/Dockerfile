FROM nvcr.io/nvidia/pytorch:24.10-py3
WORKDIR /app

# Build context is repo root (see scripts/build-and-push-containers.sh)
COPY containers/unsloth-train/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/unsloth-train/run.py /app/run.py

# Cache HF model downloads to /workspace so pod restarts reuse them
ENV HF_HOME=/workspace/hf_cache \
    PYTHONPATH=/app

CMD ["python", "run.py"]
