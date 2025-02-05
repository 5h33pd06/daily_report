# Use an official lightweight Python image
FROM python:3.9-slim

# Set environment variables to avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Set the working directory in the container
WORKDIR /app

# Copy project files
COPY . .

# Install system packages and dependencies
RUN apt-get update && apt-get install -y \
    cron procps nano \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose Flask default port
EXPOSE 31337

# Start cron in the background and run the Flask app with Gunicorn
CMD service cron start && gunicorn -b 0.0.0.0:31337 app:app
