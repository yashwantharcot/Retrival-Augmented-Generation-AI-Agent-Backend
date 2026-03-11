FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install small system deps required by some packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git libgl1 libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-backend.txt ./

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements-backend.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
