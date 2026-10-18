FROM python:3.12-slim

# ffmpeg splits long voice notes for transcription
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
ENV PYTHONUNBUFFERED=1
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["purchasebot", "serve", "--host", "0.0.0.0", "--port", "8000"]
