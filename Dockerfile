FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOME=/app
RUN apt-get update && apt-get install -y --no-install-recommends curl wget build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR $APP_HOME
COPY requirements/base.txt .
RUN pip install --no-cache-dir -r base.txt
COPY . .
RUN useradd -m -u 1000 quantuser && chown -R quantuser:quantuser $APP_HOME
USER quantuser
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:9090/metrics || exit 1
ENTRYPOINT ["python", "main.py"]
