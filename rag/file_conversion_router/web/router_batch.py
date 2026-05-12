"""Batch upload API endpoints.

This module provides the FastAPI router for batch file upload,
conversion, and progress streaming via SSE.

Endpoints:
- POST /upload: Upload files and start batch conversion
- GET /{job_id}/stream: Stream progress updates via SSE
- GET /{job_id}/status: Get current job status (polling fallback)
- POST /{job_id}/cancel: Cancel a running job
- GET /jobs: List recent jobs
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse

from file_conversion_router.config import (
    get_course_db_path,
    get_course_output_dir,
)
from file_conversion_router.web.schemas import (
    BatchUploadResponse,
    BatchJobStatus,
    BatchConversionResult,
    FileInfo,
    JobStatus,
    ProgressEvent,
    ProgressEventType,
)
from file_conversion_router.services.temp_storage_service import get_temp_storage_service
from file_conversion_router.services.batch_upload_service import (
    get_job_manager,
    get_batch_processor,
    get_file_validator,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=BatchUploadResponse)
async def upload_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="Files to upload and convert"),
    course_code: Optional[str] = Form(None, description="Course identifier (e.g., 'CS61A'). Required for ingest jobs."),
    course_name: Optional[str] = Form(None, description="Full course name. Defaults to course_code when omitted."),
    auto_embed: bool = Form(True, description="Generate embeddings after conversion and DB chunk insertion."),
    output_dir: Optional[str] = Form(None, description="Custom output directory (optional)"),
    db_path: Optional[str] = Form(None, description="Custom database path (optional)"),
):
    """
    Upload files and start a directory-service ingest job.

    This endpoint:
    1. Validates uploaded files (extension, size)
    2. Saves files to temporary storage
    3. Converts files to markdown through directory_service
    4. Chunks converted content and writes file/chunk rows to SQLite
    5. Optionally creates embeddings
    6. Returns job ID for progress tracking

    Use the returned job_id to:
    - Stream progress: GET /batch/{job_id}/stream
    - Poll status: GET /batch/{job_id}/status
    - Cancel job: POST /batch/{job_id}/cancel
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # /batch/upload is always the ingest/directory-service path. Pure
    # conversion is exposed separately at /convert and never writes to DB.
    if not course_code:
        raise HTTPException(
            status_code=400,
            detail="course_code is required for /batch/upload ingest jobs. Use /convert for convert-only jobs.",
        )

    # Validate files
    validator = get_file_validator()
    validation_result = validator.validate_batch(files)

    if not validation_result.valid_files:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No valid files in batch",
                "errors": [e.model_dump() for e in validation_result.invalid_files]
            }
        )

    # Filter to only valid files
    valid_files = [f for f in files if f.filename in validation_result.valid_files]

    # Create job. This path always has course context because it writes to DB.
    job_manager = get_job_manager()
    effective_course_code = course_code
    effective_course_name = course_name or effective_course_code

    job_id = job_manager.create_job(
        course_code=effective_course_code,
        course_name=effective_course_name,
        file_count=len(valid_files),
    )

    # Save files to temp storage
    temp_storage = get_temp_storage_service()
    saved_paths = await temp_storage.save_uploaded_files(
        job_id=job_id,
        files=valid_files,
        preserve_paths=True,
    )

    if output_dir:
        final_output_dir = Path(output_dir)
    else:
        final_output_dir = get_course_output_dir(effective_course_code)

    if db_path:
        final_db_path = Path(db_path)
    else:
        final_db_path = get_course_db_path(effective_course_code)

    # Start background processing. The web ingest API always reconverts on upload —
    # callers expect fresh markdown/sidecar JSON every time, even when the
    # exact same file was previously uploaded. The legacy directory-batch
    # entry point keeps the cache behavior so course-scoped reprocessing of
    # unchanged files stays cheap.
    async def run_batch_processing():
        processor = get_batch_processor()
        try:
            await processor.process_batch(
                job_id=job_id,
                file_paths=saved_paths,
                course_code=effective_course_code,
                course_name=effective_course_name,
                output_dir=final_output_dir,
                db_path=final_db_path,
                auto_embed=auto_embed,
                skip_cache=True,
            )
        finally:
            # Schedule temp file cleanup
            await temp_storage.schedule_cleanup(job_id)

    background_tasks.add_task(run_batch_processing)

    # Build response
    files_info = []
    for f in valid_files:
        files_info.append(FileInfo(
            file_name=f.filename,
            file_size=f.size or 0,
            content_type=f.content_type,
        ))

    return BatchUploadResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        files_received=len(valid_files),
        files_info=files_info,
        message=f"Batch job created. {len(valid_files)} files queued for processing."
        + (f" {len(validation_result.invalid_files)} files rejected." if validation_result.invalid_files else ""),
    )


