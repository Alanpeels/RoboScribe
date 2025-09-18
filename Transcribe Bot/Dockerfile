# Use slim Python base
FROM python:3.11-slim

# System deps: ffmpeg + opus for Discord voice
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY bot.py .

# Expose HTTP health port for Fly
EXPOSE 8080

# Run
CMD ["python", "bot.py"]
