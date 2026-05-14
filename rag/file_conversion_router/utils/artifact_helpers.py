"""Shared helpers for building converter artifact dicts and archive path lists."""
import base64
import json
import mimetypes
from pathlib import Path


def json_attachment(path: Path) -> dict | None:
    if not path or not path.exists():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        content = path.read_text(encoding="utf-8")
    return {"file_name": path.name, "content_type": "application/json", "content": content}


def binary_attachment(path: Path, include_content: bool = False) -> dict:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    item = {
        "file_name": path.name,
        "content_type": content_type,
        "size_bytes": path.stat().st_size,
    }
    if include_content:
        item["content_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return item


def iter_image_files(directory: Path):
    if not directory or not directory.exists() or not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            yield path
