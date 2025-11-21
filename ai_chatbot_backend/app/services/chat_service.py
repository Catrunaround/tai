from app.core.models.chat_completion import *
from typing import AsyncIterator, List, Any, Dict
import re
import os
import base64
import io
import soundfile as sf
import numpy as np
from openai import OpenAI
from app.services.rag_postprocess import extract_channels, extract_json_array
from app.services.rag_generation import enhance_references_v2

def extract_channels_oss(text: str) -> dict:
    # 1) Remove the special marker wherever it appears
    cleaned = re.sub(r"<\|start\|\>assistant\s*", "", text)

    # 2) Capture channel/message pairs; message ends at next channel, <|end|>, or end-of-text
    pattern = re.compile(
        r"<\|channel\|\>(?P<channel>[A-Za-z0-9_]+)\s*"
        r"<\|message\|\>(?P<message>.*?)(?=(?:<\|channel\|\>|<\|end\|\>|\Z))",
        re.DOTALL
    )

    result = {}
    for m in pattern.finditer(cleaned):
        ch = m.group("channel").strip()
        msg = m.group("message").strip()
        result[ch] = msg  # if duplicate channels appear, the last one wins
    return result


def extract_answer_from_streaming_json(text: str) -> dict:
    """
    Extract clean answer text from streaming JSON without showing JSON syntax.

    This function progressively extracts the 'answer' field value from a JSON object
    being streamed, hiding JSON syntax like braces, quotes, and field names.

    Args:
        text: Partial or complete JSON text like '{"answer": "Python uses..."}'

    Returns:
        dict with:
            - 'answer': Clean extracted answer text (empty if not yet extractable)
            - 'complete': Boolean indicating if JSON is complete
            - 'mentioned_contexts': List of reference dicts (only when complete)
    """
    import json as json_lib

    result = {
        'answer': '',
        'complete': False,
        'mentioned_contexts': []
    }

    # Try to parse as complete JSON first
    try:
        parsed = json_lib.loads(text)
        if isinstance(parsed, dict) and 'answer' in parsed:
            result['answer'] = parsed['answer']
            result['complete'] = True
            result['mentioned_contexts'] = parsed.get('mentioned_contexts', [])
            return result
    except (json_lib.JSONDecodeError, ValueError):
        pass

    # If not complete JSON, try to extract answer field progressively
    # Match: {"answer": "text content that might be incomplete
    # We want to extract only the text content part
    answer_pattern = re.compile(
        r'\{\s*"answer"\s*:\s*"((?:[^"\\]|\\.)*)',
        re.DOTALL
    )

    match = answer_pattern.search(text)
    if match:
        # Extract the answer content, unescaping JSON string escapes
        raw_answer = match.group(1)
        # Unescape common JSON escapes
        answer_text = raw_answer.replace(r'\"', '"').replace(r'\\', '\\').replace(r'\n', '\n')
        result['answer'] = answer_text

    return result

async def chat_stream_parser(
        stream: AsyncIterator, reference_list: List[str], audio: bool = False, messages: List[Message]= None,audio_text: str=None, engine: Any = None, old_sid: str = "", course_code: str = None, debug: bool = False, use_json_array: bool = False, use_simple_json: bool = False
) -> AsyncIterator[str]:
    """
    Parse the streaming response from the chat model and yield deltas.

    Args:
        use_simple_json: If True, uses clean streaming extraction from JSON format
                        {"answer": "text", "mentioned_contexts": [{"reference": 1}]}
                        Streams only the answer text without JSON syntax.
    """
    if audio_text:
        yield sse(AudioTranscript(text=audio_text))
    previous_channels = {}
    previous_index = -2
    text_seq = 0
    voice_seq=0
    audio_messages = []

    # For simple JSON streaming - tracks clean answer text without JSON syntax
    previous_answer_len = 0
    json_complete = False
    final_mentioned_contexts = []

    PARTIAL_TAIL_GUARD = re.compile(r"""
    (?ix)
    (?:                                     # 只要还没到"完整终止"的形态，都算未完成；匹配到结尾
        \[\s*ref(?:erence)?\s*:?\s*         # [Reference: / [Ref / [reference
        (?:\d+(?:\s*(?:,|\band\b|&)\s*\d+)*)?   # 可有部分数字序列
        \s*(?:,|\band\b|&)?                 # 允许以分隔符结尾（说明还没写完下一个数字）
        \s*\Z
      |
        (?<![A-Za-z])(?:references?|ref)\s* # 行文式开头：reference / references / ref
        (?:\d+(?:\s*(?:,|\band\b|&)\s*\d+)*)?
        \s*(?:,|\band\b|&)?                 # 允许以分隔符结尾
        \s*\Z
      |
        \[\s*\Z                              # 只有一个 '[' 到结尾
    )
    """, re.VERBOSE)
    async for output in stream:
        text = output.outputs[0].text

        # Simple JSON format: {"answer": "text", "mentioned_contexts": [{"reference": 1}]}
        if use_simple_json:
            # Extract clean answer text from streaming JSON (hides JSON syntax)
            extracted = extract_answer_from_streaming_json(text)
            current_answer = extracted['answer']

            # Only stream new content (incremental diff)
            if len(current_answer) > previous_answer_len:
                new_chunk = current_answer[previous_answer_len:]
                previous_answer_len = len(current_answer)

                # Stream the new text chunk to frontend
                yield sse(ResponseDelta(seq=text_seq, text_channel='final', text=new_chunk))
                text_seq += 1
                print(new_chunk, end="", flush=True)

            # When JSON is complete, store data for reference extraction
            if extracted['complete'] and not json_complete:
                json_complete = True
                channels = {'final': current_answer}
                final_mentioned_contexts = extracted.get('mentioned_contexts', [])
                # Continue to reference handling below
            else:
                continue

        elif use_json_array:
            # Legacy JSON array format (kept for backward compatibility)
            json_data = extract_json_array(text)
            all_answers = " ".join([obj["answer"] for obj in json_data["objects"]])
            if json_data["current_partial"]:
                all_answers += (" " if all_answers else "") + json_data["current_partial"]
            channels = {
                "analysis": json_data["analysis"],
                "final": all_answers.strip()
            }
        else:
            # Use existing extract_channels logic (channel-based format)
            channels = extract_channels(text)

        if not channels:
            continue
        chunks= {c: channels[c][len(previous_channels.get(c,"")):] for c in channels if channels[c] != previous_channels.get(c,"")}
        if not chunks:
            continue
        continue_flag = False
        for channel in chunks:
            chunk = chunks[channel]
            if not chunk.strip():
                continue
            if PARTIAL_TAIL_GUARD.search(channels[channel][-100:]):
                # if PARTIAL_TAIL_GUARD.search(channels[channel][-50:]):
                #     print("[DEBUG] Skipping partial reference chunk:" + repr(channels[channel][-50:]))
                continue_flag = True
                break
            yield sse(ResponseDelta(seq=text_seq, text_channel=channel, text=chunk)); text_seq += 1
            print(chunk, end="")
        if continue_flag:
            continue
        previous_channels = channels
        if audio and 'final' in channels:
            last_newline_index = channels['final'].rfind('. ')
            if last_newline_index >previous_index+2:
                audio_text = channels['final'][previous_index + 2:last_newline_index+2]
                previous_index = last_newline_index
                #replace all the consecutive \n with space no matter how many \n
                # audio_text = re.sub(r'\n+', ' ', audio_text)
                if audio_text.strip()== "":
                    continue
                messages_to_send= audio_text.split('. ')
                for msg in messages_to_send:
                    if msg.strip():
                        audio_messages.append({"role": "user", "content": msg + '. '})
                        print("\n[INFO] Audio text:")
                        print(msg + '. ')
                        speaker_name = get_speaker_name(course_code)
                        audio_iterator = audio_generator(audio_messages, stream=True, speaker_name=speaker_name)
                        audio_bytes_io = io.BytesIO()
                        async for data in audio_iterator:
                            yield sse(ResponseDelta(seq=voice_seq, audio_b64=data, audio_spec=AudioSpec())); voice_seq += 1
                            audio_bytes = base64.b64decode(data)
                            audio_bytes_io.write(audio_bytes)
                        audio_data = np.frombuffer(audio_bytes_io.getvalue(), dtype=np.int16)
                        audio2_base64 = convert_audio_to_base64(audio_data, 24000, target_format="wav")
                        audio_messages.append({
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": audio2_base64,
                                        "format": "wav",
                                    },
                                }
                            ],
                        })
    else:
        chunks = {c: channels[c][len(previous_channels.get(c, "")):] for c in channels if
                  channels[c] != previous_channels.get(c, "")}
        for channel in chunks:
            chunk = chunks[channel]
            if not chunk.strip():
                continue
            yield sse(ResponseDelta(seq=text_seq, text_channel=channel, text=chunk));
            text_seq += 1
            print(chunk, end="")
        if audio and 'final' in channels:
            audio_text = channels['final'][previous_index + 2:]
            # replace all the consecutive \n with space no matter how many \n
            # yield sse(ResponseDelta(seq=text_seq, text=audio_text)); text_seq += 1
            if audio_text.strip():
                messages_to_send = audio_text.split('. ')
                for msg in messages_to_send:
                    if msg.strip():
                        audio_messages.append({"role": "user", "content": msg + '. '})
                        print("\n[INFO] Audio text:")
                        print(msg + '. ')
                        speaker_name= get_speaker_name(course_code)
                        audio_iterator = audio_generator(audio_messages, stream=True, speaker_name=speaker_name)
                        audio_bytes_io = io.BytesIO()
                        async for data in audio_iterator:
                            yield sse(ResponseDelta(seq=voice_seq, audio_b64=data, audio_spec=AudioSpec(),speaker_name=speaker_name));
                            voice_seq += 1
                            audio_bytes = base64.b64decode(data)
                            audio_bytes_io.write(audio_bytes)
                        audio_data = np.frombuffer(audio_bytes_io.getvalue(), dtype=np.int16)
                        audio2_base64 = convert_audio_to_base64(audio_data, 24000, target_format="wav")
                        audio_messages.append({
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": audio2_base64,
                                        "format": "wav",
                                    },
                                }
                            ],
                        })

    # # convert token ids to text
    # print("\n[INFO] Full response text:")
    # from transformers import AutoTokenizer
    # TOKENIZER_MODEL_ID = "openai/gpt-oss-20b"
    # TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_MODEL_ID)
    # full_response_text = TOKENIZER.decode(token, skip_special_tokens=False)
    # print(full_response_text)

    # Handle structured JSON responses - extract BOTH answer AND references, then move to 'final' channel
    import json as json_lib
    mentioned_references = set()
    parsed_json = None
    original_json_content = None  # Preserve for enhance_references_v2

    # Priority 1: Use final_mentioned_contexts from simple JSON streaming
    if use_simple_json and final_mentioned_contexts:
        print(f"[INFO] Using mentioned_contexts from simple JSON format")
        for ctx in final_mentioned_contexts:
            if isinstance(ctx, dict) and 'reference' in ctx:
                mentioned_references.add(int(ctx['reference']))

    # Priority 2: Try parsing JSON from channels (backward compatibility)
    if not mentioned_references:
        for channel_name in ['analysis', 'final']:
            channel_content = channels.get(channel_name, '')
            if channel_content and channel_content.strip().startswith('{'):
                print(f"\n[DEBUG] Attempting to parse JSON from '{channel_name}' channel...")
                try:
                    parsed = json_lib.loads(channel_content)
                    print(f"[DEBUG] Successfully parsed JSON!")
                    print(f"[DEBUG] JSON keys: {list(parsed.keys())}")
                    print(f"[DEBUG] Full JSON structure: {json_lib.dumps(parsed, indent=2)[:500]}...")

                    if isinstance(parsed, dict) and 'answer' in parsed:
                        parsed_json = parsed
                        original_json_content = channel_content  # Save original JSON string
                        answer = parsed['answer']
                        print(f"\n[INFO] Detected structured JSON in '{channel_name}' channel, extracting answer ({len(answer)} chars)")

                        # Extract reference numbers from mentioned_contexts BEFORE modifying channels
                        mentioned_contexts = parsed.get('mentioned_contexts', [])
                        print(f"[DEBUG] mentioned_contexts: {mentioned_contexts}")
                        for ctx in mentioned_contexts:
                            if isinstance(ctx, dict) and 'reference' in ctx:
                                mentioned_references.add(int(ctx['reference']))

                    if mentioned_references:
                        print(f"[INFO] Extracted {len(mentioned_references)} references from structured JSON")

                    # Now move answer to 'final' channel for proper display
                    channels['final'] = answer
                    channels['analysis'] = ''
                    # Send the answer as a correction to replace the JSON that was streamed
                    yield sse(ResponseDelta(seq=text_seq, text_channel='final', text=answer))
                    text_seq += 1
                    break
                except (json_lib.JSONDecodeError, ValueError, TypeError) as e:
                    # Not valid JSON, continue with original content
                    print(f"[DEBUG] JSON parsing failed: {e}")
                    pass

    # If no references found in JSON, try regex pattern matching (backward compatibility)
    if not mentioned_references:
        pattern = re.compile(
            r'(?:\[Reference:\s*([\d,\s]+)\]'
            r'|\breference\s+(\d+(?:(?:\s*,\s*|\s*(?:and|&)\s*)\d+)*))',
            re.IGNORECASE
        )
        mentioned_references = {
            int(n)
            for m in pattern.finditer(channels['final'])
            for n in re.findall(r'\d+', m.group(1) or m.group(2))
        }
        if mentioned_references:
            print(f"\n[INFO] Extracted {len(mentioned_references)} references from text pattern")

    print(f"\n[INFO] Mentioned references: {mentioned_references}")
    references = []
    max_idx = len(reference_list)
    for i in sorted(mentioned_references):
        if 1 <= i <= max_idx:
            info_path, url, file_path, file_uuid,chunk_index = reference_list[i - 1]
            references.append(Reference(
                reference_idx=i,
                info_path=info_path,
                url=url,
                file_path=file_path,
                file_uuid=file_uuid,
                chunk_index=chunk_index
            ))
    if references:
        yield sse(ResponseReference(references=references))

    # Enhanced sentence-level citations with bbox and page_index
    try:
        # Use original JSON if available, otherwise use channels
        final_response = original_json_content or channels.get('final') or channels.get('analysis', '')
        answer_text, enhanced_refs = enhance_references_v2(final_response, reference_list)

        # Only send enhanced references if we have sentence-level citations
        if enhanced_refs and any(ref.get('sentences') for ref in enhanced_refs):
            print(f"\n[INFO] Sending enhanced citations for {len(enhanced_refs)} references")
            # Send enhanced references as a separate event
            # Frontend can use this for precise PDF highlighting
            yield sse(EnhancedCitations(
                answer=answer_text,
                references=enhanced_refs
            ))
    except Exception as e:
        print(f"[WARNING] Failed to enhance citations: {e}")
        # Continue without enhanced citations (graceful degradation)

    yield sse(Done())
    yield "data: [DONE]\n\n"  # Final done message for SSE clients

def encode_base64_content_from_file(file_path: str) -> str:
    """Encode a content from a local file to base64 format."""
    # Read the MP3 file as binary and encode it directly to Base64
    with open(file_path, "rb") as audio_file:
        audio_base64 = base64.b64encode(audio_file.read()).decode("utf-8")
    return audio_base64

def convert_audio_to_base64(audio: np.ndarray,
                            sampling_rate: int,
                            target_format: str = "wav") -> str:
    audio_buffer = io.BytesIO()
    sf.write(audio_buffer, audio, sampling_rate, format=target_format)
    return base64.b64encode(audio_buffer.getvalue()).decode('utf-8')

def format_audio_text_message(audio_text: str) -> List[Dict]:
    """
    Format the audio text message into the expected structure for the chat model.
    """
    # remove all the [] in text
    audio_text = re.sub(r'\[.*?\]', '', audio_text).replace('\n',' ').strip()
    print(f"[INFO] Audio text after cleaning: {audio_text}")
    return [{"role": "user", "content": audio_text}]

def get_speaker_name(course_code: str) -> str:
    if course_code == "CS 61A":
        return "Professor John DeNero"
    elif course_code in ["ROAR Academy", "CS 294-137"]:
        return "Professor Allen Yang"
    else:
        return "Professor Allen Yang"  # Default speaker name

