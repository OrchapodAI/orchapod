FROM python:3.12-slim
WORKDIR /app
RUN pip install datasets pandas pyyaml boto3 --no-cache-dir
COPY packages/sdk-py/orchapod /app/orchapod
COPY containers/data-prep/run.py /app/run.py
CMD ["python", "run.py"]
