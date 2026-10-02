# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# The retrieval index is derived from the corpus in the image, so build it
# here (read-only at runtime). Mutable state goes under /data: the SQLite
# database when DATABASE_URL isn't set to Postgres, and dev mail when SMTP
# isn't configured.
ENV CHROMA_DIR=/app/index \
    DATABASE_URL=sqlite:////data/glassbox.db \
    DEV_MAIL_DIR=/data/mail
RUN python -m corpus.ingest

RUN useradd --system --uid 10001 --no-create-home glassbox \
    && mkdir -p /data \
    && chown glassbox /data
USER glassbox
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Behind a load balancer, set FORWARDED_ALLOW_IPS to its address range so
# rate limits and the security log see client IPs, not the balancer's.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
