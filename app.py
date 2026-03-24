import streamlit as st
import pandas as pd
import plotly.express as px
import tempfile
from datetime import datetime
# Добавьте эту строку в начало файла, где остальные импорты
from recommendation_module.recommendation_module import get_recommendation
from financial_pipeline import run_pipeline_on_uploaded_pdf, format_metrics_for_llm_prompt
from financial_pipeline.financial_parser import extract_lines_from_pdf
from api_ai.ModelProvider import extract_coeffs

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


def _pdf_bytes_to_text(file_bytes: bytes) -> str:
    # Берем текст построчно и склеиваем обратно — для промпта LLM
    lines = extract_lines_from_pdf(file_bytes)
    return "\n".join(lines)


def _parse_coeff_list(text: str) -> list[str]:
    items = [x.strip() for x in (text or "").split(",")]
    return [x for x in items if x]

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
    
    # Анализ данных - единая кнопка запуска всех модулей
    st.title("🚀 Анализ данных")

    st.session_state.coeff_source = st.selectbox(
        "Источник коэффициентов",
        ["Локальный пайплайн", "Через API (extract_coeffs)"],
        index=0 if st.session_state.coeff_source == "Локальный пайплайн" else 1,
    )

    if st.session_state.coeff_source == "Через API (extract_coeffs)":
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
    
    # Кнопка запуска всех модулей сразу
    if st.button("🔍 Запустить анализ", use_container_width=True, type="primary"):
        if st.session_state.documents:
            with st.spinner("Запуск модулей анализа..."):
                st.session_state.processing_started = True

                primary_file = st.session_state.documents[0]
                file_bytes = primary_file.getvalue()

                # 1) Коэффициенты: локально или через API
                if st.session_state.coeff_source == "Через API (extract_coeffs)":
                    coeff_list = _parse_coeff_list(st.session_state.coeff_list_text)
                    if not coeff_list:
                        st.error("⚠️ Укажите хотя бы один коэффициент/показатель для извлечения.")
                        st.stop()
                    if not st.session_state.api_key:
                        st.error("⚠️ Введите API key для выбранного провайдера.")
                        st.stop()

                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(file_bytes)
                            tmp_path = tmp.name

                        extracted = extract_coeffs(
                            api_key=st.session_state.api_key,
                            model_family=st.session_state.model_family,
                            model_name=st.session_state.model_name,
                            file_path=tmp_path,
                            coefficients=coeff_list,
                            chunk_size=6000,
                        )

                        st.session_state.coefficients_data = {
                            "file_name": primary_file.name,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "coefficients": extracted,
                            "warnings": [],
                            "metrics_detailed": [],
                            "facts": {},
                            "parse_meta": {},
                        }
                    except Exception as e:
                        st.session_state.coefficients_data = None
                        st.session_state.recommendations = f"Ошибка extract_coeffs: {str(e)}"
                        st.session_state.report_generated = False
                        st.error("❌ Ошибка при извлечении коэффициентов через API.")
                        st.stop()
                else:
                    # Локальный pipeline (financial_pipeline)
                    try:
                        st.session_state.coefficients_data = run_pipeline_on_uploaded_pdf(
                            file_bytes=file_bytes,
                            file_name=primary_file.name,
                        )
                    except Exception as e:
                        st.session_state.coefficients_data = None
                        st.session_state.recommendations = f"Ошибка расчета коэффициентов: {str(e)}"
                        st.session_state.report_generated = False
                        st.error("❌ Ошибка при обработке PDF. Проверьте формат документа.")
                        st.stop()

                # 2) Рекомендации через Ollama (строго: модель qwen3.5:9b, промпт = текст PDF)
                try:
                    pdf_text = _pdf_bytes_to_text(file_bytes)
                    prompt = pdf_text
                    
                    # Получаем рекомендации от Ollama
                    recommendation_text = get_recommendation(
                        model_name="qwen3.5:9b",
                        prompt=prompt,
                        system_prompt="Ты профессиональный финансовый аналитик. Дай краткие и практические рекомендации по улучшению финансового состояния компании на основе данных из документа.",
                        temperature=0.3
                    )
                    
                    # Сохраняем в сессию
                    st.session_state.recommendations = recommendation_text
                    
                except Exception as e:
                    st.session_state.recommendations = f"Ошибка получения рекомендаций: {str(e)}"
                
                # Модуль 3: Генерация отчета (имитация)
                st.session_state.report_generated = True
                
                st.success("✅ Анализ завершен! Все модули выполнены.")
        else:
            st.warning("⚠️ Сначала загрузите PDF документы")
    
    # Информация о статусе выполнения модулей
    if st.session_state.processing_started:
        st.divider()
        st.markdown("### 📊 Статус модулей")
        
        # Статус для коэффициентов
        if st.session_state.coefficients_data:
            st.success("✅ Коэффициенты: готово")
        else:
            st.info("⏳ Коэффициенты: ожидание")
        
        # Статус для рекомендаций
        if st.session_state.recommendations:
            st.success("✅ Рекомендации: готово")
        else:
            st.info("⏳ Рекомендации: ожидание")
        
        # Статус для отчета
        if st.session_state.report_generated:
            st.success("✅ Отчет: готово")
        else:
            st.info("⏳ Отчет: ожидание")

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
        
        # Визуализация коэффициентов
        fig = px.bar(
            x=list(st.session_state.coefficients_data['coefficients'].keys()),
            y=list(st.session_state.coefficients_data['coefficients'].values()),
            title="Значения коэффициентов",
            labels={'x': 'Коэффициенты', 'y': 'Значение'}
        )
        st.plotly_chart(fig, use_container_width=True)
    elif st.session_state.documents and not st.session_state.processing_started:
        st.info("ℹ️ Нажмите кнопку 'Запустить анализ' в боковой панели для расчета коэффициентов")
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
        st.info("ℹ️ Нажмите кнопку 'Запустить анализ' в боковой панели для генерации рекомендаций")
    elif not st.session_state.documents:
        st.info("ℹ️ Загрузите PDF документ в боковой панели")

