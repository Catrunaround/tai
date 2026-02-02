"""
Client for remote GPU service.

This client sends requests to a remote GPU server (e.g., RunPod Pod)
for ML model inference. Used by video_converter.py and convert.py
when GPU_SERVICE_URL is configured.
"""
import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class GPUServiceClient:
    """Client for remote GPU service endpoints."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 600):
        """
        Initialize GPU service client.

        Args:
            base_url: Base URL of GPU service (e.g., "http://runpod-ip:8000")
                      If not provided, reads from GPU_SERVICE_URL env var.
            timeout: Request timeout in seconds (default: 600 = 10 minutes)
        """
        self.base_url = (base_url or os.getenv("GPU_SERVICE_URL", "")).rstrip("/")
        self.timeout = timeout

        if not self.base_url:
            raise ValueError(
                "GPU_SERVICE_URL not set. Either pass base_url parameter "
                "or set GPU_SERVICE_URL environment variable."
            )

    def health_check(self) -> Dict:
        """
        Check if GPU service is running and healthy.

        Returns:
            Health status dict with keys: status, gpu, whisper_loaded, diarize_loaded

        Raises:
            requests.RequestException: If health check fails
        """
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"GPU service health check failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if GPU service is available (non-throwing)."""
        try:
            health = self.health_check()
            return health.get("status") == "ok"
        except Exception:
            return False

    def transcribe(
        self,
        audio_path: str,
        language: str = "en",
        diarize: bool = True
    ) -> List[Dict]:
        """
        Send audio file to remote GPU for transcription with speaker diarization.

        Args:
            audio_path: Path to local audio file (WAV, MP3, etc.)
            language: Language code (default: "en")
            diarize: Whether to perform speaker diarization (default: True)

        Returns:
            List of segments: [{start, end, text, speaker}, ...]

        Raises:
            FileNotFoundError: If audio file doesn't exist
            requests.RequestException: If API request fails
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Sending audio to remote GPU for transcription: {audio_path}")

        with open(audio_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/transcribe",
                files={"file": (os.path.basename(audio_path), f)},
                data={"language": language, "diarize": str(diarize).lower()},
                timeout=self.timeout
            )

        response.raise_for_status()
        result = response.json()

        segments = result.get("segments", [])
        logger.info(f"Transcription complete: {len(segments)} segments")

        return segments

    def parse_pdf(
        self,
        pdf_path: str,
        lang: str = "en",
        backend: str = "transformers"
    ) -> Dict:
        """
        Send PDF file to remote GPU for parsing with MinerU VLM.

        Args:
            pdf_path: Path to local PDF file
            lang: Language code for OCR (default: "en")
            backend: VLM backend - "transformers" or "sglang-engine"

        Returns:
            Dict with keys: result (middle_json), markdown, raw_output

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            requests.RequestException: If API request fails
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        logger.info(f"Sending PDF to remote GPU for parsing: {pdf_path}")

        with open(pdf_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/parse_pdf",
                files={"file": (os.path.basename(pdf_path), f)},
                data={"lang": lang, "backend": backend},
                timeout=self.timeout
            )

        response.raise_for_status()
        result = response.json()

        logger.info("PDF parsing complete")
        return result


def get_gpu_client() -> Optional[GPUServiceClient]:
    """
    Get GPU service client if configured.

    Returns:
        GPUServiceClient instance if GPU_SERVICE_URL is set, None otherwise
    """
    gpu_url = os.getenv("GPU_SERVICE_URL")
    if gpu_url:
        try:
            return GPUServiceClient(gpu_url)
        except ValueError:
            return None
    return None


def is_remote_gpu_available() -> bool:
    """Check if remote GPU service is configured and available."""
    client = get_gpu_client()
    if client:
        return client.is_available()
    return False
