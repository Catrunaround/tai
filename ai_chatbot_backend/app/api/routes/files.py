from typing import Optional, List
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Path, UploadFile, File, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.core.dbs.metadata_db import get_metadata_db
from app.api.deps import verify_api_token
from app.schemas.files import FileMetadata, FileListResponse, DirectoryBrowserResponse, TranscriptSegment
from app.services.file_service import file_service

router = APIRouter()
logger = logging.getLogger(__name__)

# Maximum upload size for student files (50 MB)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_ALLOWED_EXTENSIONS = {".pdf"}


@router.get(
    "", response_model=FileListResponse, summary="List files with auto-discovery"
)
async def list_files(
    course_code: Optional[str] = Query(
        None, description="Filter by course code (e.g., CS61A)"
    ),
    category: Optional[str] = Query(
        None, description="Filter by category (document, video, audio, other)"
    ),
    search: Optional[str] = Query(None, description="Search in file names and titles"),
    path: Optional[str] = Query(None, description="Filter by directory path (e.g., 'Part One/practice')"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(100, ge=1, le=1000, description="Items per page"),
    db: Session = Depends(get_metadata_db),
    _: bool = Depends(verify_api_token),
):
    """
    List files with simple filtering and auto-discovery.

    Features:
    - Auto-discovery: New files found automatically, no manual rescans needed
    - Simple filtering: By course, category, search terms
    - Pagination: Efficient handling of large file collections

    Example usage:
    - GET /api/files - List all files
    - GET /api/files?course_code=CS61A - CS61A files only
    - GET /api/files?category=document - Document files
    - GET /api/files?search=lab - Search for files containing "lab"
    """
    try:
        result = file_service.list_files(
            db=db,
            course_code=course_code,
            category=category,
            search=search,
            path=path,
            page=page,
            limit=limit,
        )

        return FileListResponse(
            files=[FileMetadata.from_db_model(file) for file in result["files"]],
            total_count=result["total_count"],
            page=result["page"],
            limit=result["limit"],
            has_next=result["has_next"],
            has_prev=result["has_prev"],
            filters_applied={
                "course_code": course_code,
                "category": category,
                "search": search,
                "path": path,
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing files: {str(e)}",
        )


@router.get(
    "/browse", response_model=DirectoryBrowserResponse, summary="Browse directory structure"
)
async def browse_directory(
    course_code: str = Query(..., description="Course code (e.g., 'CS61A')"),
    path: str = Query("", description="Directory path within course (e.g., 'Part One/practice')"),
    db: Session = Depends(get_metadata_db),
    _: bool = Depends(verify_api_token),
):
    """
    Browse directory structure for a course with hierarchical navigation.
    
    Features:
    - Hierarchical browsing: Navigate through nested folders
    - Immediate children: Shows only direct subdirectories and files
    - File counts: Number of files in each directory (including subdirectories)
    - Breadcrumbs: Navigation trail for current location
    - Supports unlimited nesting depth
    
    Example usage:
    - GET /api/files/browse?course_code=CS61A - Browse root of course
    - GET /api/files/browse?course_code=CS61A&path=Part One - Browse "Part One" folder
    - GET /api/files/browse?course_code=CS61A&path=Part One/practice - Browse nested folder
    """
    logger.info(f"Browse request: course_code={course_code}, path='{path}'")
    
    try:
        result = file_service.browse_directory(
            db=db,
            course_code=course_code,
            path=path.strip()
        )
        
        logger.debug(f"Got {len(result.get('files', []))} files from service")
        
        # Convert files to schema format
        from app.schemas.files import DirectoryInfo, BreadcrumbItem
        
        files = []
        for idx, file in enumerate(result["files"]):
            try:
                files.append(FileMetadata.from_db_model(file))
            except Exception as e:
                logger.error(f"Failed to convert file #{idx} '{file.file_name}': {e}")
                # Log the problematic sections data
                if hasattr(file, 'sections'):
                    logger.error(f"Sections data type: {type(file.sections)}, value: {file.sections[:200] if file.sections else None}")
                raise
        
        return DirectoryBrowserResponse(
            directories=[DirectoryInfo(**dir_info) for dir_info in result["directories"]],
            files=files,
            current_path=result["current_path"],
            breadcrumbs=[BreadcrumbItem(**crumb) for crumb in result["breadcrumbs"]],
            course_code=result["course_code"]
        )
        
    except Exception as e:
        logger.error(f"Browse directory error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error browsing directory: {str(e)}"
        )


@router.get(
    "/{file_id}", response_model=FileMetadata, summary="Get file metadata by UUID"
)
async def get_file_metadata(
    file_id: UUID = Path(..., description="File UUID"),
    db: Session = Depends(get_metadata_db),
    _: bool = Depends(verify_api_token),
):
    """
    Get detailed metadata for a specific file by its UUID.

    Returns comprehensive file information including:
    - Basic info: name, size, type, creation date
    - Academic info: course, category, assignment number
    - Access info: download count, last accessed
    """
    file_record = file_service.get_file_by_id(db, file_id)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID {file_id} not found",
        )

    return FileMetadata.from_db_model(file_record)


@router.get("/{file_id}/download", summary="Download file by UUID")
async def download_file(
    file_id: UUID = Path(..., description="File UUID"),
    db: Session = Depends(get_metadata_db),
    _: bool = Depends(verify_api_token),
):
    """
    Download a file by its UUID.

    Features:
    - Secure access: UUID-based, no path exposure
    - Access tracking: Download count and last access time
    - Security validation: Ensures file is within allowed directory
    - Proper headers: Correct MIME type and filename
    """
    return file_service.get_file_content(db, file_id)

@router.get(
    "/{file_id}/extra_info", 
    response_model=List[TranscriptSegment], 
    summary="Get extra info (transcript) for file"
)
async def get_file_extra_info(
    file_id: UUID = Path(..., description="File UUID"),
    db: Session = Depends(get_metadata_db),
    _: bool = Depends(verify_api_token),
):
    """
    Get extra info for a specific file by its UUID.
    
    Currently supports video transcript data stored in extra_info field.
    Returns empty array if no extra info is available.
    """
    logger.info(f"Getting extra_info for file_id: {file_id}")
    
    file_record = file_service.get_file_by_id(db, file_id)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID {file_id} not found",
        )
    
    # Parse extra_info JSON if it exists
    if not file_record.extra_info:
        logger.debug(f"No extra_info for file {file_id}")
        return []
    
    try:
        import json
        extra_info_data = json.loads(file_record.extra_info)
        logger.debug(f"Parsed extra_info type: {type(extra_info_data)}")
        
        # Handle case where extra_info might be wrapped in an object
        if isinstance(extra_info_data, dict):
            # Check if it has a transcript or segments key
            if "transcript" in extra_info_data:
                logger.debug("Found 'transcript' key in extra_info")
                extra_info_data = extra_info_data["transcript"]
            elif "segments" in extra_info_data:
                logger.debug("Found 'segments' key in extra_info")
                extra_info_data = extra_info_data["segments"]
            elif "extra_info" in extra_info_data:
                logger.debug("Found nested 'extra_info' key")
                extra_info_data = extra_info_data["extra_info"]
        
        # Validate and convert to TranscriptSegment objects
        if isinstance(extra_info_data, list):
            transcript_segments = []
            for i, segment in enumerate(extra_info_data):
                # Normalize key names (handle both "start time" and "start_time" formats)
                normalized_segment = {}
                
                # Map various key formats to the expected format
                key_mappings = {
                    "start time": "start_time",
                    "start_time": "start_time",
                    "end time": "end_time", 
                    "end_time": "end_time",
                    "text content": "text_content",
                    "text_content": "text_content",
                    "speaker": "speaker"
                }
                
                for old_key, new_key in key_mappings.items():
                    if old_key in segment:
                        normalized_segment[new_key] = segment[old_key]
                
                # Check if all required keys are present after normalization
                required_keys = ["start_time", "end_time", "speaker", "text_content"]
                if all(key in normalized_segment for key in required_keys):
                    transcript_segments.append(TranscriptSegment(**normalized_segment))
                else:
                    missing_keys = [key for key in required_keys if key not in normalized_segment]
                    logger.warning(f"Segment {i} missing keys after normalization: {missing_keys}. Original keys: {list(segment.keys())}")
            
            logger.info(f"Returning {len(transcript_segments)} transcript segments")
            return transcript_segments
        else:
            logger.warning(f"extra_info is not a list after parsing: {type(extra_info_data)}")
            return []
            
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Error parsing extra_info: {e}")
        logger.error(f"Raw extra_info: {file_record.extra_info[:500] if file_record.extra_info else None}")
        # Return empty array if parsing fails
        return []


