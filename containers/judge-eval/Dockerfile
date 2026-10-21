FROM python:3.12-slim-trixie
WORKDIR /app
# API node: Token Factory and our endpoints through packages/providers, object storage through the SDK, and
# llama-server (llama.cpp's CPU build b11223, from its own image) for GGUF inputs. trixie's glibc and libstdc++ are new
# enough for that Ubuntu 24.04 build; libgomp1 is its one missing library.
COPY --from=ghcr.io/ggml-org/llama.cpp:server-b11223 /app /opt/llama
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir boto3==1.35.71 httpx==0.28.0
# Its RUNPATH only covers the build tree and the working directory, so point the loader at the libraries.
ENV PATH=/opt/llama:$PATH LD_LIBRARY_PATH=/opt/llama
COPY packages/sdk-py/orchapod /app/orchapod
COPY packages/providers /app/packages/providers
COPY containers/judge-eval/run.py /app/run.py
CMD ["python", "run.py"]
