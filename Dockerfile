# Agente VNC: un contenedor, una instancia y un worker de uvicorn (diseño D12).
FROM python:3.12-slim

# Tesseract con el paquete de español para el OCR (diseño D8).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Primero las dependencias: la capa se reutiliza mientras no cambie uv.lock.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# Sin root. TRACE_DIR (./traces) queda dentro de /app y es del usuario del servicio.
RUN useradd --create-home --uid 1000 agente && mkdir traces && chown agente traces
USER agente

EXPOSE 8000
# Railway y Fly.io pasan el puerto en $PORT. Un solo worker: el registro de tareas vive en memoria.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
