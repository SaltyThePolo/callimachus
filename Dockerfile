# Minimal Linux image; credentials, state and meeting content are mounted at run time, never built in.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable && rm -rf /root/.cache
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CALLIMACHUS_STATE_DIR=/state \
    CALLIMACHUS_ARCHIVE_DIR=/archive \
    CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE=/credentials/google-client.json \
    CALLIMACHUS_OAUTH_BIND=0.0.0.0
VOLUME ["/state", "/archive"]
ENTRYPOINT ["callimachus"]
CMD ["watch"]
