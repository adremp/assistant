FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN pip install --no-cache-dir uv

# Copy pkg first for caching
COPY pkg/ ./pkg/

# Install pkg
RUN cd pkg && uv pip install --system .

# Copy core module
COPY internal/core/ ./internal/core/

# Install core dependencies
RUN cd internal/core && uv pip install --system .

# Production stage
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

# Copy application code
COPY pkg/pkg /app/pkg
COPY internal/core/core /app/core

# Set Python path
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
