FROM python:3.12-slim
WORKDIR /app

# hf_transfer — Rust-based multi-threaded downloader (5-10x faster than urllib).
# Activated via HF_HUB_ENABLE_HF_TRANSFER=1 below.
RUN pip install --no-cache-dir \
        "huggingface_hub[hf_transfer]>=0.23" \
        boto3 \
        httpx

# Enable fast downloads
ENV HF_HUB_ENABLE_HF_TRANSFER=1

# SDK and container entry point
COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py

CMD ["python3", "run.py"]
