FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/alembic.ini ./
COPY backend/researchhub ./researchhub
COPY backend/migrations ./migrations
COPY demo/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend /app/dist /usr/share/nginx/html
COPY scripts/seed_browser_fixture.py ./seed_browser_fixture.py
COPY demo/start.sh ./start.sh
RUN chmod +x ./start.sh

ENV RESEARCHHUB_STORAGE=/tmp/researchhub-artifacts
RUN mkdir -p /tmp/researchhub-artifacts
EXPOSE 10000
CMD ["./start.sh"]
