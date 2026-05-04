FROM vllm/vllm-openai:latest
WORKDIR /app
RUN pip install boto3 --no-cache-dir
COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py
CMD ["python", "run.py"]
