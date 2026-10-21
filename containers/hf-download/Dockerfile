FROM python:3.12-slim
WORKDIR /app
# CPU node: Hugging Face Hub → object storage. huggingface_hub is pinned to the version the unit tests run against
# (2.x dropped resume_download and hf_transfer; downloads always resume).
RUN pip install --no-cache-dir huggingface_hub==2.2.0 boto3==1.35.71
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/hf-download/run.py /app/run.py
CMD ["python", "run.py"]
