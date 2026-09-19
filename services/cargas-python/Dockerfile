FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt && pip check \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY app/ ./app/
USER app
EXPOSE 8092
ENTRYPOINT ["python", "-m", "app.main"]
