from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id              BIGSERIAL PRIMARY KEY,
    applicant       TEXT NOT NULL,
    drug_product    TEXT NOT NULL,
    dossier_id      TEXT NOT NULL,
    submission_type TEXT NOT NULL,
    sequence        TEXT NOT NULL,
    contact_email   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_submissions_dossier
    ON submissions (dossier_id, sequence);

CREATE TABLE IF NOT EXISTS package_jobs (
    id          BIGSERIAL PRIMARY KEY,
    dossier_id  TEXT NOT NULL,
    sequence    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    s3_key      TEXT,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://", "postgresql://", 1
            )
        self._pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
        )
        self.init_schema()

    def init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _connection(self):
        with self._pool.connection() as conn:
            yield conn
            conn.commit()

    def prior_sequences(self, dossier_id: str) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT sequence FROM submissions WHERE dossier_id = %s "
                "ORDER BY sequence",
                (dossier_id.strip(),),
            ).fetchall()
        return [r["sequence"] for r in rows]

    def add_submission(self, data: dict, submission_type: str) -> dict:
        created_at = datetime.now(timezone.utc)
        with self._connection() as conn:
            row = conn.execute(
                """
                INSERT INTO submissions
                    (applicant, drug_product, dossier_id, submission_type,
                     sequence, contact_email, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(data.get("applicant", "")).strip(),
                    str(data.get("drug_product", "")).strip(),
                    str(data.get("dossier_id", "")).strip(),
                    submission_type,
                    str(data.get("sequence", "")).strip(),
                    str(data.get("contact_email", "")).strip(),
                    created_at,
                ),
            ).fetchone()
        return _serialize(row)

    def list_submissions(self) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM submissions ORDER BY id"
            ).fetchall()
        return [_serialize(r) for r in rows]

    def get_submission(self, submission_id: int) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = %s",
                (submission_id,),
            ).fetchone()
        return _serialize(row) if row else None

    def enqueue_package_job(self, dossier_id: str, sequence: str) -> dict:
        with self._connection() as conn:
            row = conn.execute(
                """
                INSERT INTO package_jobs (dossier_id, sequence, status)
                VALUES (%s, %s, 'queued')
                RETURNING *
                """,
                (dossier_id.strip(), sequence.strip()),
            ).fetchone()
        return _serialize(row)

    def claim_next_package_job(self) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                UPDATE package_jobs
                SET status = 'running', updated_at = NOW()
                WHERE id = (
                    SELECT id FROM package_jobs
                    WHERE status = 'queued'
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """
            ).fetchone()
        return _serialize(row) if row else None

    def complete_package_job(
        self, job_id: int, *, s3_key: str | None = None, error: str | None = None
    ) -> None:
        status = "failed" if error else "completed"
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE package_jobs
                SET status = %s, s3_key = %s, error = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (status, s3_key, error, job_id),
            )

    def close(self) -> None:
        self._pool.close()


def _serialize(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    if out.get("created_at") is not None:
        out["created_at"] = out["created_at"].isoformat()
    if out.get("updated_at") is not None:
        out["updated_at"] = out["updated_at"].isoformat()
    return out
