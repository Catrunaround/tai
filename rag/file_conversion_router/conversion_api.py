"""Standalone FastAPI conversion service.

Exposes two endpoints:
  POST /convert  — pure file → markdown conversion (output stays on disk)
  POST /process  — file → markdown → chunks JSON (no embedding, no DB writes)

Run with:
  uvicorn file_conversion_router.conversion_api:app --host 0.0.0.0 --port 8010
"""

import hashlib
import json
import logging
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from file_conversion_router.conversion.pdf_converter import PdfConverter
from file_conversion_router.classes.new_page import Page

logger = logging.getLogger(__name__)

app = FastAPI(title="TAI Conversion Service", version="1.0.0")

# ---------------------------------------------------------------------------
# Allowed extensions for MVP (PDF only, extensible later)
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {".pdf"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


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


def _run_to_markdown(
    input_path: Path,
    output_dir: Path,
    course_name: str,
    course_code: str,
    file_uuid: str,
):
    """Run _to_markdown for a PDF and return (md_path, converter)."""
    converter = PdfConverter(course_name, course_code, file_uuid)
    converter.file_name = input_path.name
    md_output_path = output_dir / f"{input_path.name}.md"
    md_path = converter._to_markdown(input_path, md_output_path)
    return md_path, converter


# ---------------------------------------------------------------------------
# POST /convert  —  pure file → markdown
# ---------------------------------------------------------------------------

@app.post("/convert")
async def convert_file(
    file: UploadFile = File(...),
    course_code: str = Form(""),
    course_name: str = Form(""),
):
    """Convert a file to markdown. Returns markdown content + file path on disk."""
    # Validate extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Allowed: {ALLOWED_EXTENSIONS}")

    # Save to temp dir
    tmp_dir = Path(tempfile.mkdtemp(prefix="tai_convert_"))
    try:
        input_path, raw = _save_upload(file, tmp_dir / "input")
        fhash = _file_hash(raw)
        file_uuid = _deterministic_uuid(fhash, file.filename)
        output_dir = tmp_dir / "output"

        if not course_name:
            course_name = course_code

        md_path, converter = _run_to_markdown(
            input_path, output_dir, course_name, course_code, file_uuid
        )

        if md_path is None or not Path(md_path).exists():
            raise HTTPException(500, "Conversion failed — no markdown output produced")

        md_content = Path(md_path).read_text(encoding="utf-8")

        # Read content_list if present (MinerU generates this alongside the md)
        content_list = None
        content_list_path = Path(md_path).with_name(
            f"{Path(md_path).stem}_content_list.json"
        )
        if content_list_path.exists():
            with open(content_list_path, "r", encoding="utf-8") as f:
                content_list = json.load(f)

        return JSONResponse({
            "file_name": file.filename,
            "file_uuid": file_uuid,
            "md_content": md_content,
            "md_file_path": str(md_path),
            "content_list": content_list,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Conversion failed")
        raise HTTPException(500, f"Conversion error: {e}")


# ---------------------------------------------------------------------------
# POST /process  —  file → markdown → chunks (no embedding)
# ---------------------------------------------------------------------------

@app.post("/process")
async def process_file(
    file: UploadFile = File(...),
    course_code: str = Form(""),
    course_name: str = Form(""),
):
    """Convert a file to markdown, chunk it, and return chunks JSON (no embedding)."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Allowed: {ALLOWED_EXTENSIONS}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tai_process_"))
    try:
        input_path, raw = _save_upload(file, tmp_dir / "input")
        fhash = _file_hash(raw)
        file_uuid = _deterministic_uuid(fhash, file.filename)
        output_dir = tmp_dir / "output"

        if not course_name:
            course_name = course_code

        # Step 1: Convert to markdown
        md_path, converter = _run_to_markdown(
            input_path, output_dir, course_name, course_code, file_uuid
        )

        if md_path is None or not Path(md_path).exists():
            raise HTTPException(500, "Conversion failed — no markdown output produced")

        md_content = Path(md_path).read_text(encoding="utf-8")

        # Step 2: Build index_helper from markdown headers (fast, no OpenAI)
        converter.generate_index_helper(md_content)

        # Step 3: Create Page and chunk
        page = Page(
            course_name=course_name,
            course_code=course_code,
            filetype=suffix.lstrip("."),
            content={"text": md_content},
            page_name=file.filename,
            page_url="",
            index_helper=converter.index_helper,
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
                "reference_path": chunk.reference_path or "",
                "file_path": chunk.file_path or file.filename,
                "file_uuid": file_uuid,
                "chunk_index": chunk.chunk_index if chunk.chunk_index is not None else i,
                "course_code": course_code,
                "course_name": course_name,
            })

        # Read sections from index_helper
        sections = []
        if isinstance(converter.index_helper, dict):
            for path_key, value in converter.index_helper.items():
                title = path_key[-1] if isinstance(path_key, tuple) else str(path_key)
                sections.append({"title": title, "path": list(path_key) if isinstance(path_key, tuple) else [str(path_key)]})
        elif isinstance(converter.index_helper, list):
            for item in converter.index_helper:
                for title, idx in item.items():
                    sections.append({"title": title, "index": idx})

        return JSONResponse({
            "file_uuid": file_uuid,
            "file_name": file.filename,
            "chunks": chunks_json,
            "sections": sections,
            "total_chunks": len(chunks_json),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Processing failed")
        raise HTTPException(500, f"Processing error: {e}")
    finally:
        # Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "tai-conversion", "version": "1.0.0"}
