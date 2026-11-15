# FIRMS Harmonizer: one container serving the FastAPI backend and the built React frontend.
# Used unchanged by the Hugging Face Space and for local runs:
#   docker build -t firms-harmonizer .
#   docker run -p 7860:7860 -e DATA_REPO=<user>/<dataset> firms-harmonizer

FROM node:24-slim AS frontend
WORKDIR /src/firms-harmonizer/frontend
COPY firms-harmonizer/frontend/package.json firms-harmonizer/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
# The store imports the region registry from ../../../data/regions.json.
COPY firms-harmonizer/data/regions.json /src/firms-harmonizer/data/regions.json
COPY firms-harmonizer/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Hugging Face Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user
COPY firms-harmonizer/backend/requirements.txt /tmp/backend-requirements.txt
COPY deploy/requirements.txt /tmp/deploy-requirements.txt
RUN pip install -r /tmp/backend-requirements.txt -r /tmp/deploy-requirements.txt
WORKDIR /app
COPY --chown=user firms-harmonizer/backend ./backend
COPY --chown=user firms-harmonizer/data ./data
COPY --chown=user firms-harmonizer/scripts ./scripts
COPY --chown=user --from=frontend /src/firms-harmonizer/frontend/dist ./frontend/dist
COPY --chown=user deploy/entrypoint.py ./entrypoint.py
USER user
ENV HOME=/home/user \
    APP_ROOT=/app \
    PORT=7860 \
    FRONTEND_DIST=/app/frontend/dist \
    USE_SYNTHETIC_CUBE=0 \
    COPILOT_OFFLINE=1 \
    NRT_POLLING=0
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '7860'), timeout=4)"
CMD ["python", "entrypoint.py"]
