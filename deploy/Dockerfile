# One image for all services (scanner, dashboard, recorder); the command picks the service.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install -r /tmp/req.txt && rm /tmp/req.txt

COPY config.yaml positions.example.json ./
COPY swinglock ./swinglock

# Run as an unprivileged user; data/ is the shared volume.
RUN useradd --uid 1000 --create-home app && mkdir -p data/live && chown -R app /app/data
USER app

CMD ["python", "-m", "swinglock.scanner"]
