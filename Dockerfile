# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy all files to container
COPY . .

# Install system dependencies for audio and builds
RUN apt-get update && apt-get install -y ffmpeg libffi-dev

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run your bot
CMD ["python", "bot.py"]
