"""Tests for the standalone conversion API (file_conversion_router.conversion_api).

Uses FastAPI's TestClient with mocked converters to avoid needing
real MinerU/OCR/WhisperX backends. Each test gets an isolated test DB.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


@pytest.fixture(autouse=True)
def _test_db(tmp_path, monkeypatch):
    """Point the API at a fresh throwaway DB for every test."""
    db_path = tmp_path / "test_conversion.db"
    monkeypatch.setenv("CONVERSION_DB", str(db_path))
    # Reload DB_PATH in the module
    import file_conversion_router.conversion_api as mod
    monkeypatch.setattr(mod, "DB_PATH", db_path)


@pytest.fixture()
def client():
    from file_conversion_router.conversion_api import app
    return TestClient(app)


@pytest.fixture()
def sample_pdf(tmp_path) -> Path:
    """Create a minimal PDF with known content."""
    pdf_path = tmp_path / "test_doc.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 700, "Introduction")
    c.setFont("Helvetica", 12)
    c.drawString(72, 670, "This is a test document for conversion API testing.")
    c.showPage()
    c.save()
    return pdf_path


def _fake_pdf_to_markdown(self, input_path, output_path, conversion_method="MinerU"):
    """Stub that writes a simple markdown file instead of running MinerU."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = output_path.parent / f"{input_path.name}.md"
    md_path.write_text("# Introduction\n\nConverted content.", encoding="utf-8")
    cl_path = md_path.with_name(f"{md_path.stem}_content_list.json")
    cl_path.write_text(
        json.dumps([{"type": "text", "text": "# Introduction", "text_level": 1, "page_idx": 0}]),
        encoding="utf-8",
    )
    self.index_helper = [{"Introduction": 1}]
    return md_path


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["files"] == 0
    assert data["chunks"] == 0


# ---------------------------------------------------------------------------
# POST /convert
# ---------------------------------------------------------------------------


def test_convert_rejects_unsupported_extension(client, tmp_path):
    docx = tmp_path / "notes.docx"
    docx.write_bytes(b"\x00" * 10)
    with open(docx, "rb") as f:
        resp = client.post("/convert", files={"file": ("notes.docx", f, "application/octet-stream")})
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    _fake_pdf_to_markdown,
)
def test_convert_pdf(client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        resp = client.post("/convert", files={"file": ("test_doc.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"file_name", "md_content"}
    assert data["file_name"] == "test_doc.pdf"
    assert "# Introduction" in data["md_content"]


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    return_value=None,
)
def test_convert_returns_500_when_no_md_produced(mock_tm, client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        resp = client.post("/convert", files={"file": ("test_doc.pdf", f, "application/pdf")})
    assert resp.status_code == 500
    assert "no markdown output" in resp.json()["detail"]


def test_convert_markdown(client, tmp_path):
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Hello\n\nWorld", encoding="utf-8")
    with open(md_file, "rb") as f:
        resp = client.post("/convert", files={"file": ("notes.md", f, "text/markdown")})
    assert resp.status_code == 200
    assert "# Hello" in resp.json()["md_content"]


def test_convert_python(client, tmp_path):
    py_file = tmp_path / "example.py"
    py_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    with open(py_file, "rb") as f:
        resp = client.post("/convert", files={"file": ("example.py", f, "text/x-python")})
    assert resp.status_code == 200
    assert "hello" in resp.json()["md_content"]


def test_convert_txt(client, tmp_path):
    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("Some plain text content.", encoding="utf-8")
    with open(txt_file, "rb") as f:
        resp = client.post("/convert", files={"file": ("readme.txt", f, "text/plain")})
    assert resp.status_code == 200
    assert "plain text" in resp.json()["md_content"]


# ---------------------------------------------------------------------------
# POST /process — stores to DB
# ---------------------------------------------------------------------------


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    _fake_pdf_to_markdown,
)
def test_process_stores_to_db(client, sample_pdf):
    # Process a file
    with open(sample_pdf, "rb") as f:
        resp = client.post("/process", files={"file": ("test_doc.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["stored"] is True
    file_uuid = data["file_uuid"]

    # Verify via /files
    resp = client.get("/files")
    assert resp.status_code == 200
    files = resp.json()
    assert files["total"] == 1
    assert files["files"][0]["file_uuid"] == file_uuid
    assert files["files"][0]["chunk_count"] == data["total_chunks"]

    # Verify via /files/{uuid}
    resp = client.get(f"/files/{file_uuid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["file_name"] == "test_doc.pdf"
    assert detail["total_chunks"] == data["total_chunks"]
    assert len(detail["chunks"]) == data["total_chunks"]
    for chunk in detail["chunks"]:
        assert chunk["text"]  # non-empty content


def test_process_rejects_unsupported_extension(client, tmp_path):
    docx = tmp_path / "notes.docx"
    docx.write_bytes(b"\x00" * 10)
    with open(docx, "rb") as f:
        resp = client.post("/process", files={"file": ("notes.docx", f, "application/octet-stream")})
    assert resp.status_code == 400


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    return_value=None,
)
def test_process_returns_500_when_no_md_produced(mock_tm, client, sample_pdf):
    with open(sample_pdf, "rb") as f:
        resp = client.post("/process", files={"file": ("test_doc.pdf", f, "application/pdf")})
    assert resp.status_code == 500


def test_process_markdown_stores_to_db(client, tmp_path):
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Section\n\nSome content here.", encoding="utf-8")
    with open(md_file, "rb") as f:
        resp = client.post("/process", files={"file": ("notes.md", f, "text/markdown")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["stored"] is True
    assert data["total_chunks"] >= 1

    # Health check should reflect the stored data
    health = client.get("/health").json()
    assert health["files"] == 1
    assert health["chunks"] >= 1


# ---------------------------------------------------------------------------
# DELETE /files/{uuid}
# ---------------------------------------------------------------------------


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    _fake_pdf_to_markdown,
)
def test_delete_file(client, sample_pdf):
    # Store a file
    with open(sample_pdf, "rb") as f:
        resp = client.post("/process", files={"file": ("test_doc.pdf", f, "application/pdf")})
    file_uuid = resp.json()["file_uuid"]

    # Delete it
    resp = client.delete(f"/files/{file_uuid}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == file_uuid

    # Confirm it's gone
    resp = client.get(f"/files/{file_uuid}")
    assert resp.status_code == 404

    resp = client.get("/files")
    assert resp.json()["total"] == 0


def test_delete_nonexistent_file(client):
    resp = client.delete("/files/nonexistent-uuid")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /files/{uuid} — 404
# ---------------------------------------------------------------------------


def test_get_nonexistent_file(client):
    resp = client.get("/files/nonexistent-uuid")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Deterministic UUID — re-uploading same file updates, not duplicates
# ---------------------------------------------------------------------------


@patch(
    "file_conversion_router.conversion_api.PdfConverter._to_markdown",
    _fake_pdf_to_markdown,
)
def test_reupload_same_file_upserts(client, sample_pdf):
    """Uploading the same file twice should upsert, not create duplicates."""
    for _ in range(2):
        with open(sample_pdf, "rb") as f:
            resp = client.post("/process", files={"file": ("test_doc.pdf", f, "application/pdf")})
        assert resp.status_code == 200

    files = client.get("/files").json()
    assert files["total"] == 1  # only one file, not two
