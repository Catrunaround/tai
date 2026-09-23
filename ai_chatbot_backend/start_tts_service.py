#!/usr/bin/env python3
"""Standalone CosyVoice service: python start_tts_service.py (port 8011).

Run in the CosyVoice Python environment with COSYVOICE_HOME pointing at its
source checkout. See docs/tts-service.md for setup and request examples.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import uuid
import wave
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

PUBLIC_HOST = "128.32.43.46"
PORT = 8011
MODEL_NAME = "cosyvoice"
SAMPLE_RATE = 24000  # Matches app.core.models.chat_completion.AudioSpec.
DEFAULT_MODEL = "iic/CosyVoice2-0.5B"
DEFAULT_PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
BACKEND_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("tai.tts")


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    prompt_text: str | None = Field(default=None, min_length=1, max_length=4000)
    prompt_audio: str | None = Field(
        default=None,
        max_length=12 * 1024 * 1024,
        description="Base64 WAV reference, paired with prompt_text. Omit both for the default voice.",
    )

    @field_validator("text", "prompt_text")
    @classmethod
    def strip_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank")
        return value.strip() if value is not None else None


class ChatRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list[dict] = Field(min_length=1, max_length=3)
    stream: bool = True


def validate_reference(audio: bytes) -> None:
    """Reject invalid references before starting model inference."""
    try:
        info = sf.info(io.BytesIO(audio))
    except (RuntimeError, ValueError) as exc:
        raise ValueError("Reference audio must be a valid WAV file") from exc
    if info.format not in {"WAV", "WAVEX"}:
        raise ValueError("Reference audio must be a WAV file")
    if info.samplerate < 16000 or not 0 < info.duration <= 30:
        raise ValueError(
            "Reference WAV must be at least 16 kHz and between 0 and 30 seconds"
        )


def as_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return output.getvalue()


class CosyVoiceEngine:
    def __init__(self, model_dir: str):
        # Heavy imports/model loading happen only during application startup.
        from cosyvoice.cli.cosyvoice import AutoModel

        self.model = AutoModel(model_dir=model_dir)

    def synthesize(self, text: str, prompt_text: str, reference: bytes) -> bytes:
        # Current official CosyVoice accepts a WAV path as its prompt_wav.
        with tempfile.TemporaryDirectory(prefix="tai_tts_") as directory:
            prompt_path = Path(directory) / "reference.wav"
            prompt_path.write_bytes(reference)
            chunks = []
            for result in self.model.inference_zero_shot(
                text,
                prompt_text,
                str(prompt_path),
                stream=False,
            ):
                speech = result["tts_speech"].detach().cpu().float()
                if self.model.sample_rate != SAMPLE_RATE:
                    from torchaudio.functional import resample

                    speech = resample(speech, self.model.sample_rate, SAMPLE_RATE)
                samples = speech.numpy().reshape(-1)
                if not np.isfinite(samples).all():
                    raise RuntimeError("CosyVoice returned non-finite audio samples")
                # Clip before int16 conversion: +1.0 must not wrap to -32768.
                chunks.append(
                    np.clip(np.rint(samples * 32768), -32768, 32767)
                    .astype("<i2")
                    .tobytes()
                )
        pcm = b"".join(chunks)
        if not pcm:
            raise RuntimeError("CosyVoice produced no audio")
        return pcm


def chat_to_speech(request: ChatRequest) -> SpeechRequest:
    """Accept the single-user or user/audio-reference/user shape used by TAI."""
    messages = request.messages
    target = messages[-1]
    if target.get("role") != "user" or not isinstance(target.get("content"), str):
        raise HTTPException(422, "The last message must contain user text")
    fields = {"text": target["content"]}
    if len(messages) != 1:
        if (
            len(messages) != 3
            or messages[0].get("role") != "user"
            or messages[1].get("role") != "assistant"
        ):
            raise HTTPException(
                422, "Use one user message or user/assistant-audio/user messages"
            )
        content = messages[1].get("content")
        if (
            not isinstance(content, list)
            or len(content) != 1
            or not isinstance(content[0], dict)
        ):
            raise HTTPException(
                422, "The assistant reference must contain one input_audio item"
            )
        item = content[0]
        audio = item.get("input_audio")
        if (
            item.get("type") != "input_audio"
            or not isinstance(audio, dict)
            or audio.get("format") != "wav"
        ):
            raise HTTPException(
                422, "The assistant reference must be input_audio in WAV format"
            )
        fields.update(
            prompt_text=messages[0].get("content"), prompt_audio=audio.get("data")
        )
        if not isinstance(fields["prompt_text"], str) or not isinstance(
            fields["prompt_audio"], str
        ):
            raise HTTPException(422, "Reference text and base64 WAV data are required")
    try:
        return SpeechRequest(**fields)
    except ValidationError as exc:
        raise HTTPException(
            422, "Invalid speech text or reference audio fields"
        ) from exc


def create_app(
    engine_factory,
    default_reference: bytes,
    default_prompt_text: str,
    api_key: str = "",
) -> FastAPI:
    """Keep this service independent of the chatbot's DB and LLM settings."""
    inference_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        validate_reference(default_reference)
        app.state.engine = engine_factory()
        try:
            yield
        finally:
            del app.state.engine

    app = FastAPI(title="TAI CosyVoice TTS Service", version="1.0.0", lifespan=lifespan)

    def authorize(authorization: str | None = Header(default=None)):
        if api_key and api_key != "EMPTY":
            if not secrets.compare_digest(authorization or "", f"Bearer {api_key}"):
                raise HTTPException(
                    401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"}
                )

    def synthesize(request: SpeechRequest) -> bytes:
        if (request.prompt_text is None) != (request.prompt_audio is None):
            raise HTTPException(422, "Provide prompt_text and prompt_audio together")
        reference = default_reference
        prompt_text = default_prompt_text
        if request.prompt_audio is not None:
            try:
                reference = base64.b64decode(request.prompt_audio, validate=True)
                validate_reference(reference)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(
                    422, "Invalid reference audio: " + str(exc)
                ) from exc
            prompt_text = request.prompt_text
        # Sync routes run in FastAPI's thread pool, keeping /health responsive.
        # Complete inference before sending audio so failures return HTTP 500.
        try:
            with inference_lock:
                pcm = app.state.engine.synthesize(request.text, prompt_text, reference)
            if not pcm or len(pcm) % 2:
                raise RuntimeError("The model returned empty or invalid PCM audio")
            return pcm
        except Exception as exc:
            logger.exception("CosyVoice inference failed")
            raise HTTPException(
                500, "Speech synthesis failed; check the TTS server log"
            ) from exc

    @app.get("/health")
    def health():
        if not hasattr(app.state, "engine"):
            raise HTTPException(503, "TTS model is not ready")
        return {
            "status": "ok",
            "service": "tai-tts",
            "model": MODEL_NAME,
            "sample_rate": SAMPLE_RATE,
        }

    @app.get("/v1/models", dependencies=[Depends(authorize)])
    def models():
        return {
            "object": "list",
            "data": [
                {"id": MODEL_NAME, "object": "model", "created": 0, "owned_by": "tai"}
            ],
        }

    @app.post("/tts", dependencies=[Depends(authorize)])
    def tts(request: SpeechRequest):
        return Response(as_wav(synthesize(request)), media_type="audio/wav")

    @app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    def chat_completions(request: ChatRequest):
        if request.model != MODEL_NAME:
            raise HTTPException(404, f"Unknown model; use {MODEL_NAME}")
        speech = chat_to_speech(request)
        pcm = synthesize(speech)
        identifier = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        if not request.stream:
            return {
                "id": identifier,
                "object": "chat.completion",
                "created": created,
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "audio": {
                                "data": base64.b64encode(pcm).decode("ascii"),
                                "transcript": speech.text,
                            },
                        },
                    }
                ],
            }

        def events():
            # Buffered SSE compatibility for the existing audio_generator client.
            # Model inference is complete; this is not incremental synthesis.
            envelope = {
                "id": identifier,
                "object": "chat.completion.chunk",
                "created": created,
                "model": MODEL_NAME,
            }
            for offset in range(0, len(pcm), SAMPLE_RATE * 2):
                chunk = base64.b64encode(pcm[offset : offset + SAMPLE_RATE * 2]).decode(
                    "ascii"
                )
                data = {
                    **envelope,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"audio": {"data": chunk}},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(data)}\n\n"
            data = {
                **envelope,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(data)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def main():
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cosyvoice-home",
        default=os.getenv("COSYVOICE_HOME"),
        help="Official CosyVoice source checkout",
    )
    parser.add_argument(
        "--model-dir",
        default=os.getenv("COSYVOICE_MODEL_DIR", DEFAULT_MODEL),
        help="Local model directory or ModelScope model ID",
    )
    parser.add_argument(
        "--prompt-wav",
        default=os.getenv("COSYVOICE_PROMPT_WAV"),
        help="Default reference WAV (paired with --prompt-text)",
    )
    parser.add_argument(
        "--prompt-text",
        default=os.getenv("COSYVOICE_PROMPT_TEXT"),
        help="Transcript of the default reference WAV",
    )
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if not args.cosyvoice_home:
        parser.error(
            "Set COSYVOICE_HOME or --cosyvoice-home to the official CosyVoice checkout; see docs/tts-service.md"
        )
    cosyvoice_home = Path(args.cosyvoice_home).expanduser().resolve()
    if not (cosyvoice_home / "cosyvoice/cli/cosyvoice.py").is_file():
        parser.error(f"Not a CosyVoice checkout: {cosyvoice_home}")
    if (args.prompt_wav is None) != (args.prompt_text is None):
        parser.error("Set --prompt-wav and --prompt-text together")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    prompt_wav = (
        Path(args.prompt_wav).expanduser().resolve()
        if args.prompt_wav
        else cosyvoice_home / "asset/zero_shot_prompt.wav"
    )
    prompt_text = (
        args.prompt_text if args.prompt_text is not None else DEFAULT_PROMPT_TEXT
    )
    if not prompt_wav.is_file() or not prompt_text.strip():
        parser.error("Provide an existing reference WAV and a nonblank transcript")
    sys.path[:0] = [str(cosyvoice_home), str(cosyvoice_home / "third_party/Matcha-TTS")]
    model_dir = (
        str(Path(args.model_dir).expanduser().resolve())
        if Path(args.model_dir).expanduser().exists()
        else args.model_dir
    )
    api_key = os.getenv("TTS_API_KEY", os.getenv("VLLM_API_KEY", ""))
    app = create_app(
        lambda: CosyVoiceEngine(model_dir),
        prompt_wav.read_bytes(),
        prompt_text,
        api_key,
    )

    import uvicorn

    print(f"Starting CosyVoice: http://{PUBLIC_HOST}:{args.port}/tts", flush=True)
    print(f"Backend base URL: http://{PUBLIC_HOST}:{args.port}/v1", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=args.port, workers=1)


if __name__ == "__main__":
    main()
