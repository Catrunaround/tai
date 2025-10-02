"""Public API for the file conversion router module.

This module provides a high-level interface for document conversion, embedding generation,
and database management for the RAG pipeline.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

# Import from utility modules
from file_conversion_router.utils.yaml_utils import load_yaml, save_yaml
from file_conversion_router.utils.course_processor import (
    convert_directory as _convert_directory,
    process_courses_from_master_config as _process_courses_from_master_config,
    update_master_config_status,
    get_courses_needing_update,
    mark_course_for_update,
    merge_course_databases_from_master_config
)
from file_conversion_router.utils.database_merger import (
    merge_course_databases_into_collective,
    merge_all_course_databases_in_directory,
    merge_databases_by_list
)
from file_conversion_router.embedding.embedding_create import embedding_create
from file_conversion_router.embedding.file_embedding_create import (
    embed_files_from_markdown,
    check_embedding_status
)

# Configure logging
logger = logging.getLogger(__name__)


# ========================
# Main Conversion Functions
# ========================

def convert_directory(
    input_config: Union[str, Path],
    auto_embed: bool = True
) -> Dict[str, Any]:
    """
    Convert all supported files in a directory to Markdown format and optionally create embeddings.

    This is the main entry point for processing a single course directory. It handles:
    1. File conversion to Markdown format
    2. Database creation/update with file metadata
    3. Optional embedding generation for both chunks and full files

    Args:
        input_config: Path to the configuration YAML file containing:
            - input_dir: Source directory with course materials
            - output_dir: Destination for converted Markdown files
            - course_name: Full name of the course
            - course_code: Short code for the course (e.g., "CS61A")
            - db_path: Path to SQLite database for metadata
            - log_folder: Optional directory for log files
        auto_embed: Whether to automatically create embeddings after conversion (default: True)

    Returns:
        Dictionary containing conversion statistics:
            - files_processed: Number of files successfully converted
            - files_failed: Number of files that failed conversion
            - embeddings_created: Number of embeddings created (if auto_embed=True)
            - total_time: Total processing time in seconds

    Example:
        >>> result = convert_directory("configs/CS61A_config.yaml", auto_embed=True)
        >>> print(f"Processed {result['files_processed']} files")
    """
    try:
        # Load configuration
        data = load_yaml(str(input_config))

        # Track statistics
        stats = {
            "files_processed": 0,
            "files_failed": 0,
            "embeddings_created": 0,
            "chunks_embedded": 0,
            "total_time": 0
        }

        # Perform conversion with the original function
        logger.info(f"Starting conversion for config: {input_config}")
        _convert_directory(input_config, auto_embed=auto_embed)

        # If embeddings were created, get statistics
        if auto_embed and data.get("db_path"):
            embed_stats = check_embedding_status(data["db_path"])
            stats["embeddings_created"] = embed_stats.get("total_embedded", 0)
            stats["chunks_embedded"] = embed_stats.get("chunks_embedded", 0)

        logger.info(f"Conversion completed. Stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error in convert_directory: {str(e)}")
        raise


def process_courses_from_master_config(
    master_config_path: Optional[str] = None,
    auto_embed: bool = True
) -> Dict[str, Any]:
    """
    Process all courses marked for update in the master configuration file.

    This function provides batch processing capabilities for multiple courses,
    automatically handling conversion, embedding, and status updates.

    Args:
        master_config_path: Path to the master configuration file.
                          Defaults to 'configs/courses_master_config.yaml'
        auto_embed: Whether to automatically create embeddings after each course conversion

    Returns:
        Dictionary containing processing statistics:
            - courses_processed: List of successfully processed course names
            - courses_failed: List of courses that failed processing
            - total_files: Total number of files processed
            - total_embeddings: Total number of embeddings created

    Example:
        >>> results = process_courses_from_master_config(auto_embed=True)
        >>> print(f"Processed courses: {results['courses_processed']}")
    """
    stats = {
        "courses_processed": [],
        "courses_failed": [],
        "total_files": 0,
        "total_embeddings": 0
    }

    try:
        # Use the original function
        _process_courses_from_master_config(master_config_path, auto_embed=auto_embed)

        # Get list of processed courses from master config
        if master_config_path is None:
            master_config_path = Path(__file__).parent / "configs" / "courses_master_config.yaml"

        master_config = load_yaml(str(master_config_path))
        for course_name, course_info in master_config.get("courses", {}).items():
            if not course_info.get("needs_update", True):
                stats["courses_processed"].append(course_name)

        logger.info(f"Batch processing completed. Stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error in process_courses_from_master_config: {str(e)}")
        raise


# ========================
# Embedding Functions
# ========================

def create_embeddings_for_course(
    db_path: str,
    course_code: str,
    data_dir: Optional[str] = None,
    force_recompute: bool = False
) -> Dict[str, int]:
    """
    Create embeddings for a specific course's converted content.

    This function generates embeddings for both:
    1. Document chunks (for RAG retrieval)
    2. Complete Markdown files (for semantic search)

    Args:
        db_path: Path to the course's SQLite database
        course_code: Course identifier (e.g., "CS61A")
        data_dir: Directory containing converted Markdown files.
                 If None, will be inferred from database records.
        force_recompute: Whether to regenerate existing embeddings

    Returns:
        Dictionary with embedding statistics:
            - chunks_embedded: Number of chunks with embeddings
            - files_embedded: Number of files with embeddings
            - errors: Number of errors encountered
            - skipped: Number of items skipped (already embedded)

    Example:
        >>> stats = create_embeddings_for_course(
        ...     db_path="data/CS61A_metadata.db",
        ...     course_code="CS61A",
        ...     force_recompute=False
        ... )
        >>> print(f"Created embeddings for {stats['chunks_embedded']} chunks")
    """
    stats = {
        "chunks_embedded": 0,
        "files_embedded": 0,
        "errors": 0,
        "skipped": 0
    }

    try:
        # Create chunk embeddings
        logger.info(f"Creating chunk embeddings for course: {course_code}")
        embedding_create(db_path, course_code)

        # Create file embeddings
        if data_dir:
            logger.info(f"Creating file embeddings for course: {course_code}")
            file_results = embed_files_from_markdown(
                db_path=db_path,
                data_dir=data_dir,
                course_filter=course_code,
                force_recompute=force_recompute
            )

            stats["files_embedded"] = file_results.get("processed", 0)
            stats["errors"] = file_results.get("errors", 0)
            stats["skipped"] = file_results.get("skipped", 0)

        # Get chunk embedding count
        embed_status = check_embedding_status(db_path)
        stats["chunks_embedded"] = embed_status.get("chunks_embedded", 0)

        logger.info(f"Embedding creation completed. Stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error creating embeddings: {str(e)}")
        raise


def create_embeddings_batch(
    course_configs: List[Dict[str, str]],
    force_recompute: bool = False
) -> Dict[str, Any]:
    """
    Create embeddings for multiple courses in batch.

    Args:
        course_configs: List of dictionaries, each containing:
            - db_path: Path to course database
            - course_code: Course identifier
            - data_dir: Directory with Markdown files (optional)
        force_recompute: Whether to regenerate existing embeddings

    Returns:
        Dictionary with batch processing statistics

    Example:
        >>> configs = [
        ...     {"db_path": "data/CS61A_metadata.db", "course_code": "CS61A"},
        ...     {"db_path": "data/CS61B_metadata.db", "course_code": "CS61B"}
        ... ]
        >>> results = create_embeddings_batch(configs)
    """
    results = {
        "successful": [],
        "failed": [],
        "total_chunks": 0,
        "total_files": 0
    }

    for config in course_configs:
        try:
            course_code = config["course_code"]
            logger.info(f"Processing embeddings for course: {course_code}")

            stats = create_embeddings_for_course(
                db_path=config["db_path"],
                course_code=course_code,
                data_dir=config.get("data_dir"),
                force_recompute=force_recompute
            )

            results["successful"].append(course_code)
            results["total_chunks"] += stats.get("chunks_embedded", 0)
            results["total_files"] += stats.get("files_embedded", 0)

        except Exception as e:
            logger.error(f"Failed to create embeddings for {config.get('course_code')}: {str(e)}")
            results["failed"].append(config.get("course_code", "unknown"))

    return results


# ========================
# Full Pipeline Functions
# ========================

def process_course_pipeline(
    input_config: Union[str, Path],
    create_embeddings: bool = True,
    merge_to_collective: bool = False,
    collective_db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute the complete processing pipeline for a single course.

    This function combines all steps:
    1. Convert documents to Markdown
    2. Create embeddings for chunks and files
    3. Optionally merge to collective database

    Args:
        input_config: Path to course configuration YAML
        create_embeddings: Whether to create embeddings after conversion
        merge_to_collective: Whether to merge course DB to collective
        collective_db_path: Path to collective database (required if merge_to_collective=True)

    Returns:
        Dictionary with complete pipeline statistics

    Example:
        >>> results = process_course_pipeline(
        ...     "configs/CS61A_config.yaml",
        ...     create_embeddings=True,
        ...     merge_to_collective=True,
        ...     collective_db_path="data/collective_metadata.db"
        ... )
    """
    pipeline_stats = {
        "conversion": {},
        "embeddings": {},
        "merge": {}
    }

    try:
        # Step 1: Convert documents
        logger.info("Step 1: Converting documents to Markdown")
        pipeline_stats["conversion"] = convert_directory(
            input_config,
            auto_embed=create_embeddings
        )

        # Step 2: Get embedding stats if created
        if create_embeddings:
            config = load_yaml(str(input_config))
            db_path = config.get("db_path")
            if db_path:
                embed_status = check_embedding_status(db_path)
                pipeline_stats["embeddings"] = embed_status

        # Step 3: Merge to collective if requested
        if merge_to_collective and collective_db_path:
            config = load_yaml(str(input_config))
            db_path = config.get("db_path")

            if db_path and Path(db_path).exists():
                logger.info("Step 3: Merging to collective database")
                merge_stats = merge_databases_by_list(
                    course_db_paths=[db_path],
                    collective_db_path=collective_db_path
                )
                pipeline_stats["merge"] = merge_stats

        logger.info(f"Pipeline completed successfully. Stats: {pipeline_stats}")
        return pipeline_stats

    except Exception as e:
        logger.error(f"Pipeline error: {str(e)}")
        raise


