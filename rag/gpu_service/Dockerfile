# TAI GPU Service Dockerfile
# Build: docker build -t tai-gpu-service .
# Run: docker run --gpus all -p 8000:8000 tai-gpu-service

FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download models to cache in image (optional, makes image larger but faster startup)
# Uncomment if you want models baked into image
# RUN python -c "import whisperx; whisperx.load_model('large-v3', device='cpu')"

# Copy server code
COPY server.py .

# Environment variables
ENV HUGGINGFACE_ACCESS_TOKEN=""
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
