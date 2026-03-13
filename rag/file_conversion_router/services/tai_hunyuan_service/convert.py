from vllm import LLM, SamplingParams
from PIL import Image
from transformers import AutoProcessor


def clean_repeated_substrings(text):
    """Clean repeated substrings in text"""
    n = len(text)
    if n < 8000:
        return text
    for length in range(2, n // 10 + 1):
        candidate = text[-length:]
        count = 0
        i = n - length

        while i >= 0 and text[i:i + length] == candidate:
            count += 1
            i -= length

        if count >= 10:
            return text[:n - length * (count - 1)]

    return text


model_path = "tencent/HunyuanOCR"
llm = LLM(model=model_path, trust_remote_code=True)
processor = AutoProcessor.from_pretrained(model_path)
sampling_params = SamplingParams(temperature=0, max_tokens=16384)

img_path = "/home/bot/bot/yk/YK_final/test_folder/page_17.png"
img = Image.open(img_path)
messages = [
    {"role": "system", "content": ""},
    {"role": "user", "content": [
        {"type": "image", "image": img_path},
        {"type": "text", "text": "检测并识别图片中的文字，将文本坐标格式化输出。"}
    ]}
]
prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = {"prompt": prompt, "multi_modal_data": {"image": [img]}}
output = llm.generate([inputs], sampling_params)[0]
print(clean_repeated_substrings(output.outputs[0].text))
