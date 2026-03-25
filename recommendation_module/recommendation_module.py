import requests
import json
from typing import List


def get_available_ollama_models(
    base_url: str = "http://localhost:11434",
    timeout_s: float = 5.0,
) -> List[str]:
    """
    Returns list of available Ollama model names from `/api/tags`.
    Raises RuntimeError if Ollama is not reachable.
    """
    url = f"{base_url}/api/tags"
    try:
        tags_response = requests.get(url, timeout=timeout_s)
        tags_response.raise_for_status()
        payload = tags_response.json()
        models = []
        for m in payload.get("models", []) or []:
            name = m.get("name") if isinstance(m, dict) else None
            if name:
                models.append(name)
        # Make stable + unique ordering
        return sorted(set(models))
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError("Ошибка: Ollama не запущена. Запустите Ollama по адресу http://localhost:11434.") from e
    except Exception as e:
        raise RuntimeError(f"Ошибка при получении списка моделей Ollama: {str(e)}") from e

def get_recommendation(model_name, prompt, system_prompt="Ты профессиональный ИТ-консультант.", temperature = 0.3):
    """
    Основной метод для получения ответа от локальной Ollama.
    """
    url = "http://localhost:11434/api/generate"
    
    # 1. Проверяем наличие модели в системе
    try:
        available_models = get_available_ollama_models()
        
        # Проверяем точное совпадение или наличие тега :latest
        if model_name not in available_models and f"{model_name}:latest" not in available_models:
            return f"Ошибка: Модель '{model_name}' не найдена в Ollama. Сначала сделайте 'ollama pull {model_name}'"
            
    except RuntimeError as e:
        return str(e)

    # 2. Формируем запрос
    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,  # Отключаем потоковую передачу для простоты MVP
        "options": {
            "temperature": temperature 
        }
    }

    # 3. Отправляем и возвращаем результат
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json().get('response', "Ошибка: Пустой ответ от модели.")
    except Exception as e:
        return f"Ошибка при запросе к модели: {str(e)}"
