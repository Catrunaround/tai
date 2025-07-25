"""Public API for the file conversion router module."""

from pathlib import Path
from typing import Union

from file_conversion_router.services.directory_service import process_folder


def convert_directory(
    input_dir: Union[str, Path],
    output_dir: Union[str, Path],
    course_name: str,
    course_id: str,
    log_dir: Union[str, Path] = None,
    cache_path: Union[str, Path] = None,
) -> None:
    """Convert all supported files in the given directory to Markdown format, to the specified output directory.

    Current supported file types:
    1. PDF
    2. Markdown (To clarify, this markdown includes additional tree structure of original markdown file)
    """
    process_folder(
        input_dir,
        output_dir,
        course_name,
        course_id,
        log_dir=log_dir,
        cache_path=cache_path,
    )


