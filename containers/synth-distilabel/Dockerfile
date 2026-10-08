FROM python:3.12-slim

WORKDIR /workspace

RUN pip install --no-cache-dir boto3 openai anthropic

# Copy the SDK directly (not on PyPI)
COPY sdk/ /workspace/orchapod/

COPY run.py /workspace/run.py

ENV PYTHONUNBUFFERED=1

CMD ["python", "run.py"]
