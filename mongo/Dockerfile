FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt && pip check \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY common.py ./
COPY init/ ./init/
COPY indexes/ ./indexes/
COPY seed/ ./seed/
COPY docker-entrypoint.sh ./
USER app
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
