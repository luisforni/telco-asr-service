FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8001/healthz').raise_for_status()"
CMD ["python", "main.py"]
