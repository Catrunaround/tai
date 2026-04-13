"""Standalone FastAPI conversion service.

Exposes endpoints:
  POST /convert   — file → markdown (auto-detects file type)
  POST /process   — file → markdown → chunks → store in DB
  GET  /files     — list stored files
  GET  /files/{uuid}         — get file metadata + chunks
  DELETE /files/{uuid}       — remove a file and its chunks

Run with:
  uvicorn file_conversion_router.conversion_api:app --host 0.0.0.0 --port 8010
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from file_conversion_router.conversion.pdf_converter import PdfConverter
from file_conversion_router.conversion.md_converter import MarkdownConverter
from file_conversion_router.conversion.html_converter import HtmlConverter
from file_conversion_router.conversion.video_converter import VideoConverter
from file_conversion_router.conversion.notebook_converter import NotebookConverter
from file_conversion_router.conversion.python_converter import PythonConverter
from file_conversion_router.conversion.rst_converter import RstConverter
from file_conversion_router.conversion.txt_converter import TxtConverter
from file_conversion_router.classes.new_page import Page

logger = logging.getLogger(__name__)

app = FastAPI(title="TAI Conversion Service", version="1.0.0")

# ---------------------------------------------------------------------------
# Extension → Converter mapping
# ---------------------------------------------------------------------------
CONVERTER_MAP = {
    ".pdf":   PdfConverter,
    ".md":    MarkdownConverter,
    ".html":  HtmlConverter,
    ".rst":   RstConverter,
    ".ipynb": NotebookConverter,
    ".py":    PythonConverter,
    ".txt":   TxtConverter,
    ".mp4":   VideoConverter,
    ".mkv":   VideoConverter,
    ".webm":  VideoConverter,
    ".mov":   VideoConverter,
}

# Extensions that need GPU (MinerU for PDF, WhisperX for video)
GPU_EXTENSIONS = {".pdf", ".mp4", ".mkv", ".webm", ".mov"}

# Only one GPU-heavy job at a time (single 4090, ~24 GB VRAM)
_gpu_lock = asyncio.Semaphore(1)

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# ---------------------------------------------------------------------------
# Database — test DB path (override with CONVERSION_DB env var)
# ---------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("CONVERSION_DB", "test_conversion.db"))

SQL_INIT = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS file (
  uuid         TEXT PRIMARY KEY,
  file_hash    TEXT NOT NULL UNIQUE,
  sections     TEXT,
  file_name    TEXT,
  created_at   TIMESTAMP DEFAULT (datetime('now', 'localtime')),
  update_time  TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_uuid     TEXT PRIMARY KEY,
  file_uuid      TEXT NOT NULL,
  idx            INTEGER NOT NULL,
  text           TEXT NOT NULL,
  title          TEXT,
  file_path      TEXT,
  reference_path TEXT,
  chunk_index    INTEGER,
  FOREIGN KEY (file_uuid) REFERENCES file(uuid) ON DELETE CASCADE
);
"""

SQL_UPSERT_FILE = """
INSERT INTO file (uuid, file_hash, sections, file_name)
VALUES (?, ?, ?, ?)
ON CONFLICT(uuid) DO UPDATE SET
  file_hash   = excluded.file_hash,
  sections    = excluded.sections,
  file_name   = excluded.file_name,
  update_time = datetime('now', 'localtime');
"""

SQL_UPSERT_CHUNK = """
INSERT INTO chunks (chunk_uuid, file_uuid, idx, text, title, file_path, reference_path, chunk_index)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(chunk_uuid) DO UPDATE SET
  file_uuid      = excluded.file_uuid,
  idx            = excluded.idx,
  text           = excluded.text,
  title          = excluded.title,
  file_path      = excluded.file_path,
  reference_path = excluded.reference_path,
  chunk_index    = excluded.chunk_index;
"""


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SQL_INIT)
    return conn


@app.on_event("startup")
async def _init_db():
    """Create tables on first launch."""
    conn = _get_db()
    conn.close()
    logger.info(f"Database ready at {DB_PATH.resolve()}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _deterministic_uuid(file_hash: str, file_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{file_hash}:{file_name}"))