async def audio_generator(messages: List[Dict], stream: bool = True, speaker_name: str = None
) -> AsyncIterator[str]:
    """
    Parse the streaming response from the audio model and yield deltas.
    """
    data_dir = '/home/bot/localgpt/tai/ai_chatbot_backend/voice_prompts'
    
    # Select voice prompt based on course_code
    if speaker_name == "Professor John DeNero":
        audio_file = "trees_54.wav"
        text_file = "trees_54.txt"
    elif speaker_name == "Professor Allen Yang":
        audio_file = "Allen_yang_voice.wav"
        text_file = "Allen_yang_voice.txt"
    else:
        audio_file = "Allen_yang_voice.wav"
        text_file = "Allen_yang_voice.txt"
    
    audio_path = os.path.join(data_dir, audio_file)
    audio_text_path = os.path.join(data_dir, text_file)
    with open(audio_text_path, "r") as f:
        audio_text = f.read()
    audio_base64 = encode_base64_content_from_file(audio_path)
    messages_add_to_begining = [
        {"role": "user", "content": audio_text},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_base64,
                        "format": "wav",
                    },
                }
            ],
        }
    ]
    messages = messages_add_to_begining + messages
    audio_bytes_io = io.BytesIO()
    if len(messages) > 3:
        messages = messages[:2] + messages[-1:]
    client = OpenAI(base_url='http://128.32.43.216:8000/v1',api_key='EMPTY')
    models = client.models.list()
    model = models.data[0].id
    chat_completion = client.chat.completions.create(
        messages=messages,
        model=model,
        max_completion_tokens=500,
        stream=stream,
        modalities=["text", "audio"],
        temperature=1.0,
        top_p=0.95,
        extra_body={"top_k": 50},
        stop=["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
    )
    for chunk in chat_completion:
        if chunk.choices and hasattr(chunk.choices[0].delta, "audio") and chunk.choices[0].delta.audio:
            yield chunk.choices[0].delta.audio["data"]

async def tts_parsor(
        stream: AsyncIterator
) -> AsyncIterator[str]:
    """
    Parse the streaming response from the TTS model and yield deltas.
    """
    seq = 0
    async for data in stream:
        yield sse(ResponseDelta(seq=seq, audio_b64=data, audio_spec=AudioSpec())); seq += 1

    yield sse(Done())
    yield "data: [DONE]\n\n"  # Final done message for SSE clients