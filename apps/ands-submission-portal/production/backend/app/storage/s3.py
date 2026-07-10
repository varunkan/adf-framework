from __future__ import annotations

import json
from datetime import datetime, timezone

import boto3
from botocore.client import Config


class PackageStorage:
    """S3-compatible object store for eCTD package artifacts."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )
        self.ensure_bucket()

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            self._client.create_bucket(Bucket=self._bucket)

    def put_package_manifest(
        self, dossier_id: str, sequence: str, manifest: dict
    ) -> str:
        key = (
            f"packages/{dossier_id}/{sequence}/"
            f"manifest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        body = json.dumps(manifest, indent=2).encode("utf-8")
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return key