# ========================
# Utility Functions
# ========================

def validate_course_config(config_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Validate a course configuration file and check paths.

    Args:
        config_path: Path to configuration YAML file

    Returns:
        Dictionary with validation results:
            - is_valid: Boolean indicating if config is valid
            - errors: List of validation errors
            - warnings: List of validation warnings

    Example:
        >>> validation = validate_course_config("configs/CS61A_config.yaml")
        >>> if validation["is_valid"]:
        ...     print("Configuration is valid")
    """
    results = {
        "is_valid": True,
        "errors": [],
        "warnings": []
    }

    try:
        config = load_yaml(str(config_path))

        # Check required fields
        required_fields = ["input_dir", "output_dir", "course_name", "course_code"]
        for field in required_fields:
            if field not in config:
                results["errors"].append(f"Missing required field: {field}")
                results["is_valid"] = False

        # Check paths exist
        if "input_dir" in config:
            input_path = Path(config["input_dir"])
            if not input_path.exists():
                results["errors"].append(f"Input directory does not exist: {input_path}")
                results["is_valid"] = False
            elif not input_path.is_dir():
                results["errors"].append(f"Input path is not a directory: {input_path}")
                results["is_valid"] = False

        # Check output directory (create if doesn't exist)
        if "output_dir" in config:
            output_path = Path(config["output_dir"])
            if not output_path.exists():
                results["warnings"].append(f"Output directory will be created: {output_path}")

        # Check database path
        if "db_path" in config:
            db_path = Path(config["db_path"])
            if not db_path.parent.exists():
                results["warnings"].append(f"Database directory does not exist: {db_path.parent}")

    except Exception as e:
        results["errors"].append(f"Error loading config: {str(e)}")
        results["is_valid"] = False

    return results


def get_processing_status(db_path: str) -> Dict[str, Any]:
    """
    Get detailed processing status for a course database.

    Args:
        db_path: Path to course database

    Returns:
        Dictionary with processing status:
            - total_files: Total number of files in database
            - converted_files: Number of successfully converted files
            - failed_files: Number of failed conversions
            - embeddings: Embedding statistics
            - last_updated: Timestamp of last update

    Example:
        >>> status = get_processing_status("data/CS61A_metadata.db")
        >>> print(f"Converted: {status['converted_files']}/{status['total_files']}")
    """
    try:
        # Get embedding status
        embed_status = check_embedding_status(db_path)

        status = {
            "total_files": embed_status.get("total_files", 0),
            "converted_files": embed_status.get("files_with_content", 0),
            "failed_files": 0,
            "embeddings": {
                "chunks_total": embed_status.get("total_chunks", 0),
                "chunks_embedded": embed_status.get("chunks_embedded", 0),
                "files_embedded": embed_status.get("files_embedded", 0)
            },
            "database_path": db_path,
            "database_exists": Path(db_path).exists()
        }

        return status

    except Exception as e:
        logger.error(f"Error getting processing status: {str(e)}")
        return {
            "error": str(e),
            "database_exists": Path(db_path).exists()
        }


# Re-export main functions for backward compatibility
__all__ = [
    # YAML utilities
    'load_yaml',
    'save_yaml',

    # Main conversion functions
    'convert_directory',
    'process_courses_from_master_config',

    # Course management
    'update_master_config_status',
    'get_courses_needing_update',
    'mark_course_for_update',

    # Database merging
    'merge_course_databases_into_collective',
    'merge_all_course_databases_in_directory',
    'merge_databases_by_list',
    'merge_course_databases_from_master_config',

    # Embedding functions
    'embedding_create',
    'embed_files_from_markdown',
    'check_embedding_status',
    'create_embeddings_for_course',
    'create_embeddings_batch',

    # Pipeline functions
    'process_course_pipeline',

    # Utility functions
    'validate_course_config',
    'get_processing_status'
]


# ========================
# Example Usage
# ========================

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Example 1: Process a single course with full pipeline
    # results = process_course_pipeline(
    #     "configs/CS61A_config.yaml",
    #     create_embeddings=True,
    #     merge_to_collective=True,
    #     collective_db_path="data/collective_metadata.db"
    # )
    # print(f"Pipeline results: {results}")

    # Example 2: Process all courses marked for update with auto-embedding
    # results = process_courses_from_master_config(auto_embed=True)
    # print(f"Processed courses: {results['courses_processed']}")

    # Example 3: Create embeddings for existing converted content
    # embed_stats = create_embeddings_for_course(
    #     db_path="data/CS61A_metadata.db",
    #     course_code="CS61A",
    #     data_dir="output/CS61A",
    #     force_recompute=False
    # )
    # print(f"Embeddings created: {embed_stats}")

    # Example 4: Batch process embeddings for multiple courses
    # configs = [
    #     {"db_path": "data/CS61A_metadata.db", "course_code": "CS61A", "data_dir": "output/CS61A"},
    #     {"db_path": "data/CS61B_metadata.db", "course_code": "CS61B", "data_dir": "output/CS61B"},
    #     {"db_path": "data/CS70_metadata.db", "course_code": "CS70", "data_dir": "output/CS70"}
    # ]
    # batch_results = create_embeddings_batch(configs, force_recompute=False)
    # print(f"Batch embedding results: {batch_results}")

    # Example 5: Validate configuration before processing
    # validation = validate_course_config("configs/CS61A_config.yaml")
    # if validation["is_valid"]:
    #     print("Configuration is valid, proceeding with conversion...")
    #     convert_directory("configs/CS61A_config.yaml", auto_embed=True)
    # else:
    #     print(f"Configuration errors: {validation['errors']}")

    # Example 6: Check processing status
    # status = get_processing_status("data/CS61A_metadata.db")
    # print(f"Processing status: {status}")

    # Example 7: Merge databases after processing
    # merge_stats = merge_course_databases_from_master_config()
    # print(f"Merge completed: {merge_stats}")

    # Default: Process all courses with embeddings enabled
    logger.info("Starting batch processing with auto-embedding...")
    results = process_courses_from_master_config(auto_embed=True)
    logger.info(f"Batch processing completed: {results}")