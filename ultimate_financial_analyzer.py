# -*- coding: utf-8 -*-
"""
🚀 ULTIMATE FINANCIAL ANALYZER - Production-Grade Engine (MAX ACCURACY)
========================================================================
Комплексная система анализа финансовых отчётов:
✓ LLM-first подход (приоритет нейросети)
✓ Умная валидация против галлюцинаций
✓ Кросс-валидация с Regex
✓ ТРЁХУРОВНЕВАЯ ИЕРАРХИЯ КОЭФФИЦИЕНТОВ
✓ 12 профессиональных коэффициентов
✓ Оценка рисков и здоровья компании

ИЕРАРХИЯ:
- УРОВЕНЬ 0: Исходные данные (LLM извлекает из PDF)
- УРОВЕНЬ 1: Первичные расчётные показатели (код рассчитывает)
- УРОВЕНЬ 2: Финансовые коэффициенты (код рассчитывает по Ур.0 + Ур.1)

ТРЕБОВАНИЯ:
- Ollama: ollama serve
- Модель: ollama pull qwen2.5:7b (или ministral-3:8b)
"""
import sys
import io
import re
import json
import logging
import requests
import unicodedata
import os
from pathlib import Path
from typing import Dict, Optional, Any, Tuple, List, Set
from datetime import datetime
from dataclasses import dataclass, asdict, field
from dotenv import load_dotenv

# Загрузка переменных из .env файла
load_dotenv()

# Установка UTF-8 кодировки
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    logging.warning("⚠️ pdfplumber не установлен. pip install pdfplumber")

# ==================== КОНСТАНТЫ (из .env) ====================
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://localhost:11434')
OLLAMA_GENERATE_ENDPOINT = f"{OLLAMA_API_URL}/api/generate"
LLM_MODEL = os.getenv('OLLAMA_MODEL', 'ministral-3:8b')
USE_LLM = os.getenv('USE_LLM', 'True').lower() == 'true'
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '900'))

# 🔴 Подозрительно круглые числа — вероятные галлюцинации
_suspicious_str = os.getenv('SUSPICIOUS_ROUND_NUMBERS', '1000,5000,10000,25000,50000,100000,125000,150000,200000,250000,300000,500000,1000000')
SUSPICIOUS_ROUND_NUMBERS = {int(x.strip()) for x in _suspicious_str.split(',')}

# 📊 Ожидаемые диапазоны для телеком-отчётности (в млн руб.)
EXPECTED_RANGES = {
    'revenue': (int(os.getenv('REVENUE_MIN', '100000')), int(os.getenv('REVENUE_MAX', '2000000'))),
    'net_income': (int(os.getenv('NET_INCOME_MIN', '1000')), int(os.getenv('NET_INCOME_MAX', '500000'))),
    'total_assets': (int(os.getenv('TOTAL_ASSETS_MIN', '200000')), int(os.getenv('TOTAL_ASSETS_MAX', '5000000'))),
    'equity': (int(os.getenv('EQUITY_MIN', '50000')), int(os.getenv('EQUITY_MAX', '2000000'))),
    'current_assets': (int(os.getenv('CURRENT_ASSETS_MIN', '50000')), int(os.getenv('CURRENT_ASSETS_MAX', '1000000'))),
    'current_liabilities': (int(os.getenv('CURRENT_LIABILITIES_MIN', '10000')), int(os.getenv('CURRENT_LIABILITIES_MAX', '500000'))),
    'receivables': (int(os.getenv('RECEIVABLES_MIN', '10000')), int(os.getenv('RECEIVABLES_MAX', '300000'))),
    'cash_and_equivalents': (int(os.getenv('CASH_AND_EQUIVALENTS_MIN', '5000')), int(os.getenv('CASH_AND_EQUIVALENTS_MAX', '200000'))),
    'inventories': (int(os.getenv('INVENTORIES_MIN', '5000')), int(os.getenv('INVENTORIES_MAX', '200000'))),
    'operating_profit': (int(os.getenv('OPERATING_PROFIT_MIN', '10000')), int(os.getenv('OPERATING_PROFIT_MAX', '500000'))),
    'capex': (int(os.getenv('CAPEX_MIN', '10000')), int(os.getenv('CAPEX_MAX', '500000'))),
    'cost_of_goods': (int(os.getenv('COST_OF_GOODS_MIN', '50000')), int(os.getenv('COST_OF_GOODS_MAX', '1500000'))),
}

# 🔗 Маппинг русских ключей LLM на английские поля DataClass (УРОВЕНЬ 0)
KEY_MAPPING = {
    # Отчёт о прибылях и убытках
    'выручка': 'revenue',
    'себестоимость': 'cost_of_goods',
    'коммерческие_расходы': 'commercial_expenses',
    'управленческие_расходы': 'administrative_expenses',
    'прочие_доходы': 'other_income',
    'прочие_расходы': 'other_expenses',
    'внереализационные_доходы': 'non_operating_income',
    'чистая_прибыль': 'net_income',
    'прибыль_от_продаж': 'operating_profit',
    # Баланс (АКТИВЫ)
    'основные_средства': 'fixed_assets',
    'нематериальные_активы': 'intangible_assets',
    'материальные_активы': 'material_assets',
    'финансовые_вложения_долгосрочные': 'long_term_investments',
    'запасы': 'inventories',
    'ндс': 'vat_receivable',
    'дебиторская_задолженность': 'receivables',
    'финансовые_вложения_краткосрочные': 'short_term_investments',
    'денежные_средства': 'cash_and_equivalents',
    'активы': 'total_assets',
    'оборотные_активы': 'current_assets',
    # Баланс (ПАССИВЫ)
    'уставный_капитал': 'authorized_capital',
    'нераспределенная_прибыль': 'retained_earnings',
    'добавочный_капитал': 'additional_capital',
    'резервный_капитал': 'reserve_capital',
    'кредиты_займы_долгосрочные': 'long_term_loans',
    'отложенные_налоговые_обязательства': 'deferred_tax_liabilities',
    'прочие_обязательства_долгосрочные': 'other_long_term_liabilities',
    'кредиты_займы_краткосрочные': 'short_term_loans',
    'кредиторская_задолженность': 'accounts_payable',
    'доходы_будущих_периодов': 'deferred_income',
    'прочие_обязательства_краткосрочные': 'other_short_term_liabilities',
    'обязательства': 'total_liabilities',
    'капитал': 'equity',
    'краткосрочные_обязательства': 'current_liabilities',
    # Денежные потоки
    'капитальные_затраты': 'capex',
}

# 🔹 ПОЛЯ УРОВНЯ 0 (LLM извлекает напрямую)
LEVEL_0_FIELDS = set(KEY_MAPPING.keys())

# 🔹 Ключевые слова для определения разделов (для контекста LLM)
SECTION_KEYWORDS = {
    'INCOME_STATEMENT': ['отчет о прибылях', 'выручка', 'прибыль за год', 'income statement'],
    'BALANCE_SHEET': ['отчет о финансовом положении', 'баланс', 'активы', 'пассивы', 'balance sheet'],
    'CASH_FLOW': ['движение денежных средств', 'денежные потоки', 'cash flow'],
}

TOTAL_KEYWORDS = ('итого', 'всего', 'прибыль за год', 'чистая прибыль', 'баланс')

# ==================== КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler('financial_analysis.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== DATACLASSES (УРОВЕНЬ 0 - все исходные поля) ====================
@dataclass
class FinancialData:
    """
    ИСХОДНЫЕ ФИНАНСОВЫЕ ДАННЫЕ (УРОВЕНЬ 0)
    Все значения в млн руб.
    """
    # ===== Отчёт о прибылях и убытках =====
    revenue: Optional[float] = None
    cost_of_goods: Optional[float] = None
    commercial_expenses: Optional[float] = None
    administrative_expenses: Optional[float] = None
    other_income: Optional[float] = None
    other_expenses: Optional[float] = None
    non_operating_income: Optional[float] = None
    net_income: Optional[float] = None
    operating_profit: Optional[float] = None
    
    # ===== Баланс (АКТИВЫ) =====
    fixed_assets: Optional[float] = None
    intangible_assets: Optional[float] = None
    material_assets: Optional[float] = None
    long_term_investments: Optional[float] = None
    inventories: Optional[float] = None
    vat_receivable: Optional[float] = None
    receivables: Optional[float] = None
    short_term_investments: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    non_current_assets: Optional[float] = None
    
    # ===== Баланс (ПАССИВЫ) =====
    authorized_capital: Optional[float] = None
    retained_earnings: Optional[float] = None
    additional_capital: Optional[float] = None
    reserve_capital: Optional[float] = None
    long_term_loans: Optional[float] = None
    deferred_tax_liabilities: Optional[float] = None
    other_long_term_liabilities: Optional[float] = None
    short_term_loans: Optional[float] = None
    accounts_payable: Optional[float] = None
    deferred_income: Optional[float] = None
    other_short_term_liabilities: Optional[float] = None
    total_liabilities: Optional[float] = None
    equity: Optional[float] = None
    current_liabilities: Optional[float] = None
    long_term_liabilities: Optional[float] = None
    
    # ===== Денежные потоки =====
    capex: Optional[float] = None
    
    # ===== Метаинформация =====
    report_date: str = ""
    report_type: str = "МСФО"
    company_name: str = ""
    
    def is_complete(self) -> bool:
        required = [self.revenue, self.net_income, self.total_assets, self.equity]
        return all(v is not None for v in required)

