# --- compile translations (.po -> .mo) ---------------------------------------
FROM python:3.12-slim AS locales
RUN apt-get update \
 && apt-get install -y --no-install-recommends gettext \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY locales ./locales
COPY compile_locales.sh .
# Strip Windows line endings in case the files were copied from a Windows checkout.
RUN sed -i 's/\r$//' compile_locales.sh locales/*.po && bash compile_locales.sh

# --- runtime -----------------------------------------------------------------
# Python 3.12: nextcord still imports audioop, which was removed in 3.13.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=locales /src/locales/compiled ./locales/compiled

RUN useradd --uid 1000 --create-home fragq \
 && mkdir -p /data \
 && chown fragq:fragq /data
USER fragq
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# SIGTERM (docker stop) saves the queues and running matches to /data/saved_state.json.
STOPSIGNAL SIGTERM
CMD ["python", "FragQ.py"]
