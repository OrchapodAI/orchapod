FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir datasets boto3 "httpx==0.28.*"
COPY packages/sdk-py/orchapod /app/orchapod
COPY packages/providers /app/packages/providers
COPY containers/data-prep/run.py /app/run.py
CMD ["python", "run.py"]
