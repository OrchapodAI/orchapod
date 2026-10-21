FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir boto3 "httpx==0.28.*" jsonschema
COPY packages/sdk-py/orchapod /app/orchapod
COPY packages/providers /app/packages/providers
COPY containers/synth-distilabel/run.py /app/run.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "run.py"]
