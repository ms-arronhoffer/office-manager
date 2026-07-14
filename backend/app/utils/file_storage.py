"""Pluggable file-storage backend for uploaded attachments.

The application historically stored every uploaded file on local disk under
``settings.UPLOAD_DIR``. That works for a single backend instance but breaks
as soon as more than one instance/AZ is involved (autoscaling, multi-AZ
deploys) because each instance would only see its own local files.

This module abstracts "save/read/delete/serve" behind ``settings.STORAGE_BACKEND``:

- ``local`` (default): unchanged behaviour, files under ``UPLOAD_DIR``. Used
  in local development and the existing single-VPS docker-compose deploy.
- ``s3``: files are stored in ``settings.S3_UPLOAD_BUCKET`` under
  ``settings.S3_UPLOAD_PREFIX``. Used by the AWS deployment (see
  ``docs/aws-deployment.md``) so any number of stateless backend replicas can
  share the same uploaded-file corpus.

Callers should not construct paths under ``UPLOAD_DIR`` directly; use the
functions below instead so the storage backend can be swapped via config.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import FileResponse, Response

from app.config import settings

logger = logging.getLogger("app.file_storage")

_s3_client: Any = None


def is_s3_backend() -> bool:
    return settings.STORAGE_BACKEND.strip().lower() == "s3"


def _local_dir(entity_type: str) -> Path:
    p = Path(settings.UPLOAD_DIR) / entity_type
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3  # imported lazily so boto3 is only required when S3 is used

        _s3_client = boto3.client("s3", region_name=settings.AWS_REGION or None)
    return _s3_client


def _s3_key(entity_type: str, stored_filename: str) -> str:
    prefix = settings.S3_UPLOAD_PREFIX.strip("/")
    key = f"{entity_type}/{stored_filename}"
    return f"{prefix}/{key}" if prefix else key


def save_file(entity_type: str, stored_filename: str, content: bytes) -> None:
    """Persist ``content`` under ``entity_type``/``stored_filename``."""
    if is_s3_backend():
        client = _get_s3_client()
        client.put_object(
            Bucket=settings.S3_UPLOAD_BUCKET,
            Key=_s3_key(entity_type, stored_filename),
            Body=content,
        )
    else:
        dest = _local_dir(entity_type) / stored_filename
        dest.write_bytes(content)


def read_file(entity_type: str, stored_filename: str) -> bytes:
    """Return the raw bytes for a stored file.

    Raises ``FileNotFoundError`` if the file does not exist, regardless of
    backend, so callers can handle both backends identically.
    """
    if is_s3_backend():
        client = _get_s3_client()
        try:
            obj = client.get_object(
                Bucket=settings.S3_UPLOAD_BUCKET,
                Key=_s3_key(entity_type, stored_filename),
            )
        except client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(stored_filename) from exc
        except Exception as exc:  # noqa: BLE001 - botocore raises generic ClientError
            error_code = getattr(getattr(exc, "response", {}), "get", lambda *_: None)("Error", {})
            if isinstance(error_code, dict) and error_code.get("Code") in {"NoSuchKey", "404"}:
                raise FileNotFoundError(stored_filename) from exc
            raise
        return obj["Body"].read()

    path = _local_dir(entity_type) / stored_filename
    if not path.exists():
        raise FileNotFoundError(stored_filename)
    return path.read_bytes()


def file_exists(entity_type: str, stored_filename: str) -> bool:
    try:
        read_file(entity_type, stored_filename)
        return True
    except FileNotFoundError:
        return False


def delete_file(entity_type: str, stored_filename: str) -> None:
    """Best-effort delete; never raises (mirrors previous local-disk behaviour)."""
    if is_s3_backend():
        try:
            client = _get_s3_client()
            client.delete_object(
                Bucket=settings.S3_UPLOAD_BUCKET,
                Key=_s3_key(entity_type, stored_filename),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to delete S3 object %s/%s", entity_type, stored_filename)
    else:
        path = _local_dir(entity_type) / stored_filename
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def build_download_response(
    entity_type: str,
    stored_filename: str,
    *,
    filename: str,
    media_type: str,
) -> Response:
    """Build a FastAPI response that streams the stored file to the client."""
    if is_s3_backend():
        try:
            content = read_file(entity_type, stored_filename)
        except FileNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    path = _local_dir(entity_type) / stored_filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return FileResponse(path=str(path), filename=filename, media_type=media_type)
