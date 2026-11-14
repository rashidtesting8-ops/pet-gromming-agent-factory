FROM python:3.12-slim
WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/src:/workspace PATH="/workspace/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra browser \
    && playwright install --with-deps chromium \
    && useradd --create-home --shell /bin/bash appuser
COPY src ./src
COPY app ./app
RUN chown -R appuser:appuser /workspace
USER appuser
EXPOSE 8787 8888
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)"
CMD ["uvicorn", "src.engine.service:app", "--host", "0.0.0.0", "--port", "8787"]

