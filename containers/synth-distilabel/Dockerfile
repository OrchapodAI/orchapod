FROM python:3.12-slim

WORKDIR /workspace

RUN pip install --no-cache-dir orchapod-sdk openai anthropic

COPY run.py /workspace/run.py

ENV PYTHONUNBUFFERED=1

CMD ["python", "run.py"]
