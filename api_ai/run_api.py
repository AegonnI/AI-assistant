from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from getpass import getpass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


def _http_request_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    payload: Any = None,
    timeout_s: int = 60,
) -> Any:
    data: Optional[bytes] = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = Request(url, data=data, method=method.upper())
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urlopen(req, timeout=timeout_s) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read error body>"
        raise RuntimeError(f"HTTP {e.code} calling {url}. Body: {body[:2000]}") from e


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _normalize_provider(provider: str) -> str:
    p = provider.strip().lower()
    if p in {"groq"}:
        return "groq"
    if p in {"openrouter", "open_router"}:
        return "openrouter"
    if p in {"google", "gemini"}:
        return "google"
    raise ValueError(f"Unknown provider: {provider!r}. Use openrouter/groq/google.")


def list_models_openrouter(api_key: str) -> List[str]:
    url = "https://openrouter.ai/api/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = _http_request_json(url, headers=headers)

    raw_items = data.get("data") or data.get("models") or data.get("result") or []
    models: List[str] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            if "id" in item:
                models.append(str(item["id"]))
            elif "name" in item:
                models.append(str(item["name"]))
            elif "model" in item:
                models.append(str(item["model"]))

    return _dedupe_preserve_order(models)


def list_models_groq(api_key: str) -> List[str]:
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = _http_request_json(url, headers=headers)

    raw_items = data.get("data") or []
    models: List[str] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict) and "id" in item:
                models.append(str(item["id"]))
    return _dedupe_preserve_order(models)


def list_models_google(api_key: str) -> List[str]:
    # Most commonly used: v1beta. If it fails, we fall back to v1.
    for api_version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={quote_plus(api_key)}"
        try:
            data = _http_request_json(url)
        except Exception:
            continue

        raw_items = data.get("models") or []
        models: List[str] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                # Example item.name: "models/gemini-2.5-flash"
                name = item.get("name") or item.get("id") or item.get("model")
                if not name:
                    continue
                name = str(name)
                if name.startswith("models/"):
                    name = name[len("models/") :]
                models.append(name)

        if models:
            return _dedupe_preserve_order(models)

    return []


def get_available_models(
    model_family: str,
    api_key: str,
    model_family_filter: Optional[str] = None,
) -> List[str]:
    """
    Gets models for a given provider ("family" in the original notebook: Groq/google/openrouter).

    If `model_family_filter` is provided, it will be used as a case-insensitive substring
    filter against model identifiers.
    """

    provider = _normalize_provider(model_family)
    if provider == "openrouter":
        models = list_models_openrouter(api_key)
    elif provider == "groq":
        models = list_models_groq(api_key)
    elif provider == "google":
        models = list_models_google(api_key)
    else:
        raise AssertionError("Unreachable")

    if not model_family_filter:
        return models

    needle = model_family_filter.strip().lower()
    if not needle:
        return models
    return [m for m in models if needle in m.lower()]


def run_openrouter(prompt: str, api_key: str, model_name: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional headers that OpenRouter sometimes uses for analytics/routing.
        "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "http://localhost"),
        "X-Title": os.environ.get("OPENROUTER_TITLE", "api_ai"),
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    result = _http_request_json(url, method="POST", headers=headers, payload=payload)

    choices = result.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is not None:
            return str(content)
    return str(result)


def run_groq(prompt: str, api_key: str, model_name: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1024,
        "top_p": 0.95,
    }
    result = _http_request_json(url, method="POST", headers=headers, payload=payload)

    choices = result.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is not None:
            return str(content)
    return str(result)


def run_google(prompt: str, api_key: str, model_name: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote_plus(model_name)}"
        f":generateContent?key={quote_plus(api_key)}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "topP": 0.95, "maxOutputTokens": 1024},
    }
    result = _http_request_json(url, method="POST", headers={"Content-Type": "application/json"}, payload=payload)

    candidates = result.get("candidates") or []
    if candidates and isinstance(candidates, list):
        cand0 = candidates[0] or {}
        content = cand0.get("content") or {}
        parts = content.get("parts") or []
        if parts and isinstance(parts, list) and isinstance(parts[0], dict) and "text" in parts[0]:
            return str(parts[0]["text"])
    return str(result)


def api_request(prompt: str, api_key: str, model_family: str, model_name: str) -> str:
    provider = _normalize_provider(model_family)
    if provider == "groq":
        return run_groq(prompt, api_key, model_name)
    if provider == "google":
        return run_google(prompt, api_key, model_name)
    if provider == "openrouter":
        return run_openrouter(prompt, api_key, model_name)
    raise AssertionError("Unreachable")


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


def extract_coeffs(
    api_key: str,
    model_family: str,
    model_name: str,
    file_path: str,
    coefficients: Sequence[str],
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

