# ---- Build stage: install dependencies with uv on alpine ----
FROM python:3.13-alpine AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

# ---- Runtime stage: clean alpine without build tools ----
FROM python:3.13-alpine

WORKDIR /app

# Copy only the installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy app source
COPY . .

# Run as non-root user
RUN addgroup -S empulse && adduser -S empulse -G empulse \
    && mkdir -p /app/data && chown -R empulse:empulse /app
USER empulse

EXPOSE 8189

CMD ["uvicorn", "empulse.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8189"]
