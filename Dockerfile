FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY causaltrace ./causaltrace
COPY artifacts ./artifacts
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8000
CMD ["uvicorn","causaltrace.api:app","--host","0.0.0.0","--port","8000"]
