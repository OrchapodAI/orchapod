FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

WORKDIR /app

# System deps for llama.cpp build + Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip cmake build-essential git libgomp1 ca-certificates \
    && ln -s /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Python deps: AWQ + HF toolchain
RUN pip install --no-cache-dir \
    autoawq \
    transformers \
    accelerate \
    sentencepiece \
    protobuf \
    huggingface_hub \
    boto3 \
    gguf

# Build llama.cpp (provides convert_hf_to_gguf.py + llama-quantize binary)
# Pinned to a stable release tag; bump when a new model family needs support.
RUN git clone --depth 1 --branch b4934 \
    https://github.com/ggerganov/llama.cpp /opt/llama.cpp \
    && pip install --no-cache-dir -r /opt/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt \
    && cmake -B /opt/llama.cpp/build -S /opt/llama.cpp \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_CUDA=ON \
    && cmake --build /opt/llama.cpp/build \
        --config Release \
        --target llama-quantize \
        -j"$(nproc)"

ENV LLAMA_CPP_DIR=/opt/llama.cpp

COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py

CMD ["python", "run.py"]
