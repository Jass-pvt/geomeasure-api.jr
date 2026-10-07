import hashlib
from dataclasses import dataclass

from fastapi import UploadFile

from app.config import Settings
from app.core.exceptions import EmptyFileError, FileTooLargeError
from app.core.security import detect_file_kind, sanitize_filename
from app.models.enums import FileKind

READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class IngestedFile:
    filename: str
    kind: FileKind
    content: bytes
    size_bytes: int
    sha256: str


async def ingest_upload(upload: UploadFile, settings: Settings) -> IngestedFile:
    """Validate name and size, and compute SHA-256 while streaming the upload once."""
    filename = sanitize_filename(upload.filename)
    kind = detect_file_kind(filename)

    digest = hashlib.sha256()
    buffer = bytearray()
    while chunk := await upload.read(READ_CHUNK_BYTES):
        if len(buffer) + len(chunk) > settings.max_upload_bytes:
            raise FileTooLargeError(
                f"The uploaded file exceeds the maximum size of {settings.max_upload_mb} MB."
            )
        buffer.extend(chunk)
        digest.update(chunk)

    if not buffer:
        raise EmptyFileError()

    return IngestedFile(
        filename=filename,
        kind=kind,
        content=bytes(buffer),
        size_bytes=len(buffer),
        sha256=digest.hexdigest(),
    )
