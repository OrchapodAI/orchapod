FROM nvcr.io/nvidia/pytorch:24.10-py3
WORKDIR /app
RUN pip install "unsloth[colab-new]" trl transformers datasets vllm boto3 --no-cache-dir
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/distill-sft/run.py /app/run.py
CMD ["python", "run.py"]
