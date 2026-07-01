"""Document byte storage — a hexagonal port so dev uses the DB and prod uses S3.

A ``DocumentStore`` persists the actual uploaded/generated file bytes + metadata
and returns a stable ``doc_id`` + checksum. The eCTD leaf only ever carries an
``href`` + ``checksum`` (never bytes), so the JSON dossier model stays small —
bytes live here. Checksums use :func:`assembly.md5_hex` so a stored document and
its placed leaf share one hash. ``SqliteBlobStore`` (dev) stores bytes as a BLOB
in the service DB via the repository; ``S3Store`` is the production seam.
"""

from __future__ import annotations

from typing import Protocol

from ands_shared import new_id

from . import assembly

MAX_BYTES = 25 * 1024 * 1024   # 25 MB dev cap — keeps SQLite blobs sane


def _meta(rec: dict) -> dict:
    """A document record without its bytes (safe to return to callers)."""
    return {k: v for k, v in rec.items() if k != "body"}


class DocumentStore(Protocol):
    def put(self, dossier_id: str, section: str, filename: str,
            content_type: str, body: bytes, *, origin: str = "uploaded",
            lang: str | None = None) -> dict: ...
    def get(self, doc_id: str) -> dict | None: ...          # includes bytes
    def get_meta(self, doc_id: str) -> dict | None: ...     # no bytes
    def delete(self, doc_id: str) -> None: ...


class SqliteBlobStore:
    """Dev/test store — bytes as a BLOB in the dossier service DB (via the repo)."""

    def __init__(self, repo) -> None:
        self.repo = repo

    def put(self, dossier_id, section, filename, content_type, body, *,
            origin="uploaded", lang=None) -> dict:
        body = body if isinstance(body, bytes) else str(body or "").encode("utf-8")
        if len(body) > MAX_BYTES:
            raise ValueError(
                f"file is {len(body)} bytes; the {MAX_BYTES // (1024*1024)} MB "
                "limit is exceeded")
        rec = {"doc_id": new_id(), "dossier_id": str(dossier_id),
               "section": str(section), "filename": str(filename or "document"),
               "content_type": str(content_type or "application/octet-stream"),
               "checksum": assembly.md5_hex(body), "size": len(body),
               "origin": str(origin), "lang": lang, "body": body}
        self.repo.put_document(rec)
        return _meta(rec)

    def get(self, doc_id):
        return self.repo.get_document(str(doc_id))

    def get_meta(self, doc_id):
        return self.repo.get_document_meta(str(doc_id))

    def delete(self, doc_id):
        self.repo.delete_document(str(doc_id))


class S3Store:  # pragma: no cover - production seam
    """Production seam — bytes to object storage, metadata to the repo. Wire real
    credentials + an S3 client here; the service never branches on the backend."""

    def __init__(self, repo, *, bucket: str) -> None:
        self.repo = repo
        self.bucket = bucket

    def put(self, *a, **k):
        raise NotImplementedError("S3Store is the production seam — not wired in dev")

    def get(self, doc_id):
        raise NotImplementedError

    def get_meta(self, doc_id):
        return self.repo.get_document_meta(str(doc_id))

    def delete(self, doc_id):
        raise NotImplementedError
