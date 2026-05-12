# Copyright (c) Opendatalab. All rights reserved.
import json
import os
import re
import shutil
from pathlib import Path

from loguru import logger

from mineru.cli.common import do_parse, read_fn


def parse_doc(
        pdf_path: Path,
        output_folder: Path,
        lang: str = "en",
        backend: str = "vlm-transformers",
        method: str = "auto",
        server_url: str | None = None,
        start_page_id: int = 0,
        end_page_id: int | None = None,
) -> Path:
    """Convert a PDF to markdown using mineru.

    Defaults to mineru 3.1's VLM backend ("vlm-transformers") which uses the
    MinerU 2.5 vision-language model. This is significantly slower than the
    classic ``pipeline`` backend but produces noticeably better layout/OCR
    fidelity. The first run downloads the VLM weights from HuggingFace.

    mineru writes outputs under ``{output_folder}/{pdf_name}/{subdir}/``,
    where ``subdir`` is the parse method ("auto") for the pipeline backend
    and the literal "vlm" for any vlm-* backend. For backwards compatibility
    with the rest of the conversion router, we flatten the relevant artifacts
    (md + content_list.json + middle.json + images) back into ``output_folder``
    after the parse completes.
    """
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    file_name = pdf_path.name
    pdf_bytes = read_fn(pdf_path)

    do_parse(
        output_dir=str(output_folder),
        pdf_file_names=[file_name],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=[lang],
        backend=backend,
        parse_method=method,
        server_url=server_url,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_orig_pdf=False,
        f_dump_middle_json=True,
        f_dump_model_output=False,
        f_dump_md=True,
        f_dump_content_list=True,
    )

    nested_dir = output_folder / file_name / (method if backend == "pipeline" else "vlm")
    nested_md = nested_dir / f"{file_name}.md"
    nested_content_list = nested_dir / f"{file_name}_content_list.json"
    nested_middle = nested_dir / f"{file_name}_middle.json"

    if not nested_md.exists():
        # Fall back to whatever mineru produced (some backends use different subdirs)
        candidates = list((output_folder / file_name).rglob(f"{file_name}.md"))
        if candidates:
            nested_md = candidates[0]
            nested_content_list = nested_md.with_name(f"{file_name}_content_list.json")
            nested_middle = nested_md.with_name(f"{file_name}_middle.json")
        else:
            raise FileNotFoundError(
                f"mineru did not produce expected markdown at {nested_md}"
            )

    flat_md = output_folder / f"{file_name}.md"
    flat_content_list = output_folder / f"{file_name}_content_list.json"
    flat_middle = output_folder / f"{file_name}_middle.json"

    shutil.copy2(nested_md, flat_md)
    if nested_content_list.exists():
        content_list_data = json.loads(nested_content_list.read_text(encoding="utf-8"))
        cleaned = clean_unicode_surrogates(content_list_data)
        flat_content_list.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
    if nested_middle.exists():
        # Flatten the middle.json so downstream sentence-mapping (which derives
        # the per-line bbox JSON via generate_lines_json_from_middle_json) can
        # find it next to the markdown.
        shutil.copy2(nested_middle, flat_middle)

    nested_images = nested_dir / "images"
    if nested_images.exists():
        flat_images = output_folder / f"{file_name}_images"
        flat_images.mkdir(exist_ok=True)
        for img in nested_images.iterdir():
            if img.is_file():
                shutil.copy2(img, flat_images / img.name)

    logger.info(f"Markdown saved to: {flat_md}")
    return flat_md


def clean_unicode_surrogates(obj):
    """Recursively clean Unicode surrogate characters from any data structure"""
    if isinstance(obj, str):
        obj = obj.replace('\ud83e', '🦃')
        obj = obj.replace('\ud83d', '🐛')
        obj = re.sub(r'[\ud800-\udfff]', '', obj)
        obj = obj.encode('utf-8', 'ignore').decode('utf-8')
        return obj
    elif isinstance(obj, dict):
        return {key: clean_unicode_surrogates(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_unicode_surrogates(item) for item in obj]
    else:
        return obj


if __name__ == '__main__':
    from file_conversion_router.config import get_test_data_path, get_test_output_path

    doc_path = get_test_data_path('testing/pdfs/disc01.pdf')
    output_dir = get_test_output_path('disc01')
    parse_doc(doc_path, output_dir, backend="pipeline")
