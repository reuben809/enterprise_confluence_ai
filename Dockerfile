# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy all project files into the container
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose FastAPI port
EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["uvicorn", "chat.chat_api:app", "--host", "0.0.0.0", "--port", "8000"]