@router.get("/{job_id}/stream")
async def stream_progress(job_id: str):
    """
    Stream real-time progress updates via Server-Sent Events (SSE).

    Connect to this endpoint to receive live updates as files are processed.

    Event types:
    - job_start: Job started processing
    - file_start: Started processing a file
    - file_done: File completed successfully
    - file_error: File failed with error
    - job_complete: All files processed

    The connection will close automatically when the job completes.
    """
    job_manager = get_job_manager()

    # Check job exists
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Get progress queue
    queue = job_manager.get_progress_queue(job_id)
    if not queue:
        raise HTTPException(status_code=404, detail=f"Progress queue not found for job: {job_id}")

    async def event_generator():
        """Generate SSE events from the progress queue."""
        try:
            while True:
                try:
                    # Wait for next event with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    # Yield the event
                    yield event.to_sse()

                    # Check if job is complete
                    if event.event_type == ProgressEventType.JOB_COMPLETE:
                        break

                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

                    # Check if job is still running
                    current_status = job_manager.get_job_status(job_id)
                    if current_status and current_status.status in [
                        JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED
                    ]:
                        break

        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for job {job_id}")
        except Exception as e:
            logger.error(f"Error in SSE stream for job {job_id}: {e}")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/{job_id}/status", response_model=BatchJobStatus)
async def get_status(job_id: str):
    """
    Get current job status.

    Use this endpoint for polling-based progress tracking
    or as a fallback when SSE is not available.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return job


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    """
    Cancel a running job.

    Files that have already been processed will remain processed.
    Only pending files will be skipped.
    """
    job_manager = get_job_manager()

    # Check job exists
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Check if job can be cancelled
    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in '{job.status}' state"
        )

    # Request cancellation
    cancelled = job_manager.cancel_job(job_id)

    if cancelled:
        return {
            "job_id": job_id,
            "status": "cancellation_requested",
            "message": "Job cancellation has been requested. Processing will stop after current file."
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to cancel job"
        )


def _find_result_by_name(job, file_name: str):
    """Locate a FileResult by name with tolerant matching.

    Some clients URL-substitute spaces with underscores instead of using
    percent-encoding, so we accept either form. Match priority:
        1. exact match
        2. underscores-as-spaces (and vice versa)
        3. case-insensitive variants of (1) and (2)
    """
    if not job.results:
        return None

    by_exact = {r.file_name: r for r in job.results}
    if file_name in by_exact:
        return by_exact[file_name]

    def _normalize(name: str) -> str:
        return name.replace("_", " ")

    target = _normalize(file_name)
    for r in job.results:
        if _normalize(r.file_name) == target:
            return r

    target_lower = target.lower()
    for r in job.results:
        if _normalize(r.file_name).lower() == target_lower:
            return r

    return None


@router.get("/{job_id}/files/{file_name}/transcript")
async def get_file_transcript(job_id: str, file_name: str):
    """
    Download the timestamped transcript JSON for a converted video file.

    For video inputs (mp4/mkv/webm/mov), the conversion pipeline writes a
    sidecar JSON with per-segment `start time`, `end time`, `speaker`, and
    `text content` (plus title markers for navigation). This endpoint serves
    that JSON so remote callers can map paragraphs to video timestamps for
    click-to-jump UIs.

    Returns 404 if the job, file, or transcript file is not found.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    matching = _find_result_by_name(job, file_name)
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_name}' not found in job {job_id}",
        )
    if not matching.transcript_path:
        raise HTTPException(
            status_code=404,
            detail=f"No transcript available for '{file_name}' (not a video, or conversion incomplete)",
        )

    transcript_file = Path(matching.transcript_path)
    if not transcript_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Transcript file missing on disk: {transcript_file}",
        )

    return FileResponse(
        path=str(transcript_file),
        media_type="application/json",
        filename=transcript_file.name,
    )


