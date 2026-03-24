from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import json
import re

def run_groq(prompt, key, model_name = "qwen/qwen3-32b"):
    from groq import Groq

    client = Groq(api_key=key)

    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.6,
        max_tokens=4096,
        top_p=0.95,
        stream=True,
    )

    content_parts = []
    for chunk in completion:
        if chunk.choices[0].delta.content:
            #print(chunk.choices[0].delta.content, end="")
            content_parts.append(chunk.choices[0].delta.content)

    return "".join(content_parts)

def run_google(prompt, key, model_name = 'gemini-2.5-flash'):
    import google.generativeai as genai

    genai.configure(api_key=key)

    model = genai.GenerativeModel(model_name) 

    print(f"Отправляю запрос к {model.model_name}...\n")

    try:
        response = model.generate_content(prompt)
        print("Ответ модели:")
        return response.text
    except Exception as e:
        print("Произошла ошибка:", e)

def run_openrouter(prompt, key, model_name = "mistralai/mixtral-8x7b-instruct"):
    import requests
    import time

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "fallback-app"
    }

    try:
        data = {
            "model": model_name,
            "messages": [
                {
                    "role": "user", 
                    "content": prompt
                }
                ],
            "temperature": 0.7,
            "max_tokens": 300
        }

        response = requests.post(url, headers=headers, json=data)
        result = response.json()

        if "choices" in result:
            print("✅ Успех")
            return result["choices"][0]["message"]["content"]

        else:
            error_msg = result.get("error", {}).get("message", "Unknown error")
            print(f"❌ Ошибка: {error_msg}")

    except Exception as e:
        print(f"⚠️ Exception: {e}")

def api_request(prompt: str, api_key: str, model_family: str, model_name: str) -> str:
    if model_family == "Groq":
        return run_groq(prompt, api_key, model_name)
    if model_family == "google":
        return run_google(prompt, api_key, model_name)
    if model_family == 'openrouter':
        return run_openrouter(prompt, api_key, model_name)
    
def load_text(file_path: str) -> str:
    ext = file_path.lower().split(".")[-1]

    if ext == "txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    if ext == "json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, ensure_ascii=False, indent=2)

    if ext == "pdf":
        try:
            # Dynamic import so that the module remains importable without optional deps.
            import importlib

            PdfReader = importlib.import_module("pypdf").PdfReader
        except ImportError as e:
            raise RuntimeError(
                "PDF support requires 'pypdf'. Install it with: pip install pypdf"
            ) from e

        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
        return text

    raise ValueError(f"Unsupported file format: {ext!r}")

def split_text(text: str, chunk_size: int) -> List[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

def build_extract_prompt(coefficients: Sequence[str], chunk: str) -> str:
    example = {k: None for k in coefficients}
    example_json = json.dumps(example, ensure_ascii=False)
    coeffs_str = ", ".join(coefficients)

    return f"""
Извлеки коэффициенты: {coeffs_str}

Верни строго JSON ОБЪЕКТ (только JSON, без пояснений):
{example_json}

Запрещено:
- список []
- любой текст кроме JSON

Если значения нет — используй null.

Текст:
{chunk}
""".strip()

def safe_json_load(text: str) -> Dict[str, Any]:
    """
    Tries to parse JSON from a model output string.
    Returns {} if parsing fails.
    """

    if not text:
        return {}

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    # Extract the first JSON object or array-like substring.
    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(1))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

def normalize_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result

    if isinstance(result, list):
        merged: Dict[str, Any] = {}
        for obj in result:
            if isinstance(obj, dict):
                merged.update(obj)
        return merged

    return {}

def extract_from_chunk(
    api_key: str,
    model_family: str,
    model_name: str,
    chunk: str,
    coefficients: Sequence[str],
) -> Dict[str, Any]:
    prompt = build_extract_prompt(coefficients=coefficients, chunk=chunk)
    response_text = api_request(prompt, api_key=api_key, model_family=model_family, model_name=model_name)
    raw = safe_json_load(response_text)
    return normalize_result(raw)

def extract_coeffs(api_key: str,
    model_family: str,
    model_name: str,
    file_path: str,
    coefficients: List[str],
    chunk_size: int = 6000,
) -> Dict[str, Any]:
    text = load_text(file_path)
    chunks = split_text(text, chunk_size)
    final_result: Dict[str, Any] = {k: None for k in coefficients}

    for i, chunk in enumerate(chunks):
        print(f"\n=== chunk {i + 1}/{len(chunks)} ===")
        result = extract_from_chunk(
            api_key=api_key,
            model_family=model_family,
            model_name=model_name,
            chunk=chunk,
            coefficients=coefficients,
        )
        for k in coefficients:
            if k in result and result[k] is not None:
                # Keep the first non-null value we got across chunks.
                if final_result.get(k) is None:
                    final_result[k] = result[k]

    print("\n=== ИТОГ ===")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))
    return final_result