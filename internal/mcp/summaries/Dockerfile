FROM python:3.13-slim AS builder
WORKDIR /build
RUN pip install uv

COPY pkg/ /build/pkg_src/
RUN uv venv /opt/venv && . /opt/venv/bin/activate && cd /build/pkg_src && uv pip install -e .

COPY internal/mcp/summaries/pyproject.toml ./
RUN . /opt/venv/bin/activate && uv pip install -r pyproject.toml

FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/pkg_src/pkg /app/pkg
COPY internal/mcp/summaries/mcp_summaries/ ./mcp_summaries/

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# TCP healthcheck since streamable HTTP only accepts POST/GET with specific headers
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD nc -z localhost 8000 || exit 1

CMD ["python", "-m", "mcp_summaries.server"]
