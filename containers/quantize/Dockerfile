# CPU node. llama.cpp's own full image (CPU build b11223, Ubuntu 24.04, Python 3.12) already holds
# convert_hf_to_gguf.py with its Python deps (torch CPU, transformers, gguf, huggingface_hub) and llama-quantize in /app.
FROM ghcr.io/ggml-org/llama.cpp:full-b11223
WORKDIR /app
RUN pip install --no-cache-dir --break-system-packages boto3==1.35.71
ENV LLAMA_CPP_DIR=/app
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/quantize/run.py /app/run.py
ENTRYPOINT []
CMD ["python3", "run.py"]
