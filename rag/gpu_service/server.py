"""
FastAPI server for GPU-accelerated ML models.
Provides endpoints for:
- /transcribe: Audio transcription with WhisperX + speaker diarization
- /parse_pdf: PDF parsing with MinerU VLM

Deploy on RunPod Pod or any GPU-enabled server.
"""
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import tempfile
import os
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model references
whisper_model = None
align_model = None
align_metadata = None
diarize_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup, cleanup at shutdown."""
    global whisper_model, diarize_model

    logger.info("Loading WhisperX model (large-v3)...")
    try:
        import whisperx
        whisper_model = whisperx.load_model(
            "large-v3",
            device="cuda",
            compute_type="float16",
            language="en"
        )
        logger.info("WhisperX model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load WhisperX model: {e}")
        whisper_model = None

    logger.info("Loading speaker diarization model...")
    try:
        import whisperx
        diarize_model = whisperx.diarize.DiarizationPipeline(
            use_auth_token=os.getenv("HUGGINGFACE_ACCESS_TOKEN"),
            device="cuda"
        )
        logger.info("Diarization model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load diarization model: {e}")
        diarize_model = None

    yield  # Server runs

    # Cleanup
    logger.info("Shutting down, cleaning up models...")


app = FastAPI(
    title="TAI GPU Service",
    description="GPU-accelerated ML models for document and audio processing",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    import torch
    return {
        "status": "ok",
        "gpu": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "whisper_loaded": whisper_model is not None,
        "diarize_loaded": diarize_model is not None
    }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    diarize: bool = Form(default=True)
):
    """
    Transcribe audio with optional speaker diarization.

    Args:
        file: Audio file (WAV, MP3, etc.)
        language: Language code (default: "en")
        diarize: Whether to perform speaker diarization (default: True)

    Returns:
        segments: List of {start, end, text, speaker} dicts
    """
    import whisperx

    if whisper_model is None:
        raise HTTPException(status_code=503, detail="WhisperX model not loaded")

    # Save uploaded file to temp location
    suffix = os.path.splitext(file.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        content = await file.read()
        f.write(content)
        audio_path = f.name

    try:
        logger.info(f"Transcribing {file.filename} ({len(content)} bytes)")

        # Load audio
        audio = whisperx.load_audio(audio_path)

        # Transcribe
        result = whisper_model.transcribe(audio, batch_size=16)
        logger.info(f"Transcription complete, {len(result.get('segments', []))} segments")

        # Align
        try:
            model_a, metadata = whisperx.load_align_model(
                language_code=language,
                device="cuda"
            )
            result = whisperx.align(
                result["segments"],
                model_a,
                metadata,
                audio,
                "cuda",
                return_char_alignments=False
            )
            logger.info("Alignment complete")
        except Exception as e:
            logger.warning(f"Alignment failed: {e}, continuing without alignment")

        # Diarize
        if diarize and diarize_model is not None:
            try:
                diarize_segments = diarize_model(audio_path)
                result = whisperx.assign_word_speakers(diarize_segments, result)
                logger.info("Diarization complete")
            except Exception as e:
                logger.warning(f"Diarization failed: {e}, continuing without speakers")

        # Format response
        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", ""),
                "speaker": seg.get("speaker", "UNKNOWN")
            })

        return {"segments": segments, "language": language}

    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Cleanup temp file
        if os.path.exists(audio_path):
            os.unlink(audio_path)


@app.post("/parse_pdf")
async def parse_pdf(
    file: UploadFile = File(...),
    lang: str = Form(default="en"),
    backend: str = Form(default="transformers")
):
    """
    Parse PDF using MinerU VLM.

    Args:
        file: PDF file
        lang: Language code for OCR (default: "en")
        backend: VLM backend - "transformers" or "sglang-engine" (default: "transformers")

    Returns:
        result: Parsed document structure (middle_json)
        markdown: Extracted text as markdown
    """
    from mineru.backend.vlm.vlm_analyze import doc_analyze
    from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
    from mineru.utils.enum_class import MakeMode
    from mineru.data.data_reader_writer import FileBasedDataWriter

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Save uploaded file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        content = await file.read()
        f.write(content)
        pdf_path = f.name

    # Create temp dir for images
    temp_dir = tempfile.mkdtemp()

    try:
        logger.info(f"Parsing PDF {file.filename} ({len(content)} bytes)")

        # Read PDF bytes
        pdf_bytes = open(pdf_path, "rb").read()

        # Create image writer
        image_writer = FileBasedDataWriter(temp_dir)

        # Parse with MinerU VLM
        middle_json, infer_result = doc_analyze(
            pdf_bytes,
            image_writer=image_writer,
            backend=backend
        )

        logger.info("PDF parsing complete")

        # Generate markdown
        pdf_info = middle_json.get("pdf_info", {})
        md_content = union_make(pdf_info, MakeMode.MM_MD, "images")

        return {
            "result": middle_json,
            "markdown": md_content,
            "raw_output": infer_result if isinstance(infer_result, list) else [str(infer_result)]
        }

    except Exception as e:
        logger.error(f"PDF parsing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Cleanup
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
