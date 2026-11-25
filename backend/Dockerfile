FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg/ffprobe (with libass + x264) for every video step; fonts for captions
# (Latin + Devanagari so Hindi captions render).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-noto-core \
      fonts-inter \
      fonts-dejavu-core \
      fonts-noto-color-emoji \
      chromium \
      fontconfig \
      ca-certificates \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# motion-graphics effects drive Debian's Chromium (apt, above) through Playwright
ENV CHROMIUM_PATH=/usr/bin/chromium

COPY . .

# /app/models holds the Whisper weights (a named volume, downloaded once on first use)
RUN mkdir -p /app/work /app/models && useradd -m -u 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
