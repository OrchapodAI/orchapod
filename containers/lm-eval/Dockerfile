FROM python:3.12
WORKDIR /app
RUN pip install lm-eval vllm openai boto3 --no-cache-dir
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/lm-eval/run.py /app/run.py
CMD ["python", "run.py"]
