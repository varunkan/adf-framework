# Build context = apps/ands-platform (so the shared kernel is available).
FROM python:3.12-slim

WORKDIR /srv
COPY libs /srv/libs
COPY services/readiness /srv/service

ENV PYTHONPATH=/srv/libs:/srv/service \
    PYTHONUNBUFFERED=1 \
    ANDS_DB_BACKEND=postgres \
    ANDS_BUS=redis

RUN pip install --no-cache-dir -r /srv/service/requirements.txt

WORKDIR /srv/service
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
