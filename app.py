import streamlit as st
import pandas as pd
import plotly.express as px
import tempfile
import io
from datetime import datetime
from pathlib import Path
from recommendation_module.recommendation_module import get_recommendation, get_available_ollama_models
from financial_pipeline import run_pipeline_on_uploaded_pdf
from api_ai.ModelProvider import extract_coeffs
from pdf_parser_module.main_pdf_parser1 import extract_pdf_simple
from report_pdf import build_pdf_from_session_payload
from financial_pipeline.coefficients_module import status_emoji

# Настройка страницы
st.set_page_config(
    page_title="Система анализа документов",
    page_icon="📊",
    layout="wide"
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
if "recommendations_model_name" not in st.session_state:
    st.session_state.recommendations_model_name = "ministral-3:8b"
if "ollama_models" not in st.session_state:
    st.session_state.ollama_models = []
if "ollama_models_loaded" not in st.session_state:
    st.session_state.ollama_models_loaded = False


def _save_uploaded_pdf_to_temp(file_name: str, file_bytes: bytes) -> tuple[str, str]:
    base_dir = Path(tempfile.gettempdir()) / "ai_assistant_streamlit"
    input_dir = base_dir / "input"
    output_dir = base_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file_name).name
    input_path = input_dir / safe_name
    input_path.write_bytes(file_bytes)
    return str(input_path), str(output_dir)


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
        st.success(f"✅ Загружено: {len(uploaded_files)} PDF")
        
        # Отображение загруженных файлов
        files_data = []
        for file in uploaded_files:
            files_data.append({
                "Имя файла": file.name,
                "Размер (КБ)": round(file.size / 1024, 2)
            })
        
        df_files = pd.DataFrame(files_data)
        st.dataframe(df_files, use_container_width=True)
    
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

    # Настройки модели для генерации рекомендаций (Ollama)
    st.divider()
    st.markdown("### 💡 Настройки модели для рекомендаций (Ollama)")

    # Автопопытка загрузить список моделей при первом запуске
    if not st.session_state.ollama_models_loaded:
        try:
            st.session_state.ollama_models = get_available_ollama_models()
        except Exception:
            st.session_state.ollama_models = []
        finally:
            st.session_state.ollama_models_loaded = True

    if st.button("🔄 Поиск доступных моделей Ollama", use_container_width=True):
        with st.spinner("Получаем список моделей из Ollama..."):
            try:
                st.session_state.ollama_models = get_available_ollama_models()
                st.success(f"✅ Найдено моделей: {len(st.session_state.ollama_models)}")
            except Exception as e:
                st.session_state.ollama_models = []
                st.warning(str(e))

    if st.session_state.ollama_models:
        desired = st.session_state.recommendations_model_name
        initial_index = st.session_state.ollama_models.index(desired) if desired in st.session_state.ollama_models else 0
        st.session_state.recommendations_model_name = st.selectbox(
            "Модель Ollama",
            st.session_state.ollama_models,
            index=initial_index,
        )
    else:
        st.session_state.recommendations_model_name = st.text_input(
            "Модель Ollama (введите вручную, если список не загрузился)",
            value=st.session_state.recommendations_model_name,
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

                    if st.session_state.coeff_source == "Через API":
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
                    st.success("✅ Коэффициенты извлечены и метрики посчитаны")
                except Exception as e:
                    st.session_state.coefficients_data = None
                    st.session_state.metrics_ready = False
                    st.error(f"❌ Ошибка извлечения коэффициентов: {str(e)}")
                    st.stop()

        if st.session_state.run_recommendations and not st.session_state.recommendations:
            with st.spinner("Генерируем рекомендации..."):
                try:
                    # Пытаемся использовать уже закэшированный parser_result
                    parser_result = st.session_state.get('parser_result')
                    if not parser_result:
                        _file_bytes, parser_result, _json_str = _build_pdf_artifacts(primary_file)
                        st.session_state.parser_result = parser_result

                    st.session_state.recommendations = get_recommendation(
                        model_name=st.session_state.recommendations_model_name,
                        prompt=parser_result.get("text", ""),
                        system_prompt="Ты профессиональный финансовый аналитик. Дай краткие и практические рекомендации по улучшению финансового состояния компании на основе данных из документа.",
                        temperature=0.3,
                    )
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
        
        # Таблица с коэффициентами
        coeff_data = []
        for name, value in st.session_state.coefficients_data['coefficients'].items():
            coeff_data.append({
                "Коэффициент": name,
                "Значение": value,
                "Единица измерения": "отн. ед."
            })
        
        df_coeff = pd.DataFrame(coeff_data)
        st.dataframe(df_coeff, use_container_width=True)

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