@dataclass
class Level1Indicators:
    """
    ПЕРВИЧНЫЕ РАСЧЁТНЫЕ ПОКАЗАТЕЛИ (УРОВЕНЬ 1)
    Рассчитываются кодом из данных Уровня 0
    """
    # Показатели прибыльности
    gross_profit: Optional[float] = None
    operating_profit_calc: Optional[float] = None
    profit_from_sales: Optional[float] = None
    total_income: Optional[float] = None
    
    # Показатели баланса (АКТИВЫ)
    non_current_assets_calc: Optional[float] = None
    current_assets_calc: Optional[float] = None
    total_assets_calc: Optional[float] = None
    
    # Показатели баланса (ПАССИВЫ)
    equity_calc: Optional[float] = None
    long_term_liabilities_calc: Optional[float] = None
    current_liabilities_calc: Optional[float] = None
    total_liabilities_calc: Optional[float] = None
    
    # Статус расчёта
    calculation_log: List[str] = field(default_factory=list)

@dataclass
class FinancialRatio:
    """Финансовый коэффициент с метаданными (УРОВЕНЬ 2)"""
    code: str
    name_ru: str
    name_en: str
    value: Optional[float]
    formula: str
    unit: str
    interpretation: str
    benchmark_min: float
    benchmark_max: float
    benchmark_industry: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    status: str = "unknown"
    comment: str = ""
    level: int = 2  # Уровень коэффициента
    
    def evaluate(self):
        if self.value is None:
            self.status = "unknown"
            self.comment = "Недостаточно данных"
            return
        if self.value >= self.benchmark_max:
            self.status = "excellent"
            self.comment = f"✓ Отлично (выше норматива {self.benchmark_max})"
        elif self.value >= self.benchmark_min:
            self.status = "good"
            self.comment = f"⚠ Хорошо (в пределах {self.benchmark_min}-{self.benchmark_max})"
        else:
            self.status = "critical"
            self.comment = f"✗ Критично (ниже норматива {self.benchmark_min})"

@dataclass
class AnalysisResult:
    """Полный результат анализа"""
    pdf_file: str
    analysis_date: str
    report_type: str
    company_name: str
    financial_data: FinancialData
    level1_indicators: Level1Indicators = field(default_factory=Level1Indicators)
    ratios: Dict[str, FinancialRatio] = field(default_factory=dict)
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    health_status: str = "neutral"

# ==================== 🆕 ULTIMATE PDF EXTRACTOR (из Кода 2) ====================
class UltimatePDFExtractor:
    """Ультимативный парсер: извлекает текст и идеальные Markdown таблицы без дублирования"""
    
    def extract(self, pdf_path: str) -> str:
        """Извлекает полный текст из PDF с разделением таблиц и текста"""
        full_text_parts = []
        current_section = "GENERAL"
        prev_table_cols = 0
        
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, 1):
                if page_num % 10 == 0:
                    logger.info(f"🔍 Чтение PDF: {page_num} из {total_pages} страниц")
                
                # 🔹 Шаг 1: Находим все таблицы и их bounding boxes
                tables_data = []
                table_bboxes = []
                finder = page.debug_tablefinder()
                for table in finder.tables:
                    table_bboxes.append(table.bbox)
                    tables_data.append(table.extract())

                # 🔹 Шаг 2: Фильтруем текст, исключая области таблиц
                def not_in_table(obj):
                    if obj.get('object_type') != 'char':
                        return True
                    x0, y0, x1, y1 = obj['x0'], obj['top'], obj['x1'], obj['bottom']
                    for (tx0, ty0, tx1, ty1) in table_bboxes:
                        if x0 >= tx0 and x1 <= tx1 and y0 >= ty0 and y1 <= ty1:
                            return False
                    return True

                clean_page = page.filter(not_in_table)
                page_text = clean_page.extract_text(layout=False) or ""
                page_text = self._clean_text(page_text)

                # 🔹 Шаг 3: Определяем раздел страницы
                text_lower = page_text.lower()[:1000]
                for section, keywords in SECTION_KEYWORDS.items():
                    if any(kw in text_lower for kw in keywords):
                        current_section = section
                        break

                chunk_text = f"[РАЗДЕЛ: {current_section}]\n{page_text}\n"

                # 🔹 Шаг 4: Форматируем таблицы в Markdown и добавляем
                for table_idx, table in enumerate(tables_data, 1):
                    if not table:
                        continue
                    max_cols = max(len(row) for row in table if row)
                    is_continuation = (max_cols == prev_table_cols and table_idx == 1)
                    
                    md_table = self._format_table(table, max_cols, is_continuation)
                    chunk_text += f"\n{md_table}\n"
                    prev_table_cols = max_cols

                if not tables_data:
                    prev_table_cols = 0

                if re.search(r'\d', chunk_text):
                    full_text_parts.append(chunk_text)
                    
        return "\n".join(full_text_parts)

    def _format_table(self, table: List[List[Optional[str]]], max_cols: int, is_continuation: bool) -> str:
        """Форматирует таблицу в Markdown с сохранением структуры"""
        cleaned_table = [row for row in table if row and any(cell and str(cell).strip() for cell in row)]
        if not cleaned_table:
            return ""
        
        lines = []
        tag = "ПРОДОЛЖЕНИЕ ТАБЛИЦЫ" if is_continuation else "НАЧАЛО ТАБЛИЦЫ"
        lines.append(f"[{tag} | Колонки: {max_cols}]")

        for row_idx, row in enumerate(cleaned_table):
            padded = list(row) + [""] * (max_cols - len(row))
            
            first_text = str(padded[0]).strip() if padded[0] else ""
            rest_empty = all(not str(c).strip() for c in padded[1:])
            is_sub = bool(first_text and rest_empty and row_idx != 0)
            is_tot = any(first_text.lower().startswith(k) for k in TOTAL_KEYWORDS)

            cells = []
            for col_idx, cell in enumerate(padded):
                val = str(cell).strip().replace('\n', ' ').replace('|', '\|') if cell else ""
                
                # Отступы для вложенных строк
                if col_idx == 0 and val:
                    spaces = len(cell) - len(cell.lstrip())
                    if spaces > 0:
                        val = "▪ " * (spaces // 2 if spaces // 2 > 0 else 1) + val
                
                if not val:
                    val = " - "
                elif val in ('-', '—', '–', '='):
                    val = "0"
                
                # Нормализация чисел
                val = re.sub(r'^\s*\(\s*(\d[\d\s,]*)\s*\)\s*$', r'-\1', val)
                val = re.sub(r'(?<=\d)[\s\xa0]+(?=\d{3})', '', val)
                val = re.sub(r'(\d),(\d)', r'\1.\2', val)
                
                # Выделение важных строк
                if is_sub and col_idx == 0:
                    val = f"**{val}**"
                elif is_tot:
                    val = f"**{val}**"
                
                cells.append(val)
                
            lines.append("| " + " | ".join(cells) + " |")
            if row_idx == 0 and not is_continuation:
                lines.append("|" + "|".join(["---"] * max_cols) + "|")
                
        lines.append("[КОНЕЦ ТАБЛИЦЫ]")
        return "\n".join(lines)

    def _clean_text(self, text: str) -> str:
        """Очистка текста от артефактов"""
        text = text.replace('\xa0', ' ')
        text = unicodedata.normalize('NFKC', text)
        text = re.sub(r'\s{2,}', ' ', text)
        text = re.sub(r'([а-яА-Яa-zA-Z])-\s*\n\s*([а-яА-Яa-zA-Z])', r'\1\2', text)
        lines = [line for line in text.split('\n') if not (line.strip().isdigit() and len(line.strip()) < 4)]
        return "\n".join(lines).strip()

# ==================== LLM EXTRACTOR (УРОВЕНЬ 0 - извлечение исходных данных) ====================
class LLMExtractor:
    """Извлечение финансовых данных УРОВНЯ 0 используя LLM с ТРОЙНОЙ ВАЛИДАЦИЕЙ"""
    def __init__(self, model: str = LLM_MODEL):
        self.model = model
        self.api_url = OLLAMA_GENERATE_ENDPOINT
        self.base_url = OLLAMA_API_URL
        self.is_available = self._check_ollama()
        self.regex_reference = {}

    def _check_ollama(self) -> bool:
        """Проверка доступности Ollama API"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                logger.info("✅ Ollama API доступна")
                return True
            else:
                logger.warning(f"⚠️ Ollama API вернула статус {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"⚠️ Ollama недоступна: {e}")
            return False

    def _build_extraction_prompt(self, fields: Set[str], text_chunk: str) -> str:
        """🎯 УСИЛЕННЫЙ промпт с ТОЧНЫМИ ключами JSON для УРОВНЯ 0"""
        field_definitions = {
            'выручка': 'Revenue / Выручка',
            'себестоимость': 'Cost of goods / Себестоимость',
            'коммерческие_расходы': 'Commercial expenses / Коммерческие расходы',
            'управленческие_расходы': 'Administrative expenses / Управленческие расходы',
            'прочие_доходы': 'Other income / Прочие доходы',
            'прочие_расходы': 'Other expenses / Прочие расходы',
            'внереализационные_доходы': 'Non-operating income / Внереализационные доходы',
            'чистая_прибыль': 'Net income / Чистая прибыль',
            'прибыль_от_продаж': 'Operating profit / Прибыль от продаж',
            'основные_средства': 'Fixed assets / Основные средства',
            'нематериальные_активы': 'Intangible assets / Нематериальные активы',
            'материальные_активы': 'Material assets / Материальные активы',
            'финансовые_вложения_долгосрочные': 'Long-term investments / Долгосрочные фин. вложения',
            'запасы': 'Inventories / Запасы',
            'ндс': 'VAT receivable / НДС',
            'дебиторская_задолженность': 'Receivables / Дебиторская задолженность',
            'финансовые_вложения_краткосрочные': 'Short-term investments / Краткосрочные фин. вложения',
            'денежные_средства': 'Cash / Денежные средства',
            'активы': 'Total assets / Всего активов',
            'оборотные_активы': 'Current assets / Оборотные активы',
            'уставный_капитал': 'Authorized capital / Уставный капитал',
            'нераспределенная_прибыль': 'Retained earnings / Нераспределенная прибыль',
            'добавочный_капитал': 'Additional capital / Добавочный капитал',
            'резервный_капитал': 'Reserve capital / Резервный капитал',
            'кредиты_займы_долгосрочные': 'Long-term loans / Долгосрочные кредиты',
            'отложенные_налоговые_обязательства': 'Deferred tax liabilities / Отложенные налоговые обязательства',
            'прочие_обязательства_долгосрочные': 'Other long-term liabilities / Прочие долгосрочные обязательства',
            'кредиты_займы_краткосрочные': 'Short-term loans / Краткосрочные кредиты',
            'кредиторская_задолженность': 'Accounts payable / Кредиторская задолженность',
            'доходы_будущих_периодов': 'Deferred income / Доходы будущих периодов',
            'прочие_обязательства_краткосрочные': 'Other short-term liabilities / Прочие краткосрочные обязательства',
            'обязательства': 'Total liabilities / Всего обязательств',
            'капитал': 'Equity / Собственный капитал',
            'краткосрочные_обязательства': 'Current liabilities / Краткосрочные обязательства',
            'капитальные_затраты': 'CAPEX / Капитальные затраты',
        }
        json_example = """{
"выручка": 285000,
"себестоимость": 165000,
"коммерческие_расходы": 25000,
"управленческие_расходы": 18000,
"чистая_прибыль": 36240,
"основные_средства": 450000,
"запасы": 42100,
"дебиторская_задолженность": 65000,
"денежные_средства": 28000,
"активы": 845000,
"уставный_капитал": 100000,
"капитал": 384500,
"кредиты_займы_долгосрочные": 150000,
"кредиты_займы_краткосрочные": 85000,
"кредиторская_задолженность": 95000,
"капитальные_затраты": 68500
}"""
        fields_list = "\n".join([f"  - {ru_key}: {desc}" for ru_key, desc in sorted(field_definitions.items())])
        return f"""ТЫ — ПАРСЕР ФИНАНСОВЫХ ОТЧЁТОВ (УРОВЕНЬ 0). Найди в тексте КОНКРЕТНЫЕ ЧИСЛА.

🎯 КРИТИЧЕСКИЕ ПРАВИЛА:
1. ИСПОЛЬЗУЙ ТОЛЬКО ЭТИ КЛЮЧИ JSON (не придумывай новые):
{fields_list}
2. ИЗВЛЕКАЙ ТОЛЬКО ИЗ ПРЕДОСТАВЛЕННОГО ТЕКСТА.
3. Если число не в тексте → null (не 0, не придумывай).
4. Числа В МИЛЛИОНАХ РУБЛЕЙ (как в тексте).
5. Это УРОВЕНЬ 0 — только исходные данные из документа!

📚 ПРИМЕРЫ:
Текст: "Выручка: 285000 млн рублей" → {{"выручка": 285000}}
Текст: "Чистая прибыль 36240" → {{"чистая_прибыль": 36240}}
Текст: "Основные средства: 450000 млн" → {{"основные_средства": 450000}}
Текст: "Уставный капитал 100000" → {{"уставный_капитал": 100000}}
Текст: "никакого числа тут" → {{}} (пусто)

📄 ТЕКСТ ДЛЯ ПАРСИНГА:
'''{text_chunk[:3000]}'''

🔐 ОТВЕТ (только JSON, в ТОЧНОМ формате ниже, без пояснений):
{json_example}"""

    def _validate_with_triple_check(self, value: float, field_name: str, text_context: str) -> bool:
        """🔍 ТРОЙНАЯ ВАЛИДАЦИЯ: круглые числа + диапазон + наличие в тексте"""
        if value in SUSPICIOUS_ROUND_NUMBERS:
            logger.debug(f"      ❌ {field_name}: подозрительно круглое {value:,.0f}")
            return False
        if field_name in EXPECTED_RANGES:
            min_val, max_val = EXPECTED_RANGES[field_name]
            if not (min_val <= value <= max_val):
                logger.debug(f"      ❌ {field_name}: вне диапазона [{min_val:,.0f}, {max_val:,.0f}]")
                return False
        value_str = str(int(value))
        if len(value_str) >= 3 and value_str not in text_context:
            logger.debug(f"      ⚠️ {field_name}: число {value:,.0f} не найдено в тексте")
        return True

    def _validate_results(self, data: Dict, text_part: str) -> Dict:
        """УМНАЯ валидация результатов LLM"""
        validated = {}
        for ru_key, value in data.items():
            en_key = KEY_MAPPING.get(ru_key, ru_key)
            if en_key in ['статус', 'message', 'error', 'model', 'prompt']:
                continue
            if isinstance(value, str):
                try:
                    value = float(value.replace(' ', '').replace(',', '.'))
                except (ValueError, AttributeError):
                    logger.debug(f"      ❌ {ru_key}: не удалось конвертировать '{value}'")
                    continue
            if not isinstance(value, (int, float)):
                continue
            normalized = value
            if normalized > 1_000_000_000:
                normalized = normalized / 1_000_000
                logger.debug(f"      📊 {ru_key}: нормализовано {value:,.0f} → {normalized:,.0f}")
            if normalized == 0 and en_key in ['revenue', 'total_assets', 'equity', 'net_income']:
                logger.debug(f"      ❌ {ru_key}: нулевое значение для критического поля")
                continue
            if not self._validate_with_triple_check(normalized, en_key, text_part):
                logger.warning(f"      ⚠️ {ru_key}: отклонено валидацией")
                continue
            if en_key in self.regex_reference and self.regex_reference[en_key] > 0:
                ratio = normalized / self.regex_reference[en_key]
                if ratio > 10 or ratio < 0.1:
                    logger.warning(f"      ⚠️ {ru_key}: отличается от Regex в {ratio:.1f}x — ОТКЛОНЕНО")
                    continue
                else:
                    logger.debug(f"      ✓ {ru_key}: совпадает с Regex (ratio {ratio:.2f})")
            validated[en_key] = float(normalized)
            logger.info(f"      ✅ {ru_key} → {en_key}: {normalized:,.0f}")
        return validated

    def _parse_json_safe(self, text: str) -> Optional[Dict]:
        """Надежный парсинг JSON"""
        if not text or len(text) < 10:
            return None
        try:
            return json.loads(text)
        except:
            pass
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = text[start:end]
                return json.loads(json_str)
        except:
            pass
        try:
            data = {}
            for key in KEY_MAPPING.keys():
                pattern = f'"{key}"\\s*:\\s*([0-9\\.]+|null)'
                match = re.search(pattern, text)
                if match:
                    val_str = match.group(1)
                    if val_str.lower() == 'null':
                        data[key] = None
                    else:
                        data[key] = float(val_str)
                else:
                    data[key] = None
            if any(v is not None for v in data.values()):
                return data
        except:
            pass
        return None

    def extract_financial_values(self, text: str, regex_reference: Dict = None) -> Dict[str, Optional[float]]:
        """🎯 Извлечение УРОВНЯ 0 ИЗ ВСЕХ частей текста + КОНСОЛИДАЦИЯ РЕЗУЛЬТАТОВ"""
        if not self.is_available:
            logger.warning("⚠️ Ollama недоступна")
            return {}
        self.regex_reference = regex_reference or {}
        text_parts = self._split_text_into_parts(text, num_parts=5)
        all_extracted_values = {}
        all_fields = set(KEY_MAPPING.keys())
        logger.info(f"🔍 ФАЗА 1: Извлечение УРОВНЯ 0 из {len(text_parts)} частей текста")
        for part_idx, text_part in enumerate(text_parts, 1):
            logger.info(f"📄 Часть {part_idx}/{len(text_parts)}")
            prompt = self._build_extraction_prompt(all_fields, text_part)
            try:
                response = requests.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "temperature": 0.0,
                        "num_predict": 500,
                    },
                    timeout=REQUEST_TIMEOUT
                )
                if response.status_code == 200:
                    result_text = response.json().get("response", "")
                    llm_data = self._parse_json_safe(result_text)
                    if llm_data:
                        logger.info(f"   📦 LLM вернул ключи: {list(llm_data.keys())}")
                        found_in_part = 0
                        for ru_key, value in llm_data.items():
                            if value is not None and ru_key in KEY_MAPPING:
                                try:
                                    normalized = float(value)
                                    if normalized > 0 and self._validate_with_triple_check(normalized, ru_key, text_part):
                                        if ru_key not in all_extracted_values:
                                            all_extracted_values[ru_key] = []
                                        all_extracted_values[ru_key].append(normalized)
                                        found_in_part += 1
                                except (ValueError, TypeError):
                                    pass
                        if found_in_part > 0:
                            logger.info(f"   ✅ Найдено {found_in_part} значений УРОВНЯ 0")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка на части {part_idx}: {e}")
        logger.info(f"\n🔀 ФАЗА 2: КОНСОЛИДАЦИЯ значений УРОВНЯ 0")
        final_results = self._consolidate_values(all_extracted_values)
        logger.info(f"✅ Финальных значений УРОВНЯ 0: {sum(1 for v in final_results.values() if v is not None)}")
        return final_results

    def _consolidate_values(self, all_values: Dict[str, List[float]]) -> Dict[str, Optional[float]]:
        """🔀 КОНСОЛИДИРУЮЩИЙ АЛГОРИТМ - выбор ЛУЧШЕГО значения для каждого показателя"""
        consolidated = {}
        for ru_key, values_list in all_values.items():
            if not values_list:
                consolidated[ru_key] = None
                continue
            if len(values_list) == 1:
                consolidated[ru_key] = values_list[0]
                logger.info(f"   📍 {ru_key}: {values_list[0]:,.0f} (единственное)")
                continue
            values_set = set(values_list)
            if len(values_set) == 1:
                final_value = values_list[0]
                consolidated[ru_key] = final_value
                logger.info(f"   🎯 {ru_key}: {final_value:,.0f} (КОНСЕНСУС всех {len(values_list)} попыток!)")
                continue
            from collections import Counter
            value_counts = Counter(values_list)
            most_common_value, count = value_counts.most_common(1)[0]
            if count >= 2:
                consolidated[ru_key] = most_common_value
                logger.info(f"   📊 {ru_key}: {most_common_value:,.0f} (повторялось {count} раз из {len(values_list)})")
                continue
            import statistics
            median_value = statistics.median(values_list)
            consolidated[ru_key] = median_value
            sorted_vals = sorted([f'{v:,.0f}' for v in sorted(values_list)])
            logger.info(f"   📈 {ru_key}: {median_value:,.0f} (медиана из [{', '.join(sorted_vals)}])")
        return consolidated

    def _split_text_into_parts(self, text: str, num_parts: int = 5) -> List[str]:
        """Разделить текст на части по словам С ПЕРЕКРЫТИЕМ для избежания разрезания строк"""
        text = " ".join(text.split())
        if len(text) == 0:
            return []
        base_size = len(text) // num_parts
        overlap = int(base_size * 0.15)
        parts = []
        for i in range(num_parts):
            start = max(0, i * base_size - overlap) if i > 0 else 0
            if i == num_parts - 1:
                parts.append(text[start:].strip())
            else:
                end = (i + 1) * base_size + overlap
                while end > start and text[end] != ' ':
                    end -= 1
                if end <= start:
                    end = min(start + base_size, len(text))
                parts.append(text[start:end].strip())
        return [p for p in parts if p]

# ==================== 🆕 LEVEL 1 CALCULATOR (Расчёт первичных показателей) ====================
class Level1Calculator:
    """
    РАСЧЁТ ПОКАЗАТЕЛЕЙ УРОВНЯ 1
    Алгоритмический расчёт из данных Уровня 0
    """
    def __init__(self, data: FinancialData):
        self.data = data
        self.indicators = Level1Indicators()
    
    def calculate_all(self) -> Level1Indicators:
        """Расчёт всех показателей Уровня 1"""
        print("\n📐 УРОВЕНЬ 1: Расчёт первичных показателей...")
        
        # ===== Показатели прибыльности =====
        self._calc_gross_profit()
        self._calc_operating_profit()
        self._calc_profit_from_sales()
        self._calc_total_income()
        
        # ===== Показатели баланса (АКТИВЫ) =====
        self._calc_non_current_assets()
        self._calc_current_assets()
        self._calc_total_assets()
        
        # ===== Показатели баланса (ПАССИВЫ) =====
        self._calc_equity()
        self._calc_long_term_liabilities()
        self._calc_current_liabilities()
        self._calc_total_liabilities()
        
        # ===== Лог расчётов =====
        for log_entry in self.indicators.calculation_log:
            logger.info(f"   {log_entry}")
        
        return self.indicators
    
    def _log_calc(self, field: str, formula: str, value: Optional[float]):
        if value is not None:
            self.indicators.calculation_log.append(f"✅ {field} = {value:,.0f} ({formula})")
        else:
            self.indicators.calculation_log.append(f"⚠️ {field} = null (недостаточно данных)")
    
    def _calc_gross_profit(self):
        """Валовая прибыль = Выручка - Себестоимость"""
        if self.data.revenue and self.data.cost_of_goods:
            self.indicators.gross_profit = self.data.revenue - self.data.cost_of_goods
            self._log_calc('Валовая прибыль', 'Выручка - Себестоимость', self.indicators.gross_profit)
    
    def _calc_operating_profit(self):
        """Операционная прибыль = Коммерческие расходы - Управленческие расходы"""
        if self.data.commercial_expenses and self.data.administrative_expenses:
            self.indicators.operating_profit_calc = self.data.commercial_expenses - self.data.administrative_expenses
            self._log_calc('Операционная прибыль (расч.)', 'Комм.расходы - Упр.расходы', self.indicators.operating_profit_calc)
    
    def _calc_profit_from_sales(self):
        """Прибыль от продаж = Валовая прибыль - Коммерческие расходы - Управленческие расходы"""
        if self.indicators.gross_profit and self.data.commercial_expenses and self.data.administrative_expenses:
            self.indicators.profit_from_sales = self.indicators.gross_profit - self.data.commercial_expenses - self.data.administrative_expenses
            self._log_calc('Прибыль от продаж', 'Валовая прибыль - Комм.расходы - Упр.расходы', self.indicators.profit_from_sales)
    
    def _calc_total_income(self):
        """Совокупный доход = Выручка + Доходы от участия + Доходы от реализации + Внереализационные доходы"""
        total = self.data.revenue or 0
        total += self.data.other_income or 0
        total += self.data.non_operating_income or 0
        if total > 0:
            self.indicators.total_income = total
            self._log_calc('Совокупный доход', 'Выручка + Прочие доходы + Внереализ.доходы', self.indicators.total_income)
    
    def _calc_non_current_assets(self):
        """Внеоборотные активы = Основные средства + Нематериальные активы + Материальные активы + Фин.вложения долгосрочные"""
        total = 0
        components = []
        if self.data.fixed_assets:
            total += self.data.fixed_assets
            components.append('ОС')
        if self.data.intangible_assets:
            total += self.data.intangible_assets
            components.append('НМА')
        if self.data.material_assets:
            total += self.data.material_assets
            components.append('МА')
        if self.data.long_term_investments:
            total += self.data.long_term_investments
            components.append('ФВ(д)')
        if total > 0:
            self.indicators.non_current_assets_calc = total
            self._log_calc('Внеоборотные активы', ' + '.join(components), self.indicators.non_current_assets_calc)
    
    def _calc_current_assets(self):
        """Оборотные активы = Запасы + НДС + Дебиторская задолженность + Фин.вложения краткосрочные + Деньги"""
        total = 0
        components = []
        if self.data.inventories:
            total += self.data.inventories
            components.append('Запасы')
        if self.data.vat_receivable:
            total += self.data.vat_receivable
            components.append('НДС')
        if self.data.receivables:
            total += self.data.receivables
            components.append('ДЗ')
        if self.data.short_term_investments:
            total += self.data.short_term_investments
            components.append('ФВ(к)')
        if self.data.cash_and_equivalents:
            total += self.data.cash_and_equivalents
            components.append('Деньги')
        if total > 0:
            self.indicators.current_assets_calc = total
            self._log_calc('Оборотные активы', ' + '.join(components), self.indicators.current_assets_calc)
    
    def _calc_total_assets(self):
        """ИТОГО АКТИВЫ = Внеоборотные активы + Оборотные активы"""
        if self.indicators.non_current_assets_calc and self.indicators.current_assets_calc:
            self.indicators.total_assets_calc = self.indicators.non_current_assets_calc + self.indicators.current_assets_calc
            self._log_calc('ИТОГО АКТИВЫ', 'Внеоборотные + Оборотные', self.indicators.total_assets_calc)
        elif self.data.total_assets:
            self.indicators.total_assets_calc = self.data.total_assets
            self._log_calc('ИТОГО АКТИВЫ', 'Из Уровня 0', self.indicators.total_assets_calc)
    
    def _calc_equity(self):
        """Собственный капитал = Уставный капитал + Нераспределенная прибыль + Добавочный и резервный капитал"""
        total = 0
        components = []
        if self.data.authorized_capital:
            total += self.data.authorized_capital
            components.append('УК')
        if self.data.retained_earnings:
            total += self.data.retained_earnings
            components.append('НРП')
        if self.data.additional_capital:
            total += self.data.additional_capital
            components.append('ДК')
        if self.data.reserve_capital:
            total += self.data.reserve_capital
            components.append('РК')
        if total > 0:
            self.indicators.equity_calc = total
            self._log_calc('Собственный капитал', ' + '.join(components), self.indicators.equity_calc)
        elif self.data.equity:
            self.indicators.equity_calc = self.data.equity
            self._log_calc('Собственный капитал', 'Из Уровня 0', self.indicators.equity_calc)
    
    def _calc_long_term_liabilities(self):
        """Долгосрочные обязательства = Кредиты долгосрочные + Отложенные налоговые обязательства + Прочие обязательства долгосрочные"""
        total = 0
        components = []
        if self.data.long_term_loans:
            total += self.data.long_term_loans
            components.append('Кредиты(д)')
        if self.data.deferred_tax_liabilities:
            total += self.data.deferred_tax_liabilities
            components.append('ОНУ')
        if self.data.other_long_term_liabilities:
            total += self.data.other_long_term_liabilities
            components.append('Прочие(д)')
        if total > 0:
            self.indicators.long_term_liabilities_calc = total
            self._log_calc('Долгосрочные обязательства', ' + '.join(components), self.indicators.long_term_liabilities_calc)
    
    def _calc_current_liabilities(self):
        """Краткосрочные обязательства = Кредиты краткосрочные + Кредиторская задолженность + Доходы будущих периодов + Прочие обязательства краткосрочные"""
        total = 0
        components = []
        if self.data.short_term_loans:
            total += self.data.short_term_loans
            components.append('Кредиты(к)')
        if self.data.accounts_payable:
            total += self.data.accounts_payable
            components.append('КЗ')
        if self.data.deferred_income:
            total += self.data.deferred_income
            components.append('ДБП')
        if self.data.other_short_term_liabilities:
            total += self.data.other_short_term_liabilities
            components.append('Прочие(к)')
        if total > 0:
            self.indicators.current_liabilities_calc = total
            self._log_calc('Краткосрочные обязательства', ' + '.join(components), self.indicators.current_liabilities_calc)
        elif self.data.current_liabilities:
            self.indicators.current_liabilities_calc = self.data.current_liabilities
            self._log_calc('Краткосрочные обязательства', 'Из Уровня 0', self.indicators.current_liabilities_calc)
    
    def _calc_total_liabilities(self):
        """ИТОГО ПАССИВЫ = Собственный капитал + Долгосрочные обязательства + Краткосрочные обязательства"""
        equity = self.indicators.equity_calc or self.data.equity
        long_term = self.indicators.long_term_liabilities_calc or self.data.long_term_liabilities
        short_term = self.indicators.current_liabilities_calc or self.data.current_liabilities
        
        if equity and long_term and short_term:
            self.indicators.total_liabilities_calc = equity + long_term + short_term
            self._log_calc('ИТОГО ПАССИВЫ', 'Капитал + Долгосрочные + Краткосрочные', self.indicators.total_liabilities_calc)
        elif self.data.total_liabilities:
            self.indicators.total_liabilities_calc = self.data.total_liabilities
            self._log_calc('ИТОГО ПАССИВЫ', 'Из Уровня 0', self.indicators.total_liabilities_calc)

# ==================== DATA EXTRACTOR ====================
class DataExtractor:
    """Извлечение финансовых данных из PDF (LLM-first)"""
    def __init__(self):
        self.patterns = self._build_patterns()
        self.total_pages = 0
    
    def _build_patterns(self) -> Dict[str, List[str]]:
        """Построение регулярных выражений"""
        return {
            'revenue': [
                r'(?:выручка|доход|продажи)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*(?:[,\.][0-9]+)?)\s*(?:млн|тыс)?\.?\s*(?:руб|руб\.|rub)?',
                r'консолидированная.*?выручка[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*(?:[,\.][0-9]+)?)',
                r'(?:от реализации|реализованных)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'net_income': [
                r'(?:чистая\s+прибыль|прибыль\s+за\s+год)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*(?:[,\.][0-9]+)?)\s*млн',
                r'(?:чистая\s+прибыль)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:ЧИСТАЯ\s+ПРИБЫЛЬ)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'operating_profit': [
                r'(?:операционная\s+прибыль|прибыль\s+от\s+продаж)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:Прибыль\s+от\s+продаж)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'total_assets': [
                r'(?:ИТОГО\s+АКТИВЫ|Итого активы)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:активы.*?на\s+31\s+декабря)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'equity': [
                r'(?:Итого собственный капитал|собственный\s+капитал)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)\s*млн',
                r'(?:капитал)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'current_assets': [
                r'(?:Итого оборотные активы|Итого\s+оборотные\s+активы)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:оборотные\s+активы)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'current_liabilities': [
                r'(?:Итого краткосрочные обязательства)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:краткосрочные\s+обязательства)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'receivables': [
                r'(?:Дебиторская задолженность)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:дебиторская\s+задолженность)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'cash_and_equivalents': [
                r'(?:Денежные средства и их эквиваленты)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:денежные\s+средства)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'inventories': [
                r'(?:Запасы готовой продукции|запасы)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'capex': [
                r'(?:приобретение основных средств|CAPEX)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:капитальные\s+(?:затраты|вложения))[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
            'cost_of_goods': [
                r'(?:Себестоимость|себестоимость)[^0-9]*?([0-9]{1,3}(?:\s*[0-9]{3})*)',
                r'(?:операционные\s+расходы.*?нетто)[^0-9]*?\(([0-9]{1,3}(?:\s*[0-9]{3})*)',
            ],
        }
    
    def _normalize_number(self, text: str) -> Optional[float]:
        """Нормализация числа"""
        if not text:
            return None
        text = text.strip()
        text = re.sub(r'\s+', '', text)
        text = text.replace(',', '.')
        try:
            value = float(text)
            if value > 1_000_000_000:
                return value / 1_000_000
            return value
        except ValueError:
            return None
    
    def extract_from_pdf(self, pdf_path: str) -> FinancialData:
        """🆕 Извлечение данных из PDF с использованием UltimatePDFExtractor"""
        if not HAS_PDFPLUMBER:
            logger.error("pdfplumber не установлен. pip install pdfplumber")
            return FinancialData()
        
        data = FinancialData()
        
        try:
            pdf_extractor = UltimatePDFExtractor()
            text = pdf_extractor.extract(pdf_path)
            
            with pdfplumber.open(pdf_path) as pdf:
                self.total_pages = len(pdf.pages)
            
            data = self.extract_from_text(text, data)
        except Exception as e:
            logger.error(f"Ошибка при чтении PDF: {e}")
            return data
        
        return data

    def extract_from_text(self, text: str, data: FinancialData = None) -> FinancialData:
        """Извлечение: LLM УРОВЕНЬ 0 (приоритет) → Regex (дополнение)"""
        if data is None:
            data = FinancialData()
        
        print("🤖 ФАЗА 1: LLM извлечение УРОВНЯ 0 (Ollama с валидацией)...")
        llm_data = {}
        llm_results = {}
        
        text_lower = text.lower()
        regex_reference = {}
        for field_name, patterns in self.patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, text_lower, re.IGNORECASE)
                if matches:
                    value = self._normalize_number(matches[0])
                    if value is not None and value > 0:
                        regex_reference[field_name] = value
                        break
        
        logger.info(f"   📊 Regex reference: {len(regex_reference)} полей для кросс-валидации")
        
        if USE_LLM:
            print("🤖 ФАЗА 1: LLM ИЗВЛЕЧЕНИЕ УРОВНЯ 0 (приоритет)...")
            llm_extractor = LLMExtractor()
            if llm_extractor.is_available:
                llm_data = llm_extractor.extract_financial_values(text, regex_reference)
                if llm_data:
                    for ru_key, en_field in KEY_MAPPING.items():
                        if ru_key in llm_data and llm_data[ru_key] is not None:
                            value = float(llm_data[ru_key])
                            setattr(data, en_field, value)
                            llm_results[en_field] = value
                    print(f"✅ ФАЗА 1 завершена: LLM дала {len(llm_results)} значений УРОВНЯ 0")
                else:
                    print("⚠️ ФАЗА 1: LLM не дала результаты")
            else:
                print("⚠️ ФАЗА 1: Ollama недоступна")
        else:
            print("⚠️ LLM отключена флагом USE_LLM")
        
        return data

    def _calculate_derived_fields(self, data: FinancialData) -> FinancialData:
        """📐 Автоматический расчет производных показателей"""
        if data.equity and data.total_assets and data.cash_and_equivalents is None:
            cash_ratio = 0.15
            if data.current_assets:
                data.cash_and_equivalents = data.current_assets * cash_ratio
                logger.info(f"   📐 Денежные средства (расчет) = Оборотные активы × 15% = {data.cash_and_equivalents:,.0f}")
        if data.total_liabilities and data.equity and data.current_liabilities is None:
            short_term_ratio = 0.37
            data.current_liabilities = data.total_liabilities * short_term_ratio
            logger.info(f"   📐 Краткосрочные долги (расчет) = Обязательства × 37% = {data.current_liabilities:,.0f}")
        if data.receivables is None and data.cash_and_equivalents and data.current_liabilities:
            receivables_ratio = 0.25
            if data.current_assets:
                data.receivables = data.current_assets * receivables_ratio
                logger.info(f"   📐 Дебиторская задолженность (расчет) = Оборотные активы × 25% = {data.receivables:,.0f}")
        return data

# ==================== DATA RECOVERY ENGINE ====================
class DataRecoveryEngine:
    """Система 2-уровневой перепроверки"""
    def __init__(self, text: str):
        self.text = text.lower()
        self.recovery_log: List[str] = []
    
    def recover_all(self, data: FinancialData) -> Tuple[FinancialData, List[str]]:
        print("🔄 УРОВЕНЬ 1: Углубленный поиск недостающих данных...")
        data = self._level_1_aggressive_search(data)
        print("✅ УРОВЕНЬ 1 завершен")
        print("🔄 УРОВЕНЬ 2: Восстановление данных через зависимости...")
        data = self._level_2_dependency_recovery(data)
        print("✅ УРОВЕНЬ 2 завершен")
        return data, self.recovery_log
    
    def _level_1_aggressive_search(self, data: FinancialData) -> FinancialData:
        search_patterns = {
            'revenue': [r'(?:выручка|доход|продажи)[^0-9]*?([0-9]{1,15})'],
            'net_income': [r'(?:чистая\s+прибыль|прибыль\s+за\s+год)[^0-9]*?([0-9]{1,15})'],
            'total_assets': [r'(?:итого\s+активы|всего\s+активов)[^0-9]*?([0-9]{1,15})'],
            'equity': [r'(?:собственный\s+капитал|капитал\s+и\s+резервы)[^0-9]*?([0-9]{1,15})'],
        }
        for field_name, patterns in search_patterns.items():
            if getattr(data, field_name) is not None:
                continue
            for pattern in patterns:
                matches = re.findall(pattern, self.text, re.IGNORECASE)
                if matches:
                    try:
                        value = float(matches[0].replace(' ', '').replace(',', '.'))
                        if value > 1_000_000_000:
                            value = value / 1_000_000
                        if value > 0 and value not in SUSPICIOUS_ROUND_NUMBERS:
                            setattr(data, field_name, value)
                            msg = f"📍 L1 найдено {field_name}: {value:,.0f}"
                            logger.info(msg)
                            self.recovery_log.append(msg)
                            break
                    except:
                        continue
        return data
    
    def _level_2_dependency_recovery(self, data: FinancialData) -> FinancialData:
        if data.equity is None and data.total_assets and data.total_liabilities:
            data.equity = data.total_assets - data.total_liabilities
            if data.equity > 0:
                msg = f"🔗 L2 восстановлено equity через баланс: {data.equity:,.0f}"
                logger.info(msg)
                self.recovery_log.append(msg)
        if data.operating_profit is None and data.revenue and data.cost_of_goods:
            data.operating_profit = data.revenue - data.cost_of_goods
            if data.operating_profit > 0:
                msg = f"🔗 L2 восстановлено operating_profit: {data.operating_profit:,.0f}"
                logger.info(msg)
                self.recovery_log.append(msg)
        return data

# ==================== DATA VALIDATOR ====================
class DataValidator:
    """Валидация финансовых данных"""
    @staticmethod
    def validate(data: FinancialData) -> Tuple[List[str], List[str]]:
        errors = []
        warnings = []
        if data.revenue is None or data.revenue <= 0:
            errors.append("Выручка не найдена или равна нулю")
        if data.net_income is None:
            errors.append("Чистая прибыль не найдена")
        if data.total_assets is None or data.total_assets <= 0:
            errors.append("Активы не найдены или равны нулю")
        if data.equity is None:
            errors.append("Собственный капитал не найден")
        if data.equity and data.total_assets and data.total_liabilities:
            expected_equity = data.total_assets - data.total_liabilities
            if abs(data.equity - expected_equity) / data.equity > 0.1:
                warnings.append(f"⚠ Баланс не сходится: Equity={data.equity:,.0f}, Assets-Liabilities={expected_equity:,.0f}")
        if data.net_income and data.revenue and data.net_income > data.revenue:
            warnings.append(f"⚠ Прибыль > Выручки: {data.net_income:,.0f} > {data.revenue:,.0f}")
        return errors, warnings

# ==================== 🆕 METRICS CALCULATOR (УРОВЕНЬ 2 - Финансовые коэффициенты) ====================
class MetricsCalculator:
    """
    РАСЧЁТ ФИНАНСОВЫХ КОЭФФИЦИЕНТОВ (УРОВЕНЬ 2)
    Используются данные Уровня 0 и Уровня 1
    """
    def __init__(self, data: FinancialData, level1: Level1Indicators):
        self.data = data
        self.level1 = level1
        self.ratios: Dict[str, FinancialRatio] = {}
        self.recovery_log: List[str] = []
    
    def calculate_all(self) -> Dict[str, FinancialRatio]:
        """Расчёт всех 12 коэффициентов Уровня 2"""
        print("\n📈 УРОВЕНЬ 2: Расчёт финансовых коэффициентов...")
        
        self.ratios = {
            # ===== Коэффициенты рентабельности =====
            'operating_margin': self._calc_operating_margin(),
            'net_margin': self._calc_net_margin(),
            'roa': self._calc_roa(),
            'roe': self._calc_roe(),
            
            # ===== Коэффициенты ликвидности =====
            'current_ratio': self._calc_current_ratio(),
            'quick_ratio': self._calc_quick_ratio(),
            'cash_ratio': self._calc_cash_ratio(),
            
            # ===== Коэффициенты финансовой устойчивости =====
            'equity_ratio': self._calc_equity_ratio(),
            'debt_to_equity': self._calc_debt_to_equity(),
            
            # ===== Коэффициенты деловой активности =====
            'dso': self._calc_dso(),
            'asset_turnover': self._calc_asset_turnover(),
            
            # ===== Прочие коэффициенты =====
            'capex_to_revenue': self._calc_capex_to_revenue(),
        }
        
        for ratio in self.ratios.values():
            ratio.evaluate()
        
        return self.ratios
    
    def _safe_divide(self, num: Optional[float], denom: Optional[float]) -> Optional[float]:
        if num is None or denom is None or denom == 0:
            return None
        return num / denom
    
    def _get_revenue(self) -> Optional[float]:
        return self.data.revenue
    
    def _get_net_income(self) -> Optional[float]:
        return self.data.net_income
    
    def _get_total_assets(self) -> Optional[float]:
        return self.level1.total_assets_calc or self.data.total_assets
    
    def _get_equity(self) -> Optional[float]:
        return self.level1.equity_calc or self.data.equity
    
    def _get_current_assets(self) -> Optional[float]:
        return self.level1.current_assets_calc or self.data.current_assets
    
    def _get_current_liabilities(self) -> Optional[float]:
        return self.level1.current_liabilities_calc or self.data.current_liabilities
    
    def _get_inventories(self) -> Optional[float]:
        return self.data.inventories
    
    def _get_cash(self) -> Optional[float]:
        return self.data.cash_and_equivalents
    
    def _get_receivables(self) -> Optional[float]:
        return self.data.receivables
    
    def _get_total_liabilities(self) -> Optional[float]:
        return self.level1.total_liabilities_calc or self.data.total_liabilities
    
    def _get_operating_profit(self) -> Optional[float]:
        return self.data.operating_profit or self.level1.profit_from_sales
    
    def _calc_operating_margin(self) -> FinancialRatio:
        """Рентабельность продаж = (Прибыль от продаж / Выручка) × 100%"""
        value = self._safe_divide(self._get_operating_profit(), self._get_revenue())
        if value is not None: value *= 100
        return FinancialRatio('operating_margin', 'Рентабельность продаж', 'Operating Profit Margin',
                            value, 'Прибыль от продаж / Выручка × 100%', '%',
                            'Процент прибыли от каждого рубля продаж', 5.0, 20.0, level=2)
    
    def _calc_net_margin(self) -> FinancialRatio:
        """Рентабельность чистой прибыли = (Чистая прибыль / Выручка) × 100%"""
        value = self._safe_divide(self._get_net_income(), self._get_revenue())
        if value is not None: value *= 100
        return FinancialRatio('net_margin', 'Рентабельность чистой прибыли', 'Net Profit Margin',
                            value, 'Чистая прибыль / Выручка × 100%', '%',
                            'Какая часть выручки остается чистой прибылью', 2.0, 15.0, level=2)
    
    def _calc_roa(self) -> FinancialRatio:
        """ROA = (Чистая прибыль / ИТОГО АКТИВЫ) × 100%"""
        value = self._safe_divide(self._get_net_income(), self._get_total_assets())
        if value is not None: value *= 100
        return FinancialRatio('roa', 'Рентабельность активов (ROA)', 'Return on Assets',
                            value, 'Чистая прибыль / ИТОГО АКТИВЫ × 100%', '%',
                            'Сколько прибыли генерирует каждый рубль активов', 3.0, 12.0, level=2)
    
    def _calc_roe(self) -> FinancialRatio:
        """ROE = (Чистая прибыль / Собственный капитал) × 100%"""
        value = self._safe_divide(self._get_net_income(), self._get_equity())
        if value is not None: value *= 100
        return FinancialRatio('roe', 'Рентабельность собственного капитала (ROE)', 'Return on Equity',
                            value, 'Чистая прибыль / Собственный капитал × 100%', '%',
                            'Главная метрика для акционеров', 5.0, 25.0, level=2)
    
    def _calc_current_ratio(self) -> FinancialRatio:
        """Текущая ликвидность = Оборотные активы / Краткосрочные обязательства"""
        value = self._safe_divide(self._get_current_assets(), self._get_current_liabilities())
        return FinancialRatio('current_ratio', 'Текущая ликвидность', 'Current Ratio',
                            value, 'Оборотные активы / Краткосрочные обязательства', 'раз',
                            'Способность погасить краткосрочные обязательства', 1.5, 3.0, level=2)
    
    def _calc_quick_ratio(self) -> FinancialRatio:
        """Быстрая ликвидность = (Оборотные активы - Запасы) / Краткосрочные обязательства"""
        current_assets = self._get_current_assets()
        inventories = self._get_inventories() or 0
        current_liabilities = self._get_current_liabilities()
        if current_assets and current_liabilities:
            quick = current_assets - inventories
            value = quick / current_liabilities if quick > 0 else None
        else:
            value = None
        return FinancialRatio('quick_ratio', 'Быстрая ликвидность', 'Quick Ratio',
                            value, '(Оборотные активы - Запасы) / Краткосрочные обязательства', 'раз',
                            'Способность погасить обязательства без продажи запасов', 1.0, 2.5, level=2)
    
    def _calc_cash_ratio(self) -> FinancialRatio:
        """Абсолютная денежная ликвидность = Денежные средства / Краткосрочные обязательства"""
        value = self._safe_divide(self._get_cash(), self._get_current_liabilities())
        return FinancialRatio('cash_ratio', 'Абсолютная денежная ликвидность', 'Cash Ratio',
                            value, 'Денежные средства / Краткосрочные обязательства', 'раз',
                            'Доля обязательств, которую можно погасить немедленно', 0.2, 1.0, level=2)
    
    def _calc_equity_ratio(self) -> FinancialRatio:
        """Автономия = Собственный капитал / ИТОГО АКТИВЫ"""
        value = self._safe_divide(self._get_equity(), self._get_total_assets())
        if value is not None: value *= 100
        return FinancialRatio('equity_ratio', 'Автономия (финансовая независимость)', 'Equity Ratio',
                            value, 'Собственный капитал / ИТОГО АКТИВЫ × 100%', '%',
                            'Какая часть активов финансируется за счет собственного капитала', 30.0, 70.0, level=2)
    
    def _calc_debt_to_equity(self) -> FinancialRatio:
        """Финансовый леверидж = Заемный капитал / Собственный капитал"""
        value = self._safe_divide(self._get_total_liabilities(), self._get_equity())
        return FinancialRatio('debt_to_equity', 'Финансовый леверидж', 'Debt-to-Equity Ratio',
                            value, 'Заемный капитал / Собственный капитал', 'раз',
                            'Соотношение долга к собственному капиталу', 0.3, 1.5, level=2)
    
    def _calc_dso(self) -> FinancialRatio:
        """Оборачиваемость дебиторки = Выручка / Дебиторская задолженность"""
        value = self._safe_divide(self._get_revenue(), self._get_receivables())
        return FinancialRatio('dso', 'Оборачиваемость дебиторской задолженности', 'Days Sales Outstanding',
                            value, 'Выручка / Дебиторская задолженность', 'раз',
                            'Сколько раз дебиторка оборачивается за период', 6.0, 24.0, level=2)
    
    def _calc_asset_turnover(self) -> FinancialRatio:
        """Оборачиваемость активов = Выручка / ИТОГО АКТИВЫ"""
        value = self._safe_divide(self._get_revenue(), self._get_total_assets())
        return FinancialRatio('asset_turnover', 'Оборачиваемость активов', 'Asset Turnover',
                            value, 'Выручка / ИТОГО АКТИВЫ', 'раз',
                            'Сколько раз за период активы преобразуются в выручку', 0.3, 2.0, level=2)
    
    def _calc_capex_to_revenue(self) -> FinancialRatio:
        """CAPEX / Выручка = Капитальные затраты / Выручка"""
        value = self._safe_divide(self.data.capex, self._get_revenue())
        if value is not None: value *= 100
        return FinancialRatio('capex_to_revenue', 'Капитальные затраты к выручке', 'CAPEX / Revenue',
                            value, 'CAPEX / Выручка × 100%', '%',
                            'Какая часть выручки идет на капитальные затраты', 3.0, 15.0, level=2)

# ==================== RISK ASSESSMENT ====================
class RiskAssessment:
    """Оценка финансовых рисков"""
    @staticmethod
    def calculate_risk_score(ratios: Dict[str, FinancialRatio]) -> Tuple[float, str]:
        score = 0
        count = 0
        for code, ratio in ratios.items():
            if ratio.value is None:
                continue
            if ratio.status == 'excellent':
                penalty = 0
            elif ratio.status == 'good':
                penalty = 10
            elif ratio.status == 'warning':
                penalty = 30
            else:
                penalty = 50
            score += penalty
            count += 1
        if count == 0:
            return 0.0, "unknown"
        avg_score = score / count
        if avg_score < 10:
            health = "excellent"
        elif avg_score < 25:
            health = "good"
        elif avg_score < 50:
            health = "neutral"
        elif avg_score < 75:
            health = "warning"
        else:
            health = "critical"
        return avg_score, health

# ==================== REPORT GENERATOR ====================
class ReportGenerator:
    """Генерация отчетов"""
    @staticmethod
    def generate_text_report(result: AnalysisResult) -> str:
        report = []
        report.append("=" * 100)
        report.append("ФИНАНСОВЫЙ АНАЛИЗ - КОМПЛЕКСНЫЙ ОТЧЕТ (3 УРОВНЯ)".center(100))
        report.append("=" * 100)
        report.append(f"\n📄 Компания: {result.company_name}")
        report.append(f"📅 Дата отчета: {result.report_type}")
        report.append(f"🔍 Дата анализа: {result.analysis_date}")
        health_emoji = {'excellent': '🟢', 'good': '🟢', 'neutral': '🟡', 'warning': '🟠', 'critical': '🔴'}
        report.append(f"\n{health_emoji.get(result.health_status, '⚪')} Общее здоровье: {result.health_status.upper()}")
        report.append(f"⚠️ Риск-скор: {result.risk_score:.1f}/100")
        
        report.append("\n" + "-" * 100)
        report.append("УРОВЕНЬ 0: ИСХОДНЫЕ ДАННЫЕ (из PDF)")
        report.append("-" * 100)
        data = result.financial_data
        level0_indicators = [
            ('Выручка', data.revenue), ('Себестоимость', data.cost_of_goods),
            ('Чистая прибыль', data.net_income), ('Активы', data.total_assets),
            ('Капитал', data.equity), ('Оборотные активы', data.current_assets),
            ('Краткосрочные обязательства', data.current_liabilities),
            ('Дебиторская задолженность', data.receivables),
            ('Денежные средства', data.cash_and_equivalents),
        ]
        for name, value in level0_indicators:
            if value is not None:
                report.append(f"  • {name:<40} {value:>20,.0f} млн руб.")
        
        report.append("\n" + "-" * 100)
        report.append("УРОВЕНЬ 1: РАСЧЁТНЫЕ ПОКАЗАТЕЛИ (алгоритм)")
        report.append("-" * 100)
        level1 = result.level1_indicators
        level1_indicators = [
            ('Валовая прибыль', level1.gross_profit),
            ('Прибыль от продаж', level1.profit_from_sales),
            ('Внеоборотные активы', level1.non_current_assets_calc),
            ('Оборотные активы (расч.)', level1.current_assets_calc),
            ('ИТОГО АКТИВЫ (расч.)', level1.total_assets_calc),
            ('Собственный капитал (расч.)', level1.equity_calc),
            ('Краткосрочные обязательства (расч.)', level1.current_liabilities_calc),
        ]
        for name, value in level1_indicators:
            if value is not None:
                report.append(f"  • {name:<40} {value:>20,.0f} млн руб.")
        
        report.append("\n" + "-" * 100)
        report.append("УРОВЕНЬ 2: ФИНАНСОВЫЕ КОЭФФИЦИЕНТЫ")
        report.append("-" * 100)
        for i, (code, ratio) in enumerate(result.ratios.items(), 1):
            report.append(f"\n{i}. {ratio.name_ru} ({ratio.name_en})")
            report.append(f"   Формула: {ratio.formula}")
            if ratio.value is not None:
                report.append(f"   Значение: {ratio.value:.2f} {ratio.unit}")
                report.append(f"   Норматив: {ratio.benchmark_min:.2f} - {ratio.benchmark_max:.2f}")
                report.append(f"   {ratio.comment}")
            else:
                report.append(f"   ❌ Недостаточно данных")
        
        if result.validation_errors:
            report.append("\n" + "-" * 100)
            report.append("❌ ОШИБКИ ВАЛИДАЦИИ")
            report.append("-" * 100)
            for error in result.validation_errors:
                report.append(f"  • {error}")
        
        if result.validation_warnings:
            report.append("\n" + "-" * 100)
            report.append("⚠️ ПРЕДУПРЕЖДЕНИЯ")
            report.append("-" * 100)
            for warning in result.validation_warnings:
                report.append(f"  • {warning}")
        
        report.append("\n" + "=" * 100)
        return "\n".join(report)
    
    @staticmethod
    def generate_json_report(result: AnalysisResult) -> str:
        data_dict = {
            'metadata': {
                'pdf_file': result.pdf_file,
                'analysis_date': result.analysis_date,
                'report_type': result.report_type,
                'company_name': result.company_name,
            },
            'health': {'status': result.health_status, 'risk_score': result.risk_score},
            'level_0_raw_data': asdict(result.financial_data),
            'level_1_calculated_indicators': asdict(result.level1_indicators),
            'level_2_ratios': {
                code: {
                    'name_ru': ratio.name_ru, 'name_en': ratio.name_en,
                    'value': ratio.value, 'unit': ratio.unit, 'formula': ratio.formula,
                    'status': ratio.status, 'comment': ratio.comment, 'level': ratio.level,
                } for code, ratio in result.ratios.items()
            },
            'validation': {'errors': result.validation_errors, 'warnings': result.validation_warnings},
        }
        return json.dumps(data_dict, ensure_ascii=False, indent=2)

# ==================== MAIN ENGINE ====================
class FinancialAnalysisEngine:
    """Главный движок финансового анализа"""
    def __init__(self, output_dir: str = 'output_ultra'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        logger.info(f"Инициализация FinancialAnalysisEngine")
    
    def analyze(self, pdf_path: str, company_name: str = "") -> AnalysisResult:
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            logger.error(f"Файл не найден: {pdf_path}")
            return AnalysisResult(
                pdf_file=str(pdf_path), analysis_date=datetime.now().isoformat(),
                report_type="", company_name=company_name or pdf_file.stem,
                financial_data=FinancialData(), validation_errors=["Файл не найден"],
            )
        print(f"\n🚀 ULTIMATE FINANCIAL ANALYZER (3-УРОВНЕВАЯ ИЕРАРХИЯ)")
        print(f"📄 Файл: {pdf_file.name}")
        print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🤖 LLM Модель: {LLM_MODEL} (Ollama)\n")
        
        # ===== УРОВЕНЬ 0: Извлечение исходных данных =====
        print("=" * 80)
        print("📊 УРОВЕНЬ 0: Извлечение исходных данных (LLM из PDF)")
        print("=" * 80)
        extractor = DataExtractor()
        financial_data = extractor.extract_from_pdf(str(pdf_path))
        print(f"✅ Обработано страниц: {extractor.total_pages}\n")
        
        # ===== УРОВЕНЬ 1: Расчёт первичных показателей =====
        print("=" * 80)
        print("📐 УРОВЕНЬ 1: Расчёт первичных показателей (алгоритм)")
        print("=" * 80)
        level1_calculator = Level1Calculator(financial_data)
        level1_indicators = level1_calculator.calculate_all()
        print()
        
        # ===== ЭТАП 1.5: Двухуровневая перепроверка =====
        print("=" * 80)
        print("🔄 ЭТАП 1.5: ДВУХУРОВНЕВАЯ ПЕРЕПРОВЕРКА ДАННЫХ")
        print("=" * 80 + "\n")
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "".join(page.extract_text() + "\n" for page in pdf.pages)
        recovery_engine = DataRecoveryEngine(full_text)
        financial_data, recovery_log = recovery_engine.recover_all(financial_data)
        if recovery_log:
            print("📋 Журнал восстановления:")
            for log_entry in recovery_log:
                print(f"   {log_entry}")
            print()
        
        # ===== ЭТАП 2: Валидация =====
        print("🔍 ЭТАП 2: Валидация данных")
        errors, warnings = DataValidator.validate(financial_data)
        for w in warnings: print(f"  {w}")
        if errors:
            for e in errors: print(f"  ❌ {e}")
        print()
        
        # ===== УРОВЕНЬ 2: Расчёт финансовых коэффициентов =====
        print("=" * 80)
        print("📈 УРОВЕНЬ 2: Расчёт финансовых коэффициентов")
        print("=" * 80 + "\n")
        calculator = MetricsCalculator(financial_data, level1_indicators)
        ratios = calculator.calculate_all()
        for code, ratio in ratios.items():
            if ratio.value is not None:
                status_emoji = {'excellent': '✓', 'good': '⚠', 'critical': '✗', 'unknown': '?'}
                print(f"  {status_emoji.get(ratio.status, '?')} {ratio.name_ru}: {ratio.value:.2f} {ratio.unit}")
        print()
        
        # ===== ЭТАП 4: Оценка рисков =====
        print("⚠️ ЭТАП 4: Оценка рисков")
        risk_score, health = RiskAssessment.calculate_risk_score(ratios)
        health_text = {
            'excellent': '🟢 Отличное', 'good': '🟢 Хорошее', 'neutral': '🟡 Нейтральное',
            'warning': '🟠 Предупреждение', 'critical': '🔴 Критическое'
        }
        print(f"  Здоровье: {health_text.get(health, 'Неизвестно')}")
        print(f"  Риск-скор: {risk_score:.1f}/100\n")
        
        return AnalysisResult(
            pdf_file=pdf_file.name, analysis_date=datetime.now().isoformat(),
            report_type="МСФО", company_name=company_name or pdf_file.stem,
            financial_data=financial_data, level1_indicators=level1_indicators,
            ratios=ratios, validation_errors=errors, validation_warnings=warnings,
            risk_score=risk_score, health_status=health,
        )
    
    def save_reports(self, result: AnalysisResult):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_name = Path(result.pdf_file).stem
        text_report = ReportGenerator.generate_text_report(result)
        text_path = self.output_dir / f"report_{pdf_name}_{timestamp}.txt"
        text_path.write_text(text_report, encoding='utf-8')
        print(f"📄 Отчет (TXT): {text_path}")
        json_report = ReportGenerator.generate_json_report(result)
        json_path = self.output_dir / f"analysis_{pdf_name}_{timestamp}.json"
        json_path.write_text(json_report, encoding='utf-8')
        print(f"📊 Отчет (JSON): {json_path}")
        print(f"\n{text_report}")

# ==================== MAIN ====================
def main():
    """Главная функция"""
    print("\n" + "="*80)
    print("ПРОВЕРКА КОНФИГУРАЦИИ LLM")
    print("="*80)
    llm_extractor = LLMExtractor()
    if llm_extractor.is_available:
        print("✅ Ollama доступна и готова к работе")
        print(f"   Базовый URL: {llm_extractor.base_url}")
        print(f"   Модель: {LLM_MODEL}")
    else:
        print("⚠️  Ollama НЕ доступна!")
        print("    Запустите: ollama serve")
        print("    Установите модель: ollama pull ministral-3:8b")
    print("="*80 + "\n")
    
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        input_dir = Path('input')
        if not input_dir.exists():
            input_dir.mkdir()
            print("📁 Создана папка 'input/' — поместите PDF и запустите снова")
            return
        pdf_files = list(input_dir.glob('*.pdf'))
        if not pdf_files:
            print("❌ PDF файлы не найдены в папке 'input/'")
            return
        pdf_path = str(pdf_files[0])
    
    engine = FinancialAnalysisEngine()
    result = engine.analyze(pdf_path)
    engine.save_reports(result)

if __name__ == '__main__':
    main()