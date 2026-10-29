# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN useradd --system --uid 10001 --no-create-home erp
COPY pyproject.toml ./
COPY erp_mock ./erp_mock
RUN pip install .

USER erp
EXPOSE 8100
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=2)"
CMD ["uvicorn", "erp_mock.main:app", "--host", "0.0.0.0", "--port", "8100"]
