# AI Assistant (financial document analyzer)

Streamlit-приложение для анализа финансовых PDF-документов:

- извлечение текста и таблиц из PDF,
- извлечение финансовых показателей (локальный пайплайн или через LLM API),
- расчёт метрик и статусов (ok / warn / risk),
- генерация рекомендаций через Ollama,
- формирование PDF-отчёта для скачивания.

---

## Как это работает (сквозной сценарий)

1. Загрузка PDF
   - В боковой панели  загружаете один или несколько PDF.
   - Первым файлом из списка считается основной .

2. Формирование артефактов парсинга
   - Файл сохраняется во временный каталог:
     - `<TEMP>/ai_assistant_streamlit/input/` (файл)
     - `output/` (текст и JSON)
   - `extract_pdf_simple` из `pdf_parser_module/pdf_to_text_extractor_main.py` обрабатывает PDF.
   - Результат содержит `plain_text`, `structured` и метаданные.

3. Запуск модулей (через чекбоксы в боковой панели)

### Коэффициенты и метрики

- Локальный пайплайн:
  - `financial_pipeline/financial_pipeline.py` + `financial_pipeline/financial_parser.py`.
  - `parse_pdf_lines` ищет ключевые фразы по `KEYWORD_MAP` (выручка, чистая прибыль, активы и др.).
  - `run_pipeline_on_uploaded_pdf` считает метрики (`compute_metrics`) и преобразует в `coefficients` + `metrics_detailed`.
  - `parse_meta` фиксирует стратегию обработки:
    - `structured` (из JSON `pages / structured`),
    - `plain` (из `plain_text`),
    - `direct` (через `parse_financial_pdf` по bytes).

- Через API:
  - `api_ai/ModelProvider.py` (функция `extract_coeffs`).
  - Отправляет JSON-артефакт / текст в провайдера и получает строго JSON с ключами.
  - Берёт первое ненулевое значение по каждому ключу среди чанков.

### Рекомендации

- `recommendation_module/recommendation_module.py`.
- Формирует prompt на основе метрик, коэффициентов и предупреждений.
- Отправляет запрос на Ollama (`http://localhost:11434`).
- Ответ сохраняется в `st.session_state.recommendations`.

### Отчёт

- `report_pdf.py` генерирует PDF через reportlab.
- В отчёт включаются:
  - `metrics_detailed`,
  - `warnings`,
  - `recommendations` (опционально),
  - метаданные и заголовок.
- Кнопка для скачивания: `report_YYYYMMDD_HHMMSS.pdf`.

---

## Основные возможности

- PDF → текст:
  - `pdf_to_text_extractor_main.py` (Surya OCR / PyMuPDF / pdfplumber),
  - `extract_lines_from_pdf` из pdfplumber для резерва.
- Метрики:
  - `financial_pipeline/coefficients_module.py` (ros, roa, roe, liquidity, leverage, dso, capex/revenue и др.).
  - Статусы `ok`, `warn`, `risk`.
- Отчёт: PDF с таблицей метрик и рекомендациями.

---

## Установка и запуск

```bash
pip install -r requirements_finance_modules.txt
#Также рекомндуется использовать пайторч именно с кудой
# при необходимости:
# pip install -r api_ai\requirements.txt
```

Запуск:

```bash
streamlit run app.py
```

---

## Требования Ollama

- Ollama должен быть запущен.
- Модель должна быть доступна в Ollama.
- По умолчанию адрес: `http://localhost:11434`.

---

## Структура проекта

- `app.py` — Streamlit UI + логика модуля.
- `pdf_parser_module/pdf_to_text_extractor_main.py` — извлечение текста, structured output + совместимость с `app.py`.
- `financial_pipeline/financial_parser.py` — парсинг чисел + годовые колонки.
- `financial_pipeline/financial_pipeline.py` — подсчет метрик и pipeline.
- `financial_pipeline/financial_transform.py` — нормализация и предупреждения.
- `financial_pipeline/coefficients_module.py` — формулы, статус метрик.
- `api_ai/ModelProvider.py` — API-режим для извлечения коэффициентов.
- `recommendation_module/recommendation_module.py` — Ollama-рекомендации.
- `report_pdf.py` — генерация PDF-отчёта.

---

## Временные артефакты

- `<TEMP>/ai_assistant_streamlit/input/` — входные файлы.
- `<TEMP>/ai_assistant_streamlit/output/` — артефакты парсинга (txt, json).
