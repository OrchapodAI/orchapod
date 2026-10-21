FROM python:3.12-slim
WORKDIR /app
# API node: it creates a Nebius Serverless Endpoint running vllm/vllm-openai (packages/providers) and calls it once.
RUN pip install --no-cache-dir boto3==1.35.71 httpx==0.28.0
COPY packages/sdk-py/orchapod /app/orchapod
COPY packages/providers /app/packages/providers
COPY containers/vllm-serve/run.py /app/run.py
CMD ["python", "run.py"]
