FROM nvidia/cuda:12.4.1-devel-ubuntu22.04
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake build-essential python3 python3-pip python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Build llama.cpp (pinned tag for reproducibility)
RUN git clone --depth 1 --branch b4934 https://github.com/ggerganov/llama.cpp /opt/llama.cpp && \
    pip3 install --no-cache-dir -r /opt/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt && \
    cmake -B /opt/llama.cpp/build -S /opt/llama.cpp \
          -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON && \
    cmake --build /opt/llama.cpp/build --target llama-quantize -j"$(nproc)"

ENV LLAMA_CPP_DIR=/opt/llama.cpp

RUN pip3 install --no-cache-dir \
        autoawq transformers accelerate huggingface_hub boto3

COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py
CMD ["python3", "run.py"]
