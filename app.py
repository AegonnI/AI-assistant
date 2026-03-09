import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import requests
# Добавьте эту строку в начало файла, где остальные импорты
from recommendation_module import get_recommendation

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
    
    # Кнопка запуска всех модулей сразу
    if st.button("🔍 Запустить анализ", use_container_width=True, type="primary"):
        if st.session_state.documents:
            with st.spinner("Запуск модулей анализа..."):
                # Имитация работы модулей
                st.session_state.processing_started = True
                
                # Модуль 1: Подсчет коэффициентов (имитация)
                st.session_state.coefficients_data = {
                    'file_name': uploaded_files[0].name if uploaded_files else "document.pdf",
                    'date': datetime.now().strftime("%Y-%m-%d"),
                    'coefficients': {
                        'Коэффициент ликвидности': 2.5,
                        'Коэффициент рентабельности': 0.15,
                        'Коэффициент автономии': 0.6,
                        'Коэффициент оборачиваемости': 4.2
                    }
                }
                
                # Модуль 2: Генерация рекомендаций через Ollama
                try:
                    # Формируем промпт на основе коэффициентов
                    coeffs = st.session_state.coefficients_data['coefficients']
                    prompt = f"""
                    На основе следующих финансовых коэффициентов компании:
                    - Коэффициент ликвидности: {coeffs.get('Коэффициент ликвидности', 'N/A')}
                    - Коэффициент рентабельности: {coeffs.get('Коэффициент рентабельности', 'N/A')}
                    - Коэффициент автономии: {coeffs.get('Коэффициент автономии', 'N/A')}
                    - Коэффициент оборачиваемости: {coeffs.get('Коэффициент оборачиваемости', 'N/A')}
                    
                    Дай 3-4 конкретные рекомендации по улучшению финансового состояния компании.
                    Для каждой рекомендации укажи: параметр, саму рекомендацию и ожидаемый эффект.
                    Ответ представь в структурированном виде.
                    """
                    
                    # Получаем рекомендации от Ollama
                    recommendation_text = get_recommendation(
                        model_name="llama3.2",  # или другая модель, которая у вас есть
                        prompt=prompt,
                        system_prompt="Ты профессиональный финансовый аналитик. Даешь конкретные, практические рекомендации.",
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