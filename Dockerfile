# Walkie in one container: the API, the built editor, ffmpeg and caption fonts.
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-trixie
# ffmpeg 7.1 renders the videos; Noto fonts draw burned-in captions in every language; fribidi lets Pillow
# lay out Arabic and other right-to-left text.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-cjk libfribidi0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/app ./app
COPY --from=web /app/web/dist /app/web/dist
ENV WALKIE_DATA=/app/server/data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
