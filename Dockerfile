# Multi-stage build for minimal image size
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 archon && \
    mkdir -p /app && \
    chown -R archon:archon /app

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /root/.local /home/archon/.local

# Copy application code
COPY --chown=archon:archon archon/ ./archon/

# Set PATH for user-installed packages
ENV PATH=/home/archon/.local/bin:$PATH

# Switch to non-root user
USER archon

# Expose port
EXPOSE 8080

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import http.client; conn = http.client.HTTPConnection('localhost', 8080); conn.request('GET', '/health'); r = conn.getresponse(); exit(0 if r.status == 200 else 1)"

# Run application
CMD ["python", "-m", "archon.query.server"]