# ---------------------------------------------------------------------------
# Student file upload  (session-scoped, in-memory only, no DB writes)
# ---------------------------------------------------------------------------

@router.post("/upload", summary="Upload a file for session-scoped RAG")
async def upload_file_for_session(
    file: UploadFile = File(...),
    sid: str = Form(..., description="Session ID from frontend"),
    course_code: str = Form(..., description="Current course code"),
    _: bool = Depends(verify_api_token),
):
    """Upload a PDF, convert + chunk it via the RAG conversion service,
    embed the chunks, and store them in the session-scoped in-memory cache.

    The uploaded data is **not** written to metadata.db. It lives in memory
    for the duration of the session and is automatically evicted after the TTL.
    """
    import httpx
    import numpy as np
    from pathlib import Path as _Path

    from app.config import settings
    from app.services.query.embedding import _get_embeddings_batch
    from app.services.query.session_upload_cache import add_upload

    # --- validation -----------------------------------------------------------
    suffix = _Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {suffix}. Allowed: {_ALLOWED_EXTENSIONS}",
        )

    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(contents) / 1024 / 1024:.1f} MB). Max: {_MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB",
        )

    # --- call RAG conversion service ------------------------------------------
    convert_url = f"{settings.conversion_service_url}/process"
    logger.info(f"[upload] Forwarding {file.filename} to {convert_url} (sid={sid})")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(
                convert_url,
                files={"file": (file.filename, contents, file.content_type or "application/octet-stream")},
                data={"course_code": course_code},
            )
        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.error(f"[upload] Conversion service error {resp.status_code}: {detail}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Conversion service error: {detail}")

        payload = resp.json()
        chunks = payload.get("chunks", [])
        file_uuid = payload.get("file_uuid", "")
        file_name = payload.get("file_name", file.filename)
    except httpx.ConnectError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversion service is not running. Start it with: make dev-convert-api (in rag/)",
        )

    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No chunks produced from file")

    # --- embed chunks ---------------------------------------------------------
    logger.info(f"[upload] Embedding {len(chunks)} chunks for {file_name}")
    try:
        embeddings = _get_embeddings_batch(chunks)
    except Exception as e:
        logger.exception("[upload] Embedding failed")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")

    # --- store in session cache -----------------------------------------------
    total = add_upload(sid, file_name, file_uuid, chunks, embeddings)
    logger.info(f"[upload] Stored {len(chunks)} chunks for sid={sid} (total now: {total})")

    return JSONResponse({
        "sid": sid,
        "file_name": file_name,
        "file_uuid": file_uuid,
        "chunks_count": len(chunks),
        "total_session_chunks": total,
        "status": "ready",
    })

