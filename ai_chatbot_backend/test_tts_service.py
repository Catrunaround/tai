"""HTTP/audio contract tests without downloading CosyVoice or loading a GPU."""

import base64
from concurrent.futures import ThreadPoolExecutor
import io
import threading
import wave

from fastapi.testclient import TestClient
import numpy as np
from openai import OpenAI
import pytest

from start_tts_service import CosyVoiceEngine, SAMPLE_RATE, as_wav, create_app


PCM = np.arange(30000, dtype="<i2").tobytes()
REFERENCE = as_wav(bytes(32000))


class Synthesizer:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, prompt_text, reference):
        self.calls.append((text, prompt_text, reference))
        return PCM


@pytest.fixture
def service():
    engine = Synthesizer()
    app = create_app(lambda: engine, REFERENCE, "Reference words.")
    with TestClient(app) as client:
        yield client, engine


def test_health_and_wav_response(service):
    client, engine = service
    assert client.get("/health").json()["status"] == "ok"
    response = client.post("/tts", json={"text": " Hello. "})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            SAMPLE_RATE,
            1,
            2,
        )
        assert wav.readframes(wav.getnframes()) == PCM
    assert engine.calls == [("Hello.", "Reference words.", REFERENCE)]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "   "},
        {"text": "x" * 4001},
        {"text": "Hello.", "prompt_text": "Missing audio"},
        {"text": "Hello.", "prompt_audio": "Missing transcript"},
        {"text": "Hello.", "prompt_text": "Test", "prompt_audio": "%%%"},
        {
            "text": "Hello.",
            "prompt_text": "Test",
            "prompt_audio": base64.b64encode(b"not audio").decode(),
        },
    ],
)
def test_invalid_requests_do_not_run_model(service, payload):
    client, engine = service
    assert client.post("/tts", json=payload).status_code == 422
    assert not engine.calls


def test_custom_reference_and_existing_openai_client(service):
    client, engine = service
    sdk = OpenAI(base_url="http://testserver/v1", api_key="EMPTY", http_client=client)
    assert sdk.models.list().data[0].id == "cosyvoice"
    messages = [
        {"role": "user", "content": "Custom reference."},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": base64.b64encode(REFERENCE).decode(),
                        "format": "wav",
                    },
                }
            ],
        },
        {"role": "user", "content": "Say this."},
    ]
    stream = sdk.chat.completions.create(
        model="cosyvoice",
        messages=messages,
        stream=True,
        modalities=["text", "audio"],
        max_completion_tokens=500,
        extra_body={"top_k": 50},
    )
    chunks = list(stream)
    audio = b"".join(
        base64.b64decode(chunk.choices[0].delta.audio["data"])
        for chunk in chunks
        if getattr(chunk.choices[0].delta, "audio", None)
    )
    assert audio == PCM
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert engine.calls == [("Say this.", "Custom reference.", REFERENCE)]


def test_nonstreaming_chat_and_unknown_model(service):
    client, engine = service
    body = {
        "model": "cosyvoice",
        "messages": [{"role": "user", "content": "Hello."}],
        "stream": False,
    }
    response = client.post("/v1/chat/completions", json=body)
    assert response.status_code == 200
    assert (
        base64.b64decode(response.json()["choices"][0]["message"]["audio"]["data"])
        == PCM
    )
    body["model"] = "not-cosyvoice"
    assert client.post("/v1/chat/completions", json=body).status_code == 404
    assert len(engine.calls) == 1


def test_authentication_covers_model_and_inference_routes():
    engine = Synthesizer()
    with TestClient(
        create_app(lambda: engine, REFERENCE, "Reference", "test-key")
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/models").status_code == 401
        assert client.post("/tts", json={"text": "Hello"}).status_code == 401
        assert (
            client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            ).status_code
            == 401
        )
        response = client.post(
            "/tts", json={"text": "Hello"}, headers={"Authorization": "Bearer test-key"}
        )
        assert response.status_code == 200
        assert len(engine.calls) == 1


def test_model_failure_returns_http_error_before_sse_and_releases_lock():
    class FailOnce(Synthesizer):
        def synthesize(self, *args):
            if not self.calls:
                self.calls.append(args)
                raise RuntimeError("injected model failure")
            return super().synthesize(*args)

    with TestClient(create_app(FailOnce, REFERENCE, "Reference")) as client:
        body = {"messages": [{"role": "user", "content": "Hello"}], "stream": True}
        response = client.post("/v1/chat/completions", json=body)
        assert response.status_code == 500
        assert response.headers["content-type"] == "application/json"
        assert client.post("/tts", json={"text": "Retry"}).status_code == 200


def test_startup_does_not_claim_ready_without_model():
    app = create_app(
        lambda: (_ for _ in ()).throw(RuntimeError("load failed")),
        REFERENCE,
        "Reference",
    )
    assert TestClient(app).get("/health").status_code == 503
    with pytest.raises(RuntimeError, match="load failed"):
        with TestClient(app):
            pass


def test_parallel_inference_is_serialized_and_health_remains_responsive():
    entered = threading.Event()
    release = threading.Event()

    class SlowSynthesizer(Synthesizer):
        active = 0
        max_active = 0

        def synthesize(self, *args):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            entered.set()
            try:
                assert release.wait(5)
                return super().synthesize(*args)
            finally:
                self.active -= 1

    engine = SlowSynthesizer()
    with TestClient(create_app(lambda: engine, REFERENCE, "Reference")) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/tts", json={"text": "First"})
            assert entered.wait(5)
            second = pool.submit(client.post, "/tts", json={"text": "Second"})
            try:
                assert client.get("/health").status_code == 200
            finally:
                release.set()
            assert (
                first.result(timeout=5).status_code
                == second.result(timeout=5).status_code
                == 200
            )
    assert engine.max_active == 1
    assert len(engine.calls) == 2


def test_real_engine_adapter_clips_pcm_and_removes_temporary_reference():
    """Exercise the tensor-to-PCM adapter without importing CosyVoice."""
    from pathlib import Path

    class Tensor:
        def detach(self):
            return self

        cpu = detach
        float = detach

        def numpy(self):
            return np.array([[-1.5, -1, 0, 1, 1.5]], dtype=np.float32)

    class Model:
        sample_rate = SAMPLE_RATE

        def inference_zero_shot(self, text, prompt_text, path, stream):
            self.prompt_path = Path(path)
            assert self.prompt_path.read_bytes() == REFERENCE
            assert stream is False
            yield {"tts_speech": Tensor()}

    engine = CosyVoiceEngine.__new__(CosyVoiceEngine)
    engine.model = Model()
    pcm = engine.synthesize("Hello", "Reference", REFERENCE)
    assert np.frombuffer(pcm, dtype="<i2").tolist() == [-32768, -32768, 0, 32767, 32767]
    assert not engine.model.prompt_path.exists()
