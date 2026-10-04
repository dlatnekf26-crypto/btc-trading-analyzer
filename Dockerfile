FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501 \
    BTC_WEB_DATA_DIR=/app/data/web

WORKDIR /app
COPY requirements.txt ./
COPY src ./src
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

COPY app.py web_app.py ./
COPY .streamlit ./.streamlit
COPY scripts/start_web.sh ./scripts/start_web.sh
USER appuser
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8501') + '/_stcore/health', timeout=4)"
CMD ["sh", "scripts/start_web.sh"]
