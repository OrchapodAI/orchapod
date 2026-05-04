FROM python:3.12
WORKDIR /app
# llama-cpp-python for GGUF; autoawq for AWQ (needs CUDA for calibration)
RUN pip install "llama-cpp-python[server]" autoawq transformers boto3 --no-cache-dir
COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py
CMD ["python", "run.py"]
