FROM vllm/vllm-openai:latest
WORKDIR /app

# Install cloudflared for Cloudflare Tunnel support (KAN-28)
RUN curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
      -o /tmp/cloudflared.deb \
    && dpkg -i /tmp/cloudflared.deb \
    && rm /tmp/cloudflared.deb

RUN pip install boto3 --no-cache-dir
COPY ../../packages/sdk-py/orchapod /app/orchapod
COPY run.py /app/run.py
CMD ["python", "run.py"]
