# ── stage 1: build the SPA ───────────────────────────────────────────────────
# The front end ships inside the same image as the API. One origin means no
# CORS in production and no second deploy to keep in step, and it is only
# possible because every API route is namespaced under /api and therefore
# cannot collide with a client-side route.
FROM node:22-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ── stage 2: the service ─────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not invalidate the install layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY --from=web /web/dist ./web/dist

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
