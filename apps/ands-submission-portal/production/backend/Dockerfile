FROM python:3.12-slim

WORKDIR /opt/portal

# Domain modules (stdlib-only) from the monolith portal
COPY domain.py validation.py transmission.py lifecycle.py ectd.py rep.py \
     backbone.py bioequivalence.py content_model.py fees.py hc_calendar.py \
     stf.py qos.py rbac.py esign.py retention.py dr.py report_ingest.py \
     readiness.py navigation.py entitlements.py tenancy.py auth.py privacy.py \
     cv.py xmlsafe.py response_builder.py rep_stylesheet.py ./

COPY production/backend/requirements.txt /opt/backend/requirements.txt
RUN pip install --no-cache-dir -r /opt/backend/requirements.txt

COPY production/backend/app /opt/backend/app
COPY production/backend/worker /opt/backend/worker

ENV PYTHONPATH=/opt/portal
WORKDIR /opt/backend

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
