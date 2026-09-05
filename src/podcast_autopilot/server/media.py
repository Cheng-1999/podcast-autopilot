"""Serves files under out/<episode>/ and media/<episode>/ with HTTP Range
support (206 partial content), so the dashboard's <audio>/<video> elements can
seek without downloading the whole file. Path traversal is rejected by
resolving the requested path and checking it is still inside the base dir."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

CHUNK_SIZE = 1024 * 1024


def resolve_media_path(project_root: Path, episode_id: str, rel_path: str) -> Optional[Path]:
    if not rel_path or ".." in Path(rel_path).parts:
        return None
    for base_name in ("out", "media"):
        base = project_root / base_name / episode_id
        try:
            base_resolved = base.resolve()
            target = (base / rel_path).resolve()
        except OSError:
            continue
        if not target.is_relative_to(base_resolved):
            continue
        if target.is_file():
            return target
    return None


def parse_range_header(range_header: Optional[str], file_size: int) -> Optional[tuple[int, int]]:
    """Parse a single-range `Range: bytes=start-end` header. Returns None if
    absent, malformed, multi-range, or unsatisfiable."""
    if not range_header or not range_header.startswith("bytes=") or file_size <= 0:
        return None
    spec = range_header[len("bytes="):].strip()
    if "," in spec:
        return None  # multi-range not supported; caller falls back to a full 200
    start_str, _, end_str = spec.partition("-")
    try:
        if start_str == "":
            if end_str == "":
                return None
            suffix_length = int(end_str)
            if suffix_length <= 0:
                return None
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str != "" else file_size - 1
    except ValueError:
        return None
    end = min(end, file_size - 1)
    if start < 0 or start > end:
        return None
    return start, end


def iter_file_range(path: Path, start: int, end: int, chunk_size: int = CHUNK_SIZE):
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"