@router.get("/{job_id}/files/{file_name}/markdown")
async def get_file_markdown(job_id: str, file_name: str):
    """
    Download the converted markdown for a file in a completed job.

    Works for any file type the converter produces markdown for (PDF, video,
    notebook, etc.). Returns 404 if the job, file, or markdown is not found.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    matching = _find_result_by_name(job, file_name)
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_name}' not found in job {job_id}",
        )
    if not matching.markdown_path:
        raise HTTPException(
            status_code=404,
            detail=f"No markdown available for '{file_name}' (conversion incomplete or failed)",
        )

    md_file = Path(matching.markdown_path)
    if not md_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Markdown file missing on disk: {md_file}",
        )

    return FileResponse(
        path=str(md_file),
        media_type="text/markdown; charset=utf-8",
        filename=md_file.name,
    )


@router.get("/{job_id}/files/{file_name}/bbox")
async def get_file_bbox(job_id: str, file_name: str):
    """
    Download the per-line bbox JSON for a converted PDF file.

    For PDF inputs, the conversion pipeline derives `<file>_lines.json` from
    MinerU's `_middle.json`. Each entry contains `content`, `bbox`
    `[x1, y1, x2, y2]`, `index`, `page_index`, and `block_type`, allowing
    callers to highlight or jump to source regions in the original PDF.

    Returns 404 if the job, file, or bbox JSON is not found.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    matching = _find_result_by_name(job, file_name)
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_name}' not found in job {job_id}",
        )
    if not matching.bbox_path:
        raise HTTPException(
            status_code=404,
            detail=f"No bbox JSON available for '{file_name}' (not a PDF, or conversion incomplete)",
        )

    bbox_file = Path(matching.bbox_path)
    if not bbox_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Bbox JSON file missing on disk: {bbox_file}",
        )

    return FileResponse(
        path=str(bbox_file),
        media_type="application/json",
        filename=bbox_file.name,
    )


@router.get("/{job_id}/files/{file_name}/scenes")
async def get_file_scenes(job_id: str, file_name: str):
    """
    Return the per-scene snapshot index for a converted video file.

    For video inputs, the conversion pipeline runs PySceneDetect's
    AdaptiveDetector and saves one JPEG per detected scene plus a
    `scenes.json` index. This endpoint returns that JSON with each entry's
    `image_url` injected so callers can fetch the snapshots via
    `GET /batch/{job_id}/files/{file_name}/scenes/{image_name}`.

    Returns 404 if the job, file, or scenes index is not found.
    """
    import json as _json

    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    matching = _find_result_by_name(job, file_name)
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_name}' not found in job {job_id}",
        )
    if not matching.scenes_path:
        raise HTTPException(
            status_code=404,
            detail=f"No scenes index available for '{file_name}' (not a video, or conversion incomplete)",
        )

    scenes_file = Path(matching.scenes_path)
    if not scenes_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Scenes index file missing on disk: {scenes_file}",
        )

    try:
        scenes = _json.loads(scenes_file.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse scenes index: {e}",
        )

    # Inject image URLs so callers don't have to know the storage layout.
    for entry in scenes:
        if not isinstance(entry, dict):
            continue
        primary = entry.get("image")
        if primary:
            entry["image_url"] = (
                f"/batch/{job_id}/files/{file_name}/scenes/{primary}"
            )
        images = entry.get("images") or []
        if images:
            entry["image_urls"] = [
                f"/batch/{job_id}/files/{file_name}/scenes/{img}"
                for img in images
            ]

    return scenes


@router.get("/{job_id}/files/{file_name}/scenes/{image_name}")
async def get_file_scene_image(job_id: str, file_name: str, image_name: str):
    """
    Download a single per-scene snapshot JPEG.

    The image must live inside the file's scenes_dir; any path traversal
    attempt (e.g., `..`, absolute paths) is rejected.
    """
    job_manager = get_job_manager()
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    matching = _find_result_by_name(job, file_name)
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_name}' not found in job {job_id}",
        )
    if not matching.scenes_dir:
        raise HTTPException(
            status_code=404,
            detail=f"No scenes available for '{file_name}'",
        )

    scenes_dir = Path(matching.scenes_dir).resolve()
    # Reject anything that doesn't resolve to a child of scenes_dir.
    candidate = (scenes_dir / image_name).resolve()
    try:
        candidate.relative_to(scenes_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image name")

    if not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot not found: {image_name}",
        )

    suffix = candidate.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(candidate),
        media_type=media_type,
        filename=candidate.name,
    )


@router.get("/jobs", response_model=List[BatchJobStatus])
async def list_jobs(limit: int = 20):
    """
    List recent batch jobs.

    Returns the most recent jobs ordered by creation time.
    """
    job_manager = get_job_manager()
    return job_manager.list_jobs(limit=limit)


@router.delete("/{job_id}")
async def delete_job(job_id: str):
    """
    Delete a job and its temporary files.

    Only completed, failed, or cancelled jobs can be deleted.
    """
    job_manager = get_job_manager()
    temp_storage = get_temp_storage_service()

    # Check job exists
    job = job_manager.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Check if job can be deleted
    if job.status not in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete job in '{job.status}' state. Cancel it first."
        )

    # Clean up temp files
    temp_storage.cancel_scheduled_cleanup(job_id)
    temp_storage.cleanup_job(job_id)

    # Clean up job resources
    job_manager.cleanup_job(job_id)

    return {
        "job_id": job_id,
        "status": "deleted",
        "message": "Job and temporary files have been deleted"
    }
