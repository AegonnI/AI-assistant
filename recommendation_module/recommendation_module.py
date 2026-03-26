import requests
import json

def get_recommendation(model_name, prompt, system_prompt="Ты профессиональный ИТ-консультант.", temperature = 0.3):
    """
    Основной метод для получения ответа от локальной Ollama.
    """
    url = "http://localhost:11434/api/generate"
    
    # 1. Проверяем наличие модели в системе
    try:
        tags_response = requests.get("http://localhost:11434/api/tags")
        tags_response.raise_for_status()
        available_models = [m['name'] for m in tags_response.json().get('models', [])]
        
        # Проверяем точное совпадение или наличие тега :latest
        if model_name not in available_models and f"{model_name}:latest" not in available_models:
            return f"Ошибка: Модель '{model_name}' не найдена в Ollama. Сначала сделайте 'ollama pull {model_name}'"
            
    except requests.exceptions.ConnectionError:
        return "Ошибка: Ollama не запущена. Запустите приложение Ollama или сервис."

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
