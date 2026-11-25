FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-s3.txt .
RUN pip install --no-cache-dir -r requirements-s3.txt
COPY researchhub researchhub
COPY alembic.ini .
COPY migrations migrations
RUN useradd --create-home researchhub && install -d -o researchhub /artifacts
USER researchhub
CMD ["uvicorn", "researchhub.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
