# JP Research Agent — runs the whole CLI surface in a container.
# Offline (bundled sample) works with NO keys; live/LLM needs keys via --env-file.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code (the bundled offline sample under data/fixtures comes with it).
COPY . .

# Web UI port (docker compose up -> http://localhost:8000).
EXPOSE 8000

# `python` is the entrypoint, so any command is just its args, e.g.:
#   docker run --rm jp-research-agent main.py --ticker 8035 --no-llm
#   docker run --rm jp-research-agent -m src.comparison semiconductors
#   docker run --rm jp-research-agent -m unittest discover -s tests
ENTRYPOINT ["python"]

# Default (no args) — offline sample memo, zero keys required.
CMD ["main.py", "--ticker", "8035", "--no-llm"]
