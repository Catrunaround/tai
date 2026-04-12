"""Tests for the upgraded MinerU OCR integration.

Verifies that the new MinerU version produces all expected output files
in the correct directory structure, and that the pdf_converter integrates
correctly with the new layout.
"""

import json
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> Path:
    """Create a minimal 2-page PDF with known headings and body text."""
    pdf_dir = tmp_path_factory.mktemp("pdf_input")
    pdf_path = pdf_dir / "test_mineru.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)

    # Page 1
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 700, "Introduction")
    c.setFont("Helvetica", 12)
    c.drawString(72, 670, "This is the first page of a test document.")
    c.drawString(72, 650, "It contains sample text for MinerU OCR testing.")
    c.showPage()

    # Page 2
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 700, "Methodology")
    c.setFont("Helvetica", 12)
    c.drawString(72, 670, "This is the second page with a different heading.")
    c.drawString(72, 650, "Additional content for structural verification.")
    c.showPage()

    c.save()
    return pdf_path


# ---------------------------------------------------------------------------
# Test 1: Raw MinerU output structure
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_parse_doc_output_structure(sample_pdf, tmp_path):
    """Verify parse_doc produces files in the new directory layout."""
    from file_conversion_router.services.tai_MinerU_service.utils.convert import parse_doc

    output_folder = tmp_path / "mineru_output"
    method = "auto"
    file_name = sample_pdf.name  # "test_mineru.pdf"

    md_path = parse_doc(
        pdf_path=sample_pdf,
        output_folder=output_folder,
        lang="en",
        backend="pipeline",
        method=method,
    )

    # -- Directory structure --
    expected_dir = output_folder / file_name / method
    assert expected_dir.is_dir(), f"Expected subdirectory not created: {expected_dir}"

    # -- Markdown file --
    assert md_path == expected_dir / f"{file_name}.md"
    assert md_path.exists(), f"Markdown file missing: {md_path}"
    assert md_path.stat().st_size > 0, "Markdown file is empty"

    # -- content_list.json --
    content_list_path = expected_dir / f"{file_name}_content_list.json"
    assert content_list_path.exists(), f"content_list.json missing: {content_list_path}"
    with open(content_list_path, "r", encoding="utf-8") as f:
        content_list = json.load(f)
    assert isinstance(content_list, list), "content_list.json should be a list"
    assert len(content_list) > 0, "content_list.json should not be empty"

    # Verify item schema: every item must have 'type' and 'page_idx'
    for item in content_list:
        assert "type" in item, f"content_list item missing 'type': {item}"
        assert "page_idx" in item, f"content_list item missing 'page_idx': {item}"

    # Verify page_idx values span at least 2 pages (0-indexed)
    page_indices = {item["page_idx"] for item in content_list}
    assert len(page_indices) >= 2, (
        f"Expected content from at least 2 pages, got page indices: {page_indices}"
    )

    # -- middle.json --
    middle_path = expected_dir / f"{file_name}_middle.json"
    assert middle_path.exists(), f"middle.json missing: {middle_path}"
    with open(middle_path, "r", encoding="utf-8") as f:
        middle = json.load(f)
    assert isinstance(middle, dict), "middle.json should be a dict"
    assert "pdf_info" in middle, "middle.json missing 'pdf_info' key"

    # -- model.json --
    model_path = expected_dir / f"{file_name}_model.json"
    assert model_path.exists(), f"model.json missing: {model_path}"

    # -- images directory --
    images_dir = expected_dir / "images"
    assert images_dir.is_dir(), f"images/ directory missing: {images_dir}"


# ---------------------------------------------------------------------------
# Test 2: PdfConverter integration
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_pdf_converter_integration(sample_pdf, tmp_path):
    """Verify PdfConverter._to_markdown integrates with the new MinerU output layout."""
    from file_conversion_router.conversion.pdf_converter import PdfConverter

    converter = PdfConverter(
        course_name="Test Course",
        course_code="TEST101",
    )

    output_dir = tmp_path / "converter_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    # _to_markdown uses output_path.parent as the output_dir for MinerU
    output_path = output_dir / f"{sample_pdf.name}.md"

    md_path = converter._to_markdown(
        input_path=sample_pdf,
        output_path=output_path,
        conversion_method="MinerU",
    )

    # -- Returned path is valid --
    assert md_path is not None, "_to_markdown returned None"
    assert isinstance(md_path, Path), f"Expected Path, got {type(md_path)}"
    assert md_path.exists(), f"Returned md path does not exist: {md_path}"

    # -- Markdown content is non-empty --
    md_content = md_path.read_text(encoding="utf-8")
    assert len(md_content.strip()) > 0, "Markdown content is empty or whitespace"

    # -- content_list.json accessible via with_name (same logic as pdf_converter.py) --
    json_file_path = md_path.with_name(f"{md_path.stem}_content_list.json")
    assert json_file_path.exists(), (
        f"content_list.json not found via with_name: {json_file_path}"
    )
    with open(json_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list), "content_list.json should be a list"

    # -- index_helper is populated --
    assert converter.index_helper is not None, "index_helper was not set"
    assert isinstance(converter.index_helper, list), (
        f"index_helper should be a list, got {type(converter.index_helper)}"
    )

    # Each entry should be a dict mapping title -> page_idx (1-based)
    for entry in converter.index_helper:
        assert isinstance(entry, dict), f"index_helper entry should be a dict: {entry}"
        assert len(entry) == 1, f"index_helper entry should have exactly 1 key: {entry}"
        title = list(entry.keys())[0]
        page_idx = list(entry.values())[0]
        assert isinstance(title, str), f"Title should be str: {title}"
        assert isinstance(page_idx, int), f"Page index should be int: {page_idx}"
        assert page_idx >= 1, f"Page index should be >= 1 (1-based): {page_idx}"


# ---------------------------------------------------------------------------
# Test 3: Markdown quality
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_markdown_quality(sample_pdf, tmp_path):
    """Verify the markdown output has reasonable content quality."""
    from file_conversion_router.services.tai_MinerU_service.utils.convert import parse_doc

    output_folder = tmp_path / "quality_output"
    md_path = parse_doc(
        pdf_path=sample_pdf,
        output_folder=output_folder,
        lang="en",
        backend="pipeline",
        method="auto",
    )

    md_content = md_path.read_text(encoding="utf-8")
    stripped = md_content.strip()

    # Non-empty
    assert len(stripped) > 0, "Markdown output is empty"

    # Reasonable minimum length for a 2-page PDF
    assert len(stripped) >= 50, (
        f"Markdown suspiciously short ({len(stripped)} chars): {stripped[:100]}"
    )

    # Contains at least some recognizable words from the PDF
    lower = stripped.lower()
    has_content_words = any(
        word in lower
        for word in ["introduction", "methodology", "test", "document", "page"]
    )
    assert has_content_words, (
        f"Markdown does not contain any expected words. First 200 chars: {stripped[:200]}"
    )


# ---------------------------------------------------------------------------
# Test 4: API layer wrapper
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_api_layer(sample_pdf, tmp_path):
    """Verify convert_pdf_to_md_by_MinerU returns the correct path."""
    from file_conversion_router.services.tai_MinerU_service.api import (
        convert_pdf_to_md_by_MinerU,
    )

    output_dir = tmp_path / "api_output"
    md_path = convert_pdf_to_md_by_MinerU(sample_pdf, output_dir)

    file_name = sample_pdf.name
    expected = output_dir / file_name / "auto" / f"{file_name}.md"
    assert md_path == expected, f"API returned {md_path}, expected {expected}"
    assert md_path.exists(), f"Markdown file does not exist at: {md_path}"
