# Build context = apps/ands-platform (so the shared kernel is available).
FROM python:3.12-slim

WORKDIR /srv
COPY libs /srv/libs
COPY gateway /srv/gateway

ENV PYTHONPATH=/srv/libs:/srv/gateway \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir -r /srv/gateway/requirements.txt

WORKDIR /srv/gateway
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
