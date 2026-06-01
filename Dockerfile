# Build stage: Install dependencies using uv
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Disable Python downloads to use the system interpreter
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install build dependencies required for compiling native extensions (like Rust-based libsql)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cargo \
    rustc \
    pkg-config \
    libssl-dev \
 && rm -rf /var/lib/apt/lists/*

# Mount caches for uv to optimize dependency resolution and downloads
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

# Copy project source files
COPY . /app

# Sync the whole project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Runtime stage: Setup lightweight Python 3.14 slim image
FROM python:3.14-slim-bookworm

# Setup security best practices via a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# Copy the built application and virtual environment from the builder
COPY --from=builder --chown=nonroot:nonroot /app /app

# Ensure that the virtual environment executables are at the front of the PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Expose the default server port
EXPOSE 8000

# Use the non-root user
USER nonroot
WORKDIR /app

# Start the production-grade Gunicorn WSGI server by default
CMD ["prod"]
