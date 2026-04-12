"""Tests for whisperx after the PyTorch/CUDA upgrade.

Verifies that whisperx model loading, transcription, alignment, and the
VideoConverter integration all work correctly with the upgraded stack.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(scope="module")
def sample_wav(tmp_path_factory) -> Path:
    """Create a short WAV file with speech-like audio for testing.

    Uses a real lecture WAV if available, otherwise generates a synthetic
    tone (which whisperx will process but produce no text).
    """
    real_wav = Path(
        "/home/bot/bot/yk/YK_final/courses_out/CS 61A_new/study/lecture/"
        "lec03/youtube03/Control/3-Conditional statements/"
        "3-Conditional statements.mkv.wav"
    )
    wav_dir = tmp_path_factory.mktemp("wav_input")
    wav_path = wav_dir / "test_audio.wav"

    if real_wav.exists():
        # Copy first 15 seconds of the real lecture audio
        import whisperx
        audio = whisperx.load_audio(str(real_wav))
        clip = audio[: 16000 * 15]  # 15 seconds at 16kHz
        sf.write(str(wav_path), clip, 16000)
    else:
        # Fallback: generate a 5-second sine wave
        sr = 16000
        t = np.linspace(0, 5, sr * 5, dtype=np.float32)
        tone = 0.5 * np.sin(2 * np.pi * 440 * t)
        sf.write(str(wav_path), tone, sr)

    return wav_path


# ---------------------------------------------------------------------------
# Test 1: Model loading on CUDA
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_whisperx_model_loading():
    """Verify whisperx model loads on CUDA without errors."""
    import torch
    import whisperx

    assert torch.cuda.is_available(), "CUDA not available"

    model = whisperx.load_model(
        "large-v3", device="cuda", compute_type="float16", language="en"
    )
    assert model is not None, "Model failed to load"


# ---------------------------------------------------------------------------
# Test 2: Transcription produces valid output
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_whisperx_transcription(sample_wav):
    """Verify whisperx transcription returns segments with expected structure."""
    import whisperx

    model = whisperx.load_model(
        "large-v3", device="cuda", compute_type="float16", language="en"
    )
    audio = whisperx.load_audio(str(sample_wav))
    result = model.transcribe(audio, batch_size=16)

    # Result should have 'segments' key
    assert "segments" in result, f"Missing 'segments' key, got keys: {list(result.keys())}"
    assert isinstance(result["segments"], list), "segments should be a list"

    # Each segment should have start, end, text
    for seg in result["segments"]:
        assert "start" in seg, f"Segment missing 'start': {seg}"
        assert "end" in seg, f"Segment missing 'end': {seg}"
        assert "text" in seg, f"Segment missing 'text': {seg}"
        assert isinstance(seg["text"], str), f"Segment text should be str: {seg}"
        assert seg["end"] >= seg["start"], f"end < start: {seg}"


# ---------------------------------------------------------------------------
# Test 3: Alignment produces valid output
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_whisperx_alignment(sample_wav):
    """Verify whisperx alignment works and returns segments."""
    import whisperx

    model = whisperx.load_model(
        "large-v3", device="cuda", compute_type="float16", language="en"
    )
    audio = whisperx.load_audio(str(sample_wav))
    result = model.transcribe(audio, batch_size=16)

    if not result["segments"]:
        pytest.skip("No segments to align (synthetic audio)")

    model_a, metadata = whisperx.load_align_model(language_code="en", device="cuda")
    result_aligned = whisperx.align(
        result["segments"], model_a, metadata, audio, "cuda",
        return_char_alignments=False,
    )

    assert "segments" in result_aligned, "Aligned result missing 'segments'"
    assert len(result_aligned["segments"]) > 0, "Alignment produced no segments"

    for seg in result_aligned["segments"]:
        assert "start" in seg, f"Aligned segment missing 'start': {seg}"
        assert "end" in seg, f"Aligned segment missing 'end': {seg}"
        assert "text" in seg, f"Aligned segment missing 'text': {seg}"


# ---------------------------------------------------------------------------
# Test 4: VideoConverter._video_convert_whisperx integration
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_video_converter_whisperx(sample_wav):
    """Verify VideoConverter._video_convert_whisperx returns valid segments."""
    from file_conversion_router.conversion.video_converter import VideoConverter

    converter = VideoConverter(
        course_name="Test Course",
        course_code="TEST101",
    )

    segments = converter._video_convert_whisperx(str(sample_wav))

    assert isinstance(segments, list), f"Expected list, got {type(segments)}"

    for seg in segments:
        assert "start" in seg, f"Segment missing 'start': {seg}"
        assert "end" in seg, f"Segment missing 'end': {seg}"
        assert "text" in seg, f"Segment missing 'text': {seg}"
        assert "speaker" in seg, f"Segment missing 'speaker': {seg}"
        assert isinstance(seg["speaker"], str), f"Speaker should be str: {seg}"
        assert seg["end"] >= seg["start"], f"end < start: {seg}"


# ---------------------------------------------------------------------------
# Test 5: Paragraph generation and markdown output
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_paragraph_generator_and_markdown(sample_wav):
    """Verify paragraph generation and markdown output from transcription segments."""
    from file_conversion_router.conversion.video_converter import VideoConverter

    converter = VideoConverter(
        course_name="Test Course",
        course_code="TEST101",
    )

    # Create mock segments (known structure, independent of whisperx)
    mock_segments = [
        {"start": 0.0, "end": 5.0, "text": "Hello, welcome to the lecture.", "speaker": "SPEAKER_00"},
        {"start": 5.0, "end": 10.0, "text": "Today we discuss functions.", "speaker": "SPEAKER_00"},
        {"start": 10.0, "end": 15.0, "text": "Can you explain that?", "speaker": "SPEAKER_01"},
        {"start": 15.0, "end": 20.0, "text": "Sure, let me elaborate.", "speaker": "SPEAKER_00"},
    ]
    mock_scene_times = [(0.0, 12.0), (12.0, 25.0)]

    paragraphs = converter.paragraph_generator(mock_segments, mock_scene_times)

    # Should produce 2 paragraphs (one per scene)
    assert isinstance(paragraphs, list), f"Expected list, got {type(paragraphs)}"
    assert len(paragraphs) == 2, f"Expected 2 paragraphs, got {len(paragraphs)}"

    # Each paragraph has start_time and utterances
    for para in paragraphs:
        assert "start_time" in para, f"Paragraph missing 'start_time': {para}"
        assert "utterances" in para, f"Paragraph missing 'utterances': {para}"
        for utt in para["utterances"]:
            assert "speaker" in utt, f"Utterance missing 'speaker': {utt}"
            assert "text" in utt, f"Utterance missing 'text': {utt}"

    # index_helper should be populated
    assert converter.index_helper is not None, "index_helper not set"
    assert isinstance(converter.index_helper, dict), (
        f"index_helper should be dict, got {type(converter.index_helper)}"
    )

    # Markdown output
    md = converter.write_to_markdown(paragraphs)
    assert isinstance(md, str), "Markdown output should be a string"
    assert len(md.strip()) > 0, "Markdown output is empty"
    assert "SPEAKER_00" in md, "Markdown missing speaker label"


# ---------------------------------------------------------------------------
# Test 6: JSON output format
# ---------------------------------------------------------------------------

@pytest.mark.ocr
def test_speaker_json_output(sample_wav, tmp_path):
    """Verify get_speaker_json writes valid JSON with expected structure."""
    from file_conversion_router.conversion.video_converter import VideoConverter

    converter = VideoConverter(
        course_name="Test Course",
        course_code="TEST101",
    )

    mock_segments = [
        {"start": 0.0, "end": 5.0, "text": "Hello world.", "speaker": "SPEAKER_00"},
        {"start": 5.0, "end": 10.0, "text": "Testing output.", "speaker": "SPEAKER_01"},
    ]

    json_path = tmp_path / "output.json"
    converter.get_speaker_json(mock_segments, str(json_path))

    assert json_path.exists(), f"JSON file not created: {json_path}"
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list), "JSON should be a list"
    assert len(data) == 2, f"Expected 2 entries, got {len(data)}"

    for entry in data:
        assert "start time" in entry, f"Entry missing 'start time': {entry}"
        assert "end time" in entry, f"Entry missing 'end time': {entry}"
        assert "speaker" in entry, f"Entry missing 'speaker': {entry}"
        assert "text content" in entry, f"Entry missing 'text content': {entry}"
