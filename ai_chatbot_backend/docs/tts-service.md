# Standalone CosyVoice service

Start a separate TTS model service on `128.32.43.46:8011` using one Python file.
It loads CosyVoice locally, exposes `POST /tts`, and provides the message/audio
protocol used by the existing TAI TTS client at `/v1/chat/completions`.

## Prepare once on the GPU server

Use the [official CosyVoice installation instructions](https://github.com/FunAudioLLM/CosyVoice#install)
to create its Python environment, install its dependencies, and clone the source
with submodules. Run this service with that environment's Python. The chatbot's
Poetry environment alone does not install CosyVoice.

Ensure the small HTTP-service dependencies are installed in that environment:

```bash
python -m pip install fastapi uvicorn python-dotenv soundfile "pydantic>=2"
```

Set these values in `ai_chatbot_backend/.env` or export them in the server shell:

```dotenv
COSYVOICE_HOME=/absolute/path/to/CosyVoice
COSYVOICE_MODEL_DIR=iic/CosyVoice2-0.5B
```

`COSYVOICE_MODEL_DIR` can instead point to an existing local model directory.
The default model matches the [official FastAPI server](https://github.com/FunAudioLLM/CosyVoice/blob/main/runtime/python/fastapi/server.py);
the first startup downloads the weights through ModelScope if they are not cached.
The implementation uses the current official `AutoModel` and WAV-path inference API.

The default voice uses the official checkout's `asset/zero_shot_prompt.wav` and
its example transcript. To choose a different default voice, set **both**:

```dotenv
COSYVOICE_PROMPT_WAV=/absolute/path/to/reference.wav
COSYVOICE_PROMPT_TEXT=The exact words spoken in the reference WAV.
```

Reference WAVs must have a sample rate of at least 16 kHz and a duration of at
most 30 seconds. Individual requests can supply their own reference instead.
`TTS_API_KEY` overrides the existing `VLLM_API_KEY`; an unset key or `EMPTY`
keeps the service unauthenticated. Configured keys are never printed by the launcher.

## Start

After SSH login to `128.32.43.46`, activate the CosyVoice environment and run from
the TAI repository root:

```bash
python ai_chatbot_backend/start_tts_service.py
```

The process listens on `0.0.0.0:8011`. It runs in the foreground, with one model
instance and serialized inference; use Ctrl+C to stop, or `tmux` to retain it
after SSH disconnects. To select a GPU, set `CUDA_VISIBLE_DEVICES` before starting.
All options are listed by `python ai_chatbot_backend/start_tts_service.py --help`.

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Reports ready after reference validation and model loading |
| `POST /tts` | JSON text to a 24 kHz, mono, signed 16-bit WAV |
| `GET /v1/models` | Lists the served model alias `cosyvoice` |
| `POST /v1/chat/completions` | Existing TAI audio-message / PCM SSE contract |
| `GET /docs` | Interactive request documentation |

## Test

```bash
curl --fail http://128.32.43.46:8011/health

# Set TTS_API_KEY here if the service requires authentication.
curl --fail http://128.32.43.46:8011/tts \
  -H "Authorization: Bearer ${TTS_API_KEY:-EMPTY}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello, the TAI speech service is running."}' \
  --output speech.wav
```

For a custom voice, include `prompt_text` and `prompt_audio` (base64 WAV bytes)
in the same JSON request. Blank text, missing reference pairs, and invalid audio
are rejected before inference.

## Connect the existing backend

After the server has passed a real synthesis test, set the following in the
backend's `.env` and restart the backend:

```dotenv
VLLM_TTS_URL=http://128.32.43.46:8011/v1
VLLM_TTS_MODEL=cosyvoice
```

If authentication is enabled, the backend's `VLLM_API_KEY` must match the service
key. The existing client also needs its `ai_chatbot_backend/voice_prompts/` WAV
and transcript files; those files are not supplied by this launcher.

The compatibility route accepts either one user text message, or the existing
user-reference-text / assistant-input-audio / user-target-text sequence. It emits
base64 PCM at 24 kHz, matching `AudioSpec`. Inference completes before audio is
returned; `stream=true` sends buffered SSE chunks, not incremental model output.
This keeps synthesis failures visible as HTTP 500 and releases the inference
lock before audio delivery. The route supports the TAI audio subset of the chat
protocol; it is not a general chat model or an implementation of sampling controls.

Local tests use an injected synthesizer to verify the HTTP, audio, error, and
client contracts. They do not establish real GPU inference or remote readiness.

```bash
cd ai_chatbot_backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -c /dev/null -p no:cacheprovider -q test_tts_service.py
```
