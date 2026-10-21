FROM python:3.12-slim
WORKDIR /app
# API node: it only calls Token Factory (packages/providers) and object storage (the SDK).
RUN pip install --no-cache-dir boto3==1.35.71 httpx==0.28.0
COPY packages/sdk-py/orchapod /app/orchapod
COPY packages/providers /app/packages/providers
COPY containers/tf-deploy/run.py /app/run.py
CMD ["python", "run.py"]
