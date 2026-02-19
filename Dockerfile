FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .
RUN uv pip install --system --no-cache -e .

EXPOSE 8189

CMD ["uvicorn", "emtulli.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8189"]
