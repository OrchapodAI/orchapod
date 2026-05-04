FROM python:3.12
WORKDIR /app
RUN pip install lm-eval vllm anthropic openai boto3 --no-cache-dir
COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py
CMD ["python", "run.py"]
