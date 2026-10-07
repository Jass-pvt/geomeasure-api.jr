import re
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.config import Settings
from app.core.exceptions import (
    InvalidArchiveError,
    InvalidRequestError,
    UnsupportedFileTypeError,
)
from app.models.enums import FileKind

SUPPORTED_EXTENSIONS: dict[str, FileKind] = {
    ".kml": FileKind.KML,
    ".zip": FileKind.SHAPEFILE_ZIP,
}
MAX_FILENAME_LENGTH = 255
EXTRACT_CHUNK_BYTES = 64 * 1024
ZIP_ENCRYPTED_FLAG = 0x1
MACOS_METADATA_DIR = "__MACOSX/"
MACOS_RESOURCE_PREFIX = "._"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(raw: str | None) -> str:
    """Keep only the final path component and drop control characters (log-injection safe)."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    return _CONTROL_CHARS.sub("", name).strip()[:MAX_FILENAME_LENGTH]


def detect_file_kind(filename: str) -> FileKind:
    if not filename:
        raise InvalidRequestError("The uploaded file has no filename.")
    kind = SUPPORTED_EXTENSIONS.get(PurePosixPath(filename).suffix.lower())
    if kind is None:
        raise UnsupportedFileTypeError()
    return kind


def is_safe_archive_path(name: str) -> bool:
    """Reject empty, absolute, drive-qualified and parent-traversing archive entry names."""
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(name).drive:
        return False
    return ".." not in PurePosixPath(normalized).parts


def is_archive_metadata_entry(info: zipfile.ZipInfo) -> bool:
    name = info.filename.replace("\\", "/")
    basename = name.rsplit("/", 1)[-1]
    return name.startswith(MACOS_METADATA_DIR) or basename.startswith(MACOS_RESOURCE_PREFIX)


def validate_archive_entries(archive: zipfile.ZipFile, settings: Settings) -> list[zipfile.ZipInfo]:
    """Check entry count, names, encryption, symlinks and declared uncompressed size."""
    infos = archive.infolist()
    if len(infos) > settings.max_zip_files:
        raise InvalidArchiveError(
            f"The archive contains more than the allowed {settings.max_zip_files} entries."
        )
    declared_size = 0
    for info in infos:
        if not is_safe_archive_path(info.filename):
            raise InvalidArchiveError("The archive contains an unsafe file path.")
        if info.flag_bits & ZIP_ENCRYPTED_FLAG:
            raise InvalidArchiveError("Encrypted archives are not supported.")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidArchiveError("The archive contains a symbolic link.")
        declared_size += info.file_size
    if declared_size > settings.max_zip_uncompressed_bytes:
        raise InvalidArchiveError(
            "The archive expands beyond the allowed "
            f"{settings.max_zip_uncompressed_mb} MB uncompressed size."
        )
    return infos


def extract_archive(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    destination: Path,
    max_total_bytes: int,
) -> None:
    """Extract validated entries, re-checking containment and counting bytes actually written.

    Declared sizes in a ZIP header can lie, so the real number of bytes is enforced while copying.
    """
    root = destination.resolve()
    written = 0
    for info in infos:
        if info.is_dir():
            continue
        target = (root / info.filename.replace("\\", "/")).resolve()
        if not target.is_relative_to(root):
            raise InvalidArchiveError("The archive contains an unsafe file path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as sink:
            while chunk := source.read(EXTRACT_CHUNK_BYTES):
                written += len(chunk)
                if written > max_total_bytes:
                    raise InvalidArchiveError("The archive expands beyond the allowed size.")
                sink.write(chunk)