# Вкладка 3: Отчеты
with tab3:
    st.header("Генерация отчетов")
    
    if st.session_state.report_generated and st.session_state.processing_started:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("Настройки")
            
            report_type = st.selectbox(
                "Тип отчета",
                ["Краткий отчет", "Полный отчет", "Аналитическая записка"]
            )
            
            include_charts = st.checkbox("Включить графики", value=True)
            include_recommendations = st.checkbox("Включить рекомендации", value=True)
            
            st.markdown("### Экспорт")
            if st.button("📄 Экспорт в PDF", use_container_width=True):
                st.success("PDF отчет сгенерирован (демо-режим)")
        
        with col2:
            st.subheader("Предварительный просмотр")
            
            with st.container(border=True):
                st.markdown("### Отчет по анализу документа")
                if st.session_state.coefficients_data:
                    st.markdown(f"**Документ:** {st.session_state.coefficients_data['file_name']}")
                    st.markdown(f"**Дата анализа:** {st.session_state.coefficients_data['date']}")
                
                if st.session_state.coefficients_data:
                    st.markdown("#### Коэффициенты")
                    for name, value in st.session_state.coefficients_data['coefficients'].items():
                        st.markdown(f"- **{name}:** {value}")
                
                if include_recommendations and st.session_state.recommendations:
                    st.markdown("#### Рекомендации")
                    if isinstance(st.session_state.recommendations, str):
                        st.markdown(st.session_state.recommendations)
                    else:
                        for rec in st.session_state.recommendations:
                            st.markdown(f"- {rec['рекомендация']}")
    elif st.session_state.documents and not st.session_state.processing_started:
        st.info("ℹ️ Нажмите кнопку 'Запустить анализ' в боковой панели для формирования отчета")
    elif not st.session_state.documents:
        st.info("ℹ️ Загрузите PDF документ в боковой панели")

# Добавим кнопку сброса внизу боковой панели
with st.sidebar:
    st.divider()
    if st.button("🔄 Сбросить все данные", use_container_width=True):
        for key in ['documents', 'processing_started', 'coefficients_data', 
                   'recommendations', 'report_generated']:
            if key in st.session_state:
                if key == 'documents':
                    st.session_state[key] = []
                elif key == 'processing_started':
                    st.session_state[key] = False
                else:
                    st.session_state[key] = None
        st.rerun()