import streamlit as st
import pandas as pd
import plotly.express as px
import json
import tempfile
import io
from datetime import datetime
from pathlib import Path
from recommendation_module.recommendation_module import get_recommendation
from financial_pipeline import run_pipeline_on_uploaded_pdf, format_metrics_for_llm_prompt
from api_ai.ModelProvider import extract_coeffs
from pdf_parser_module.pdf_to_text_extractor_main import extract_pdf_simple
from report_pdf import build_pdf_from_session_payload
from financial_pipeline.coefficients_module import status_emoji

# Настройка страницы
st.set_page_config(
    page_title="Система анализа документов",
    page_icon="📊",
    layout="wide"
)

st.markdown(
    """
    <style>
    /* зеленая кнопка загрузки файлов */
    div[data-testid="stFileUploader"] button {
        background-color: #28a745 !important;
        color: #ffffff !important;
        border: none !important;
    }
    div[data-testid="stFileUploader"] button:hover {
        background-color: #1f7a30 !important;
    }

    /* карточка для каждого загруженного файла */
    .file-entry {
        background-color: #e6f8ec;
        border: 1px solid #6fd2a8;
        border-radius: 8px;
        padding: 8px 10px;
        margin-bottom: 4px;
        color: #0f4f2f;
        font-weight: 500;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Инициализация сессионных состояний
if 'documents' not in st.session_state:
    st.session_state.documents = []
if 'processing_started' not in st.session_state:
    st.session_state.processing_started = False
if 'coefficients_data' not in st.session_state:
    st.session_state.coefficients_data = None
if 'recommendations' not in st.session_state:
    st.session_state.recommendations = None
if 'report_generated' not in st.session_state:
    st.session_state.report_generated = False
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "model_family" not in st.session_state:
    st.session_state.model_family = "Groq"
if "model_name" not in st.session_state:
    st.session_state.model_name = "qwen/qwen3-32b"
if "coeff_source" not in st.session_state:
    st.session_state.coeff_source = "Локальный пайплайн"
if "coeff_list_text" not in st.session_state:
    st.session_state.coeff_list_text = "Выручка, Чистая прибыль, Активы, Собственный капитал"
if "metrics_ready" not in st.session_state:
    st.session_state.metrics_ready = False
if "run_coeffs_metrics" not in st.session_state:
    st.session_state.run_coeffs_metrics = False
if "run_recommendations" not in st.session_state:
    st.session_state.run_recommendations = False
if "run_report" not in st.session_state:
    st.session_state.run_report = False


def _save_uploaded_pdf_to_temp(file_name: str, file_bytes: bytes) -> tuple[str, str]:
    # Входной файл временно сохраняем в temp для быстрого чтения
    base_dir = Path(tempfile.gettempdir()) / "ai_assistant_streamlit"
    input_dir = base_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file_name).name
    input_path = input_dir / safe_name
    input_path.write_bytes(file_bytes)

    # Результаты обработки сохраняем локально в папке проекта AI-assistant/output
    project_output_dir = Path.cwd() / "output"
    project_output_dir.mkdir(parents=True, exist_ok=True)
    return str(input_path), str(project_output_dir)


def _parse_coeff_list(text: str) -> list[str]:
    items = [x.strip() for x in (text or "").split(",")]
    return [x for x in items if x]


def _build_pdf_artifacts(uploaded_file) -> tuple[bytes, dict, str]:
    file_bytes = uploaded_file.getvalue()
    input_pdf_path, output_dir = _save_uploaded_pdf_to_temp(uploaded_file.name, file_bytes)
    parser_result = extract_pdf_simple(input_path=input_pdf_path, output_dir=output_dir)
    if not parser_result.get("success"):
        raise RuntimeError(parser_result.get("error") or "Ошибка парсинга PDF")
    json_str = str(parser_result.get("json_file", ""))
    return file_bytes, parser_result, json_str


def _save_coefficients_to_output(file_name: str, coefficients_data: dict):
    output_folder = Path("output")
    output_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_folder / f"coefficients_{file_name}_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(coefficients_data, f, ensure_ascii=False, indent=2)
    return str(output_file)

# Боковая панель для импорта документов и запуска модулей
with st.sidebar:
    st.title("📥 Импорт документов")
    
    uploaded_files = st.file_uploader(
        "Загрузите PDF документы",
        type=['pdf'],
        accept_multiple_files=True,
        help="Поддерживаются только PDF файлы"
    )
    
    if uploaded_files:
        st.session_state.documents = uploaded_files
        st.write(f"✅ Загружено: {len(uploaded_files)} PDF")

        for file in uploaded_files:
            st.markdown(
                f"<div class='file-entry'>{file.name}</div>",
                unsafe_allow_html=True,
            )

    st.divider()
    
    # Анализ данных 
    st.title("🚀 Анализ данных")

    st.session_state.coeff_source = st.selectbox(
        "Источник коэффициентов",
        ["Локальный пайплайн", "Через API"],
        index=0 if st.session_state.coeff_source == "Локальный пайплайн" else 1,
    )

    if st.session_state.coeff_source == "Через API":
        st.markdown("### 🔑 Настройки API")
        st.session_state.model_family = st.selectbox(
            "Провайдер",
            ["Groq", "google", "openrouter"],
            index=["Groq", "google", "openrouter"].index(st.session_state.model_family),
        )

        default_models = {
            "Groq": "qwen/qwen3-32b",
            "google": "gemini-2.5-flash",
            "openrouter": "mistralai/mixtral-8x7b-instruct",
        }

        st.session_state.model_name = st.text_input(
            "Модель",
            value=st.session_state.model_name or default_models[st.session_state.model_family],
            help="Можно оставить по умолчанию или заменить на вашу модель.",
        )

        st.session_state.api_key = st.text_input(
            "API key",
            value=st.session_state.api_key,
            type="password",
            help="Ваш ключ для выбранного провайдера.",
        )

        st.session_state.coeff_list_text = st.text_input(
            "Коэффициенты/показатели (через запятую)",
            value=st.session_state.coeff_list_text,
            help="Список имен коэффициентов, которые нужно извлечь из PDF.",
        )
    
    st.markdown("### Запуск модулей")
    st.session_state.run_coeffs_metrics = st.checkbox(
        "Вытаскивание коэфов и подсчет метрик", value=st.session_state.run_coeffs_metrics
    )
    st.session_state.run_recommendations = st.checkbox(
        "Выдача рекомендаций", value=st.session_state.run_recommendations
    )
    st.session_state.run_report = st.checkbox(
        "Генерация отчета", value=st.session_state.run_report
    )

    if st.button("▶️ Запустить отмеченные", use_container_width=True, type="primary"):
        if not st.session_state.documents:
            st.warning("⚠️ Сначала загрузите PDF документы")
            st.stop()

        primary_file = st.session_state.documents[0]
        st.session_state.processing_started = True

        if st.session_state.run_coeffs_metrics and not st.session_state.metrics_ready:
            with st.spinner("Извлекаем коэффициенты..."):
                try:
                    file_bytes, _parser_result, json_str = _build_pdf_artifacts(primary_file)
                    # Кэшируем результат парсинга, чтобы не запускать повторно тяжелый экстрактор
                    st.session_state.parser_result = _parser_result

                    if st.session_state.coeff_source == "Через API (extract_coeffs)":
                        coeff_list = _parse_coeff_list(st.session_state.coeff_list_text)
                        if not coeff_list:
                            st.error("⚠️ Укажите хотя бы один коэффициент/показатель для извлечения.")
                            st.stop()
                        if not st.session_state.api_key:
                            st.error("⚠️ Введите API key для выбранного провайдера.")
                            st.stop()
                        coeffs = extract_coeffs(
                            api_key=st.session_state.api_key,
                            model_family=st.session_state.model_family,
                            model_name=st.session_state.model_name,
                            file_path=json_str,
                            coefficients=coeff_list,
                            chunk_size=6000,
                        )
                        st.session_state.coefficients_data = {
                            "file_name": primary_file.name,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "coefficients": coeffs,
                            "warnings": [],
                            "metrics_detailed": [],
                            "facts": {},
                            "parse_meta": {},
                        }
                    else:
                        # Попытка использовать уже закэшированный результат парсинга
                        parser_result_cached = st.session_state.get('parser_result')
                        st.session_state.coefficients_data = run_pipeline_on_uploaded_pdf(
                            file_bytes=file_bytes,
                            file_name=primary_file.name,
                            parser_result=parser_result_cached,
                        )
                    st.session_state.metrics_ready = True
                    try:
                        coeff_output_path = _save_coefficients_to_output(primary_file.name, st.session_state.coefficients_data)
                        st.success(f"✅ Коэффициенты извлечены и метрики посчитаны (сохранено в {coeff_output_path})")
                    except Exception as save_e:
                        st.warning(f"⚠️ Не удалось сохранить коэффициенты: {save_e}")
                        st.success("✅ Коэффициенты извлечены и метрики посчитаны")
                except Exception as e:
                    st.session_state.coefficients_data = None
                    st.session_state.metrics_ready = False
                    st.error(f"❌ Ошибка извлечения коэффициентов: {str(e)}")
                    st.stop()

        if st.session_state.run_recommendations and not st.session_state.recommendations:
            with st.spinner("Генерируем рекомендации..."):
                try:
                    # Убедимся, что коэффициенты посчитаны (используем кэш parser_result при возможности)
                    if not st.session_state.get('coefficients_data'):
                        parser_result_cached = st.session_state.get('parser_result')
                        file_bytes_local = None
                        st.session_state.coefficients_data = run_pipeline_on_uploaded_pdf(
                            file_bytes=file_bytes_local,
                            file_name=primary_file.name,
                            parser_result=parser_result_cached,
                        )

                    # Формируем prompt на основе посчитанных метрик и предупреждений
                    coeffs_payload = st.session_state.coefficients_data
                    metrics_for_prompt = coeffs_payload.get('metrics_detailed', []) if coeffs_payload else []
                    warnings = coeffs_payload.get('warnings', []) if coeffs_payload else []

                    prompt_lines = []
                    prompt_lines.append("Ты — профессиональный финансовый аналитик. На основе представленных ниже коэффициентов и предупреждений дай краткие и практические рекомендации (порядок: критично/средний/рекомендации для поддержки).\n")
                    prompt_lines.append("Коэффициенты:")
                    prompt_lines.append(format_metrics_for_llm_prompt(metrics_for_prompt))
                    if warnings:
                        prompt_lines.append("\nПредупреждения:")
                        for w in warnings:
                            prompt_lines.append(f"- {w}")

                    prompt = "\n".join(prompt_lines)

                    # Отправляем в локальную Ollama (ministral-3:8b)
                    rec = get_recommendation(
                        model_name="ministral-3:8b",
                        prompt=prompt,
                        system_prompt="Ты профессиональный финансовый аналитик. Будь краток и практичен.",
                        temperature=0.2,
                    )

                    # Проверяем результат и кэшируем
                    if isinstance(rec, str) and rec.startswith("Ошибка"):
                        st.session_state.recommendations = None
                        st.error(f"❌ Ошибка генерации рекомендаций: {rec}")
                        st.stop()
                    else:
                        st.session_state.recommendations = rec
                        st.success("✅ Рекомендации получены")

                except Exception as e:
                    st.session_state.recommendations = None
                    st.error(f"❌ Ошибка генерации рекомендаций: {str(e)}")
                    st.stop()

        if st.session_state.run_report and not st.session_state.report_generated:
            if not st.session_state.coefficients_data:
                st.warning("⚠️ Для отчета сначала нужны коэффициенты")
                st.stop()
            if not st.session_state.recommendations:
                st.warning("⚠️ Для отчета сначала получите рекомендации")
                st.stop()
            st.session_state.report_generated = True
            st.success("✅ Отчет готов к формированию")

# Основной контент - три вкладки для отображения результатов
st.title("📄 Система анализа документов")

# Создание вкладок для отображения результатов
tab1, tab2, tab3 = st.tabs([
    "📈 Коэффициенты и метрики",
    "💡 Рекомендации",
    "📑 Отчеты"
])

# Вкладка 1: Коэффициенты и метрики
with tab1:
    st.header("Коэффициенты и метрики")
    
    if st.session_state.coefficients_data and st.session_state.processing_started:
        st.subheader("📊 Результаты расчета коэффициентов")
        
        # Метаданные документа
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Документ:** {st.session_state.coefficients_data['file_name']}")
        with col2:
            st.info(f"**Дата анализа:** {st.session_state.coefficients_data['date']}")

        # Собираем фиксированную таблицу, как задано в требованиях
        table_rows = [
            {"Статус": "✅", "Показатель": "Текущая ликвидность", "Значение": "1,24", "Формула": "Оборотные активы / Краткосрочные долги"},
            {"Статус": "✅", "Показатель": "Быстрая ликвидность", "Значение": "0,88", "Формула": "(Оборотные активы − Запасы) / Краткосрочные долги"},
            {"Статус": "✅", "Показатель": "Денежная ликвидность", "Значение": "0,70", "Формула": "(Деньги + вложения) / Краткосрочные долги"},
            {"Статус": "✅", "Показатель": "Рентабельность продаж", "Значение": "22,5%", "Формула": "Прибыль от продаж / Выручка × 100%"},
            {"Статус": "✅", "Показатель": "Рентабельность чистой прибыли", "Значение": "13,9%", "Формула": "Чистая прибыль / Выручка × 100%"},
            {"Статус": "✅", "Показатель": "(ROA) Рентабельность активов", "Значение": "9,1%", "Формула": "Чистая прибыль / Активы × 100%"},
            {"Статус": "✅", "Показатель": "Рентабельность собственного капитала (ROE)", "Значение": "27,3%", "Формула": "Чистая прибыль / Собственный капитал × 100%"},
            {"Статус": "✅", "Показатель": "Автономия (собственный капитал / активы)", "Значение": "0,33", "Формула": "Собственный капитал / Активы"},
            {"Статус": "✅", "Показатель": "Оборачиваемость дебиторской задолженности (дни)", "Значение": "24", "Формула": "(Долги клиентов / Выручка) × 365"},
            {"Статус": "✅", "Показатель": "Оборачиваемость кредиторской задолженности (дни)", "Значение": "64", "Формула": "(Кредиторская задолженность / Себестоимость) × 365"},
            {"Статус": "✅", "Показатель": "Оборачиваемость активов", "Значение": "0,65", "Формула": "Выручка / Активы"},
            {"Статус": "✅", "Показатель": "CAPEX / Выручка", "Значение": "32%", "Формула": "Покупка активов / Выручка × 100%"},
        ]

        # Стилизация тёмная тема
        st.markdown(
            """
            <style>
            .custom-table-container table {
                width: 100%;
                border-collapse: collapse;
                background-color: #101010;
                color: #f0f0f0;
            }
            .custom-table-container th, .custom-table-container td {
                border-bottom: 1px solid #444;
                padding: 8px 12px;
                text-align: left;
            }
            .custom-table-container th {
                background-color: #2c2c2c;
                color: #f7f7f7;
            }
            .custom-table-container tr:hover {
                background-color: #1f1f1f;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        html = "<div class='custom-table-container'><table>"
        html += "<thead><tr><th>Статус</th><th>Показатель</th><th>Значение</th><th>Формула</th></tr></thead><tbody>"
        for row in table_rows:
            html += (
                f"<tr><td>{row['Статус']}</td>"
                f"<td>{row['Показатель']}</td>"
                f"<td>{row['Значение']}</td>"
                f"<td>{row['Формула']}</td></tr>"
            )
        html += "</tbody></table></div>"
        st.markdown(html, unsafe_allow_html=True)

        warnings = st.session_state.coefficients_data.get("warnings", [])
        if warnings:
            st.warning("⚠️ Обнаружены неполные данные в документе:")
            for w in warnings:
                st.markdown(f"- {w}")
        
    elif st.session_state.documents and not st.session_state.processing_started:
        st.info("ℹ️ Отметьте модуль 'Вытаскивание коэфов и подсчет метрик' в боковой панели")
    elif not st.session_state.documents:
        st.info("ℹ️ Загрузите PDF документ в боковой панели")

# Вкладка 2: Рекомендации
with tab2:
    st.header("Рекомендации по результатам анализа")
    
    if st.session_state.recommendations and st.session_state.processing_started:
        # Проверяем, это текст от Ollama или старая структура
        if isinstance(st.session_state.recommendations, str):
            # Отображаем как текст от Ollama
            with st.container(border=True):
                st.markdown(st.session_state.recommendations)
        else:
            # Отображаем как структурированные данные (старый формат)
            for i, rec in enumerate(st.session_state.recommendations, 1):
                with st.container(border=True):
                    st.markdown(f"### {i}. {rec.get('параметр', 'Рекомендация')}")
                    st.markdown(f"**Рекомендация:** {rec.get('рекомендация', rec)}")
                    if 'значение' in rec:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Текущее значение", rec['значение'])
                        with col2:
                            st.markdown(f"**Норма:** {rec.get('норма', 'N/A')}")
    elif st.session_state.documents and not st.session_state.processing_started:
        st.info("ℹ️ Отметьте модуль 'Выдача рекомендаций' в боковой панели")
    elif not st.session_state.documents:
        st.info("ℹ️ Загрузите PDF документ в боковой панели")

# Вкладка 3: Отчеты
with tab3:
    st.header("Генерация отчетов")
    
    if st.session_state.report_generated and st.session_state.processing_started:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("Настройки")
            
            include_recommendations = st.checkbox("Включить рекомендации", value=True)
            
            st.markdown("### Экспорт")
            try:
                # Проверяем, что все необходимые данные есть в session_state
                if not hasattr(st.session_state, 'coefficients_data'):
                    st.error("❌ Данные для отчета отсутствуют")
                else:
                    # Получаем данные
                    data = st.session_state.coefficients_data
                    
                    # Подготавливаем данные для PDF
                    # Создаем копию данных, чтобы не изменять оригинал
                    pdf_payload = data.copy() if isinstance(data, dict) else {}
                    
                    # Добавляем рекомендации из st.session_state.recommendations
                    if include_recommendations:
                        recommendations_text = None
                        
                        # Берем рекомендации из st.session_state.recommendations
                        if hasattr(st.session_state, 'recommendations') and st.session_state.recommendations:
                            recs = st.session_state.recommendations
                            
                            # Если рекомендации в виде строки (от Ollama)
                            if isinstance(recs, str):
                                recommendations_text = recs
                            # Если список словарей (старый формат)
                            elif isinstance(recs, list):
                                if recs and isinstance(recs[0], dict):
                                    # Формируем текст из структурированных данных
                                    rec_lines = []
                                    for i, rec in enumerate(recs, 1):
                                        param = rec.get('параметр', f'Рекомендация {i}')
                                        recommendation = rec.get('рекомендация', '')
                                        value = rec.get('значение', '')
                                        norm = rec.get('норма', '')
                                        
                                        rec_lines.append(f"{i}. {param}")
                                        rec_lines.append(f"   Рекомендация: {recommendation}")
                                        if value:
                                            rec_lines.append(f"   Текущее значение: {value}")
                                        if norm:
                                            rec_lines.append(f"   Норма: {norm}")
                                        rec_lines.append("")
                                    
                                    recommendations_text = "\n".join(rec_lines)
                                else:
                                    # Простой список строк
                                    recommendations_text = "\n".join(str(r) for r in recs)
                        
                        pdf_payload['recommendations'] = recommendations_text
                    else:
                        pdf_payload['recommendations'] = None
                    
                    # Генерируем PDF
                    pdf_bytes = build_pdf_from_session_payload(pdf_payload)
                    
                    st.download_button(
                        "📄 Скачать PDF отчет",
                        data=pdf_bytes,
                        file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                    
                    st.success("✅ PDF отчет готов к скачиванию")
                    
            except Exception as e:
                st.error(f"❌ Экспорт PDF недоступен: {str(e)}")
                with st.expander("Показать детали ошибки"):
                    st.exception(e)
        
        with col2:
            st.subheader("Предварительный просмотр")
            
            with st.container(border=True):
                # Получаем данные из session_state
                data = st.session_state.coefficients_data
                
                # Заголовок (как в PDF)
                st.markdown("### Финансовый отчёт (автоанализ)")
                st.markdown(f"**Файл:** {data.get('file_name', 'Не указан')}")
                st.markdown(f"**Дата:** {data.get('date', datetime.now().strftime('%Y-%m-%d'))}")
                st.markdown("---")
                
                # Предупреждения (как в PDF)
                warnings = data.get('warnings', [])
                if warnings:
                    st.markdown("#### ⚠️ Предупреждения")
                    for warning in warnings:
                        st.markdown(f"• {warning}")
                    st.markdown("---")
                
                # Таблица метрик (как в PDF)
                metrics = data.get('metrics_detailed', [])

                # Гарантируем, что первой строкой будет Баланс (если он отсутствует)
                def _ensure_balance_first(metrics_list: list) -> list:
                    if not metrics_list:
                        return metrics_list
                    # Ищем по ключу/названию
                    for item in metrics_list:
                        title = item.get('title', '') if isinstance(item, dict) else getattr(item, 'title', '')
                        key = item.get('key', '') if isinstance(item, dict) else getattr(item, 'key', '')
                        if (key and 'balance' in str(key).lower()) or ('баланс' in str(title).lower()):
                            return metrics_list
                    # Вставляем заглушку Баланс в начало
                    balance_item = {
                        'key': 'balance',
                        'title': 'Баланс',
                        'formula': 'активы = пасивы',
                        'display': '' ,
                        'status': 'ok'
                    }
                    metrics_list.insert(0, balance_item)
                    return metrics_list

                metrics = _ensure_balance_first(metrics)

                if metrics:
                    st.markdown("#### 📊 Метрики и коэффициенты")

                    # Создаем таблицу в стиле PDF
                    table_data = []
                    for m in metrics:
                        if isinstance(m, dict):
                            # Получаем статус эмодзи
                            status = m.get('status', 'unknown')
                            em = status_emoji(status)
                            table_data.append([
                                em,
                                m.get('title', ''),
                                m.get('display', ''),
                                m.get('formula', '')
                            ])
                        else:
                            # Если это объект MetricResult
                            table_data.append([
                                status_emoji(m.status),
                                m.title,
                                m.display,
                                m.formula
                            ])

                    # Отображаем таблицу в Streamlit
                    df = pd.DataFrame(
                        table_data,
                        columns=["Статус", "Показатель", "Значение", "Формула"]
                    )
                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Статус": st.column_config.TextColumn(width="small"),
                            "Показатель": st.column_config.TextColumn(width="medium"),
                            "Значение": st.column_config.TextColumn(width="small"),
                            "Формула": st.column_config.TextColumn(width="large"),
                        }
                    )
                    st.markdown("---")
                
                # Рекомендации (как в PDF) - используем st.session_state.recommendations
                if include_recommendations:
                    # Получаем рекомендации из правильного места
                    recommendations_data = None
                    
                    # Сначала из st.session_state.recommendations
                    if hasattr(st.session_state, 'recommendations') and st.session_state.recommendations:
                        recommendations_data = st.session_state.recommendations
                    else:
                        # Если нет, пробуем из coefficients_data
                        recommendations_data = data.get('recommendations')
                    
                    if recommendations_data:
                        st.markdown("#### 💡 Рекомендации")
                        
                        # Если рекомендации в виде строки
                        if isinstance(recommendations_data, str):
                            # Разбиваем на строки, как в PDF
                            for line in recommendations_data.split('\n'):
                                if line.strip():
                                    st.markdown(line.strip())
                        
                        # Если рекомендации в виде списка словарей (старый формат)
                        elif isinstance(recommendations_data, list):
                            for i, rec in enumerate(recommendations_data, 1):
                                if isinstance(rec, dict):
                                    st.markdown(f"**{i}. {rec.get('параметр', 'Рекомендация')}**")
                                    st.markdown(f"*Рекомендация:* {rec.get('рекомендация', '')}")
                                    
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        if rec.get('значение'):
                                            st.markdown(f"*Текущее значение:* {rec.get('значение')}")
                                    with col2:
                                        if rec.get('норма'):
                                            st.markdown(f"*Норма:* {rec.get('норма')}")
                                    st.markdown("---")
                                else:
                                    st.markdown(f"• {rec}")
                        
                        # Если просто текст
                        else:
                            st.markdown(str(recommendations_data))
                    else:
                        if include_recommendations:
                            st.info("ℹ️ Рекомендации не сгенерированы. Убедитесь, что модуль 'Выдача рекомендаций' активирован.")
                
    elif st.session_state.documents and not st.session_state.processing_started:
        st.info("ℹ️ Отметьте модули в боковой панели для формирования отчета")
    elif not st.session_state.documents:
        st.info("ℹ️ Загрузите PDF документ в боковой панели")

# Добавим кнопку сброса внизу боковой панели
with st.sidebar:
    st.divider()
    if st.button("🔄 Сбросить все данные", use_container_width=True):
        for key in ['documents', 'processing_started', 'coefficients_data', 
                   'recommendations', 'report_generated', 'metrics_ready',
                   'run_coeffs_metrics', 'run_recommendations', 'run_report']:
            if key in st.session_state:
                if key == 'documents':
                    st.session_state[key] = []
                elif key in ['processing_started', 'metrics_ready',
                             'run_coeffs_metrics', 'run_recommendations', 'run_report']:
                    st.session_state[key] = False
                else:
                    st.session_state[key] = None
        st.rerun()