def _save_upload(upload: UploadFile, dest_dir: Path) -> tuple[Path, bytes]:
    """Save an uploaded file to *dest_dir* and return (saved_path, raw_bytes)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    content = upload.file.read()
    file_path = dest_dir / upload.filename
    file_path.write_bytes(content)
    return file_path, content


def _list_index_to_page_format(
    raw_index_helper: list,
    md_content: str,
) -> dict:
    """Convert the list-of-dicts index_helper into the dict format Page needs."""
    header_lines: dict[str, int] = {}
    for ln, raw in enumerate(md_content.splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            header_text = stripped.lstrip("#").strip().replace("*", "").strip()
            if header_text and header_text not in header_lines:
                header_lines[header_text] = ln

    result: dict[tuple, tuple] = {}
    for item in raw_index_helper:
        for title, page_idx in item.items():
            line_num = header_lines.get(title)
            result[(title,)] = (page_idx, line_num)
    return result


def _get_converter(suffix: str):
    """Return the converter class for *suffix*, or raise HTTPException."""
    cls = CONVERTER_MAP.get(suffix)
    if cls is None:
        supported = ", ".join(sorted(CONVERTER_MAP))
        raise HTTPException(400, f"Unsupported file type: {suffix}. Supported: {supported}")
    return cls


def _run_to_markdown(
    input_path: Path,
    output_dir: Path,
    file_uuid: str = "",
):
    """Pick the right converter by extension and return (md_path, converter)."""
    suffix = input_path.suffix.lower()
    cls = _get_converter(suffix)
    converter = cls("", "", file_uuid)
    converter.file_name = input_path.name
    output_dir.mkdir(parents=True, exist_ok=True)
    md_output_path = output_dir / f"{input_path.stem}.md"
    md_path = converter._to_markdown(input_path, md_output_path)
    return md_path, converter


# ---------------------------------------------------------------------------
# POST /convert  —  pure file → markdown
# ---------------------------------------------------------------------------

@app.post("/convert")
async def convert_file(
    file: UploadFile = File(...),
):
    """Convert a file to markdown. Auto-detects file type by extension."""
    suffix = Path(file.filename).suffix.lower()
    _get_converter(suffix)  # validates extension

    tmp_dir = Path(tempfile.mkdtemp(prefix="tai_convert_"))
    try:
        input_path, raw = _save_upload(file, tmp_dir / "input")
        output_dir = tmp_dir / "output"

        if suffix in GPU_EXTENSIONS:
            async with _gpu_lock:
                md_path, _ = await asyncio.to_thread(
                    _run_to_markdown, input_path, output_dir
                )
        else:
            md_path, _ = _run_to_markdown(input_path, output_dir)

        if md_path is None or not Path(md_path).exists():
            raise HTTPException(500, "Conversion failed — no markdown output produced")

        md_content = Path(md_path).read_text(encoding="utf-8")

        return JSONResponse({
            "file_name": file.filename,
            "md_content": md_content,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Conversion failed")
        raise HTTPException(500, f"Conversion error: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# POST /process  —  file → markdown → chunks → DB
# ---------------------------------------------------------------------------

@app.post("/process")
async def process_file(
    file: UploadFile = File(...),
):
    """Convert, chunk, store in DB, and return chunks JSON."""
    suffix = Path(file.filename).suffix.lower()
    _get_converter(suffix)  # validates extension

    tmp_dir = Path(tempfile.mkdtemp(prefix="tai_process_"))
    try:
        input_path, raw = _save_upload(file, tmp_dir / "input")
        fhash = _file_hash(raw)
        file_uuid = _deterministic_uuid(fhash, file.filename)
        output_dir = tmp_dir / "output"

        # Step 1: Convert to markdown
        if suffix in GPU_EXTENSIONS:
            async with _gpu_lock:
                md_path, converter = await asyncio.to_thread(
                    _run_to_markdown, input_path, output_dir, file_uuid
                )
        else:
            md_path, converter = _run_to_markdown(
                input_path, output_dir, file_uuid
            )

        if md_path is None or not Path(md_path).exists():
            raise HTTPException(500, "Conversion failed — no markdown output produced")

        md_content = Path(md_path).read_text(encoding="utf-8")

        # Step 2: Build index_helper in the dict format Page expects
        if converter.index_helper is None:
            from file_conversion_router.conversion.base_converter import BaseConverter
            BaseConverter.generate_index_helper(converter, md_content)

        page_index_helper = _list_index_to_page_format(
            converter.index_helper, md_content
        )

        # Step 3: Create Page and chunk
        page = Page(
            filetype=suffix.lstrip("."),
            content={"text": md_content},
            page_name=file.filename,
            page_url="",
            index_helper=page_index_helper,
            file_path=file.filename,
            file_uuid=file_uuid,
        )
        chunks = page.to_chunk()

        # Step 4: Serialize chunks
        chunks_json = []
        for i, chunk in enumerate(chunks):
            chunks_json.append({
                "content": chunk.content,
                "titles": chunk.titles,
                "chunk_uuid": chunk.chunk_uuid or str(uuid.uuid4()),
                "reference_path": str(chunk.reference_path) if chunk.reference_path else "",
                "file_path": str(chunk.file_path) if chunk.file_path else file.filename,
                "file_uuid": file_uuid,
                "chunk_index": chunk.chunk_index if chunk.chunk_index is not None else i,
            })

        # Step 5: Build sections
        sections = []
        if isinstance(converter.index_helper, dict):
            for path_key, value in converter.index_helper.items():
                title = path_key[-1] if isinstance(path_key, tuple) else str(path_key)
                sections.append({"title": title, "path": list(path_key) if isinstance(path_key, tuple) else [str(path_key)]})
        elif isinstance(converter.index_helper, list):
            for item in converter.index_helper:
                for title, idx in item.items():
                    sections.append({"title": title, "index": idx})

        # Step 6: Store in database
        conn = _get_db()
        try:
            conn.execute(SQL_UPSERT_FILE, (
                file_uuid, fhash, json.dumps(sections), file.filename,
            ))
            # Remove old chunks before inserting (chunk UUIDs are non-deterministic)
            conn.execute("DELETE FROM chunks WHERE file_uuid = ?", (file_uuid,))
            for i, cj in enumerate(chunks_json):
                titles = cj["titles"]
                if isinstance(titles, (list, tuple)):
                    titles = json.dumps(titles)
                file_path = cj["file_path"]
                if isinstance(file_path, (list, tuple)):
                    file_path = str(file_path[0]) if file_path else ""
                ref_path = cj["reference_path"]
                if isinstance(ref_path, (list, tuple)):
                    ref_path = str(ref_path[0]) if ref_path else ""
                conn.execute(SQL_UPSERT_CHUNK, (
                    cj["chunk_uuid"], file_uuid, i, cj["content"],
                    titles, file_path, ref_path, cj["chunk_index"],
                ))
            conn.commit()
        finally:
            conn.close()

        return JSONResponse({
            "file_uuid": file_uuid,
            "file_name": file.filename,
            "chunks": chunks_json,
            "sections": sections,
            "total_chunks": len(chunks_json),
            "stored": True,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Processing failed")
        raise HTTPException(500, f"Processing error: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GET /files  —  list all stored files
# ---------------------------------------------------------------------------

@app.get("/files")
async def list_files():
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT uuid, file_name, file_hash, sections, created_at, update_time FROM file ORDER BY update_time DESC"
        ).fetchall()
        files = []
        for r in rows:
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE file_uuid = ?", (r["uuid"],)
            ).fetchone()[0]
            files.append({
                "file_uuid": r["uuid"],
                "file_name": r["file_name"],
                "file_hash": r["file_hash"],
                "sections": json.loads(r["sections"]) if r["sections"] else [],
                "chunk_count": chunk_count,
                "created_at": r["created_at"],
                "update_time": r["update_time"],
            })
        return JSONResponse({"files": files, "total": len(files)})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GET /files/{file_uuid}  —  file detail with chunks
# ---------------------------------------------------------------------------

@app.get("/files/{file_uuid}")
async def get_file(file_uuid: str):
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT uuid, file_name, file_hash, sections, created_at, update_time FROM file WHERE uuid = ?",
            (file_uuid,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"File not found: {file_uuid}")

        chunks = conn.execute(
            "SELECT chunk_uuid, idx, text, title, file_path, reference_path, chunk_index FROM chunks WHERE file_uuid = ? ORDER BY idx",
            (file_uuid,),
        ).fetchall()

        return JSONResponse({
            "file_uuid": row["uuid"],
            "file_name": row["file_name"],
            "file_hash": row["file_hash"],
            "sections": json.loads(row["sections"]) if row["sections"] else [],
            "created_at": row["created_at"],
            "update_time": row["update_time"],
            "chunks": [
                {
                    "chunk_uuid": c["chunk_uuid"],
                    "idx": c["idx"],
                    "text": c["text"],
                    "title": c["title"],
                    "file_path": c["file_path"],
                    "chunk_index": c["chunk_index"],
                }
                for c in chunks
            ],
            "total_chunks": len(chunks),
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DELETE /files/{file_uuid}  —  remove file and chunks
# ---------------------------------------------------------------------------

@app.delete("/files/{file_uuid}")
async def delete_file(file_uuid: str):
    conn = _get_db()
    try:
        row = conn.execute("SELECT uuid FROM file WHERE uuid = ?", (file_uuid,)).fetchone()
        if row is None:
            raise HTTPException(404, f"File not found: {file_uuid}")
        conn.execute("DELETE FROM file WHERE uuid = ?", (file_uuid,))
        conn.commit()
        return JSONResponse({"deleted": file_uuid})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    conn = _get_db()
    try:
        file_count = conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    return {
        "status": "ok",
        "service": "tai-conversion",
        "version": "1.0.0",
        "db_path": str(DB_PATH.resolve()),
        "files": file_count,
        "chunks": chunk_count,
    }
