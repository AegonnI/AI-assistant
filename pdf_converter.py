# -*- coding: utf-8 -*-
"""
📄 PDF_CONVERTER v5.0 — Модуль для извлечения текста из финансовых отчётов МСФО
================================================================================
Исправления в этой версии:
✅ Fixed: Извлечение текста со страниц с таблицами (страницы 3-6, 114)
✅ Fixed: PageExtractionMethod enum mapping
✅ Added: Ollama LLM для структурирования проблемных страниц
✅ Added: NumberNormalizer для нормализации финансовых чисел
✅ Added: PageRegistry для отслеживания статуса каждой страницы
✅ Added: Hybrid OCR + LLM для сканов и проблемных страниц
✅ Added: Debug mode с сохранением артефактов
✅ Added: Валидация полноты извлечения всех страниц
"""

import logging
import os
import re
import sys
import hashlib
import json
import base64
import io
from pathlib import Path
from typing import Dict, Optional, Any, Tuple, List, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('pdf_converter.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ==================== ПРОВЕРКА БИБЛИОТЕК ====================
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError: 
    HAS_PDFPLUMBER = False
    logger.warning("⚠️ pdfplumber не установлен: pip install pdfplumber")

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError: 
    HAS_PYMUPDF = False
    logger.warning("⚠️ PyMuPDF не установлен: pip install pymupdf")

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError: 
    HAS_PYPDF2 = False
    logger.warning("⚠️ PyPDF2 не установлен: pip install pypdf2")

try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    # Заглушка для аннотаций типов, чтобы класс HybridOCREngine мог определиться даже без OCR
    from typing import Any as Image  # type: ignore
    logger.warning("⚠️ OCR не установлен: pip install pytesseract pdf2image pillow")

# Путь к tesseract.exe (если задан — используется в первую очередь; на Windows часто не в PATH)
# По умолчанию на Windows подставляем стандартную установку в Program Files (venv не видит PATH установки)
_default_tesseract = (Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe") if sys.platform == "win32" else None)
TESSERACT_CMD_OVERRIDE: Optional[str] = str(_default_tesseract) if (_default_tesseract and _default_tesseract.exists()) else None

# На Windows Tesseract часто не в PATH — ищем tesseract.exe и задаём путь для pytesseract
def _configure_tesseract_windows() -> None:
    """Выставляет pytesseract.pytesseract.tesseract_cmd, если Tesseract установлен в типичные места."""
    if not HAS_OCR:
        return
    if TESSERACT_CMD_OVERRIDE and Path(TESSERACT_CMD_OVERRIDE).exists():
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_OVERRIDE
        logger.info(f"Tesseract задан вручную: {TESSERACT_CMD_OVERRIDE}")
        return
    if sys.platform != "win32":
        return
    try:
        # Уже работает (есть в PATH)?
        pytesseract.get_tesseract_version()
        return
    except Exception:
        pass
    # Типичные пути установки Tesseract на Windows
    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for exe in candidates:
        if not exe:
            continue
        if exe and exe.exists():
            pytesseract.pytesseract.tesseract_cmd = str(exe)
            try:
                pytesseract.get_tesseract_version()
                logger.info(f"Tesseract найден: {exe}")
                return
            except Exception:
                continue
    logger.warning(
        "Tesseract не найден в PATH и в стандартных папках. "
        "Установите Tesseract-OCR и добавьте папку с tesseract.exe в PATH, "
        "или укажите путь в pdf_converter: pytesseract.pytesseract.tesseract_cmd = r'C:\\...\\tesseract.exe'"
    )

if HAS_OCR:
    _configure_tesseract_windows()

# Ollama для локальных LLM
try:
    import requests
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    logger.info("ℹ️ requests не установлен — Ollama будет отключена: pip install requests")


# ==================== КОНСТАНТЫ ====================
SECTION_KEYWORDS = {
    'INCOME_STATEMENT': [
        'отчет о прибылях', 'выручка', 'прибыль за год', 'income statement', 
        'операционная прибыль', 'отчет о прибылях или убытках'
    ],
    'BALANCE_SHEET': [
        'отчет о финансовом положении', 'баланс', 'активы', 'пассивы', 
        'balance sheet', 'собственный капитал', 'финансовом положении'
    ],
    'CASH_FLOW': [
        'движение денежных средств', 'денежные потоки', 'cash flow', 
        'операционная деятельность', 'инвестиционной деятельности'
    ],
    'EQUITY': [
        'изменения в капитале', 'изменения собственного капитала', 
        'нераспределенная прибыль', 'отчет об изменениях'
    ],
    'NOTES': [
        'примечания', 'пояснительные примечания', 'учетная политика',
        'примечания к обобщенной'
    ],
}

TOTAL_KEYWORDS = (
    'итого', 'всего', 'прибыль за год', 'чистая прибыль', 'баланс', 
    'совокупный доход', 'итого операционные'
)

NEGATIVE_PATTERNS = [
    r'^\s*\(\s*([\d\s,.]+)\s*\)\s*$',
    r'^[\[\{]([\d\s,.]+)[\]\}]$'
]

# Конфигурация Ollama
OLLAMA_CONFIG = {
    'base_url': 'http://localhost:11434',
    'model': 'qwen3.5:4b',  # Или qwen2.5:3b для скорости
    # Таймаут HTTP-запроса к Ollama в секундах
    'timeout': 600,
    'max_pages': 10,  # Максимум страниц для обработки через LLM
    'temperature': 0.1,  # Низкая температура для точности чисел
}


# ==================== 1. НОРМАЛИЗАЦИЯ ЧИСЕЛ ====================
class NumberNormalizer:
    """Очистка и нормализация чисел для финансовых отчётов"""
    
    @staticmethod
    def normalize(text: str, scale_large: bool = True) -> Optional[float]:
        """
        Нормализует текст в число с обработкой финансовых форматов.
        
        Args:
            text: Исходный текст числа
            scale_large: Если True, делит числа >1 млрд на 1 млн
        
        Returns:
            float или None
        """
        if not text: 
            return None
        text = str(text).strip()
        
        # Скобки/квадратные скобки = отрицательные числа
        for pattern in NEGATIVE_PATTERNS:
            match = re.match(pattern, text)
            if match:
                text = '-' + match.group(1)
                break
        
        # Удаляем пробелы внутри чисел (779 945 → 779945)
        text = re.sub(r'(\d)\s+(\d{3})', r'\1\2', text)
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
        
        # Запятые → точки (русский формат)
        text = text.replace(',', '.')
        
        # Удаляем лишние символы
        text = re.sub(r'[^\d.\-]', '', text)
        
        if not text or text in ('-', '.', ''): 
            return None
        
        try:
            value = float(text)
            if scale_large and abs(value) > 1_000_000_000:
                value = value / 1_000_000
            return value
        except ValueError:
            return None
    
    @staticmethod
    def format_for_display(value: Optional[float], decimals: int = 0) -> str:
        """Форматирует число для вывода с разделителями тысяч"""
        if value is None:
            return "–"
        if decimals == 0:
            return f"{int(round(value)):,}".replace(',', ' ')
        return f"{value:,.{decimals}f}".replace(',', ' ')
    
    @staticmethod
    def validate_balance_check(assets: float, liabilities: float, equity: float) -> bool:
        """Проверяет баланс: Активы = Пассивы + Капитал"""
        if assets == 0:
            return True
        diff = abs(assets - (liabilities + equity)) / max(assets, 1)
        return diff < 0.01  # Допуск 1%


# ==================== 2. РЕЕСТР СТРАНИЦ ====================
class PageExtractionMethod(Enum):
    NONE = "none"
    PDFPLUMBER = "pdfplumber"
    PYMUPDF = "pymupdf"
    PYPDF2 = "pypdf2"
    OCR_TESSERACT = "ocr_tesseract"
    OCR_LLM_HYBRID = "ocr_llm_hybrid"
    LLM_STRUCTURE = "llm_structure"
    FALLBACK = "fallback"


@dataclass
class PageStatus:
    """Статус извлечения для одной страницы"""
    number: int
    extracted: bool = False
    method: PageExtractionMethod = PageExtractionMethod.NONE
    char_count: int = 0
    table_count: int = 0
    confidence: float = 0.0
    checksum: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    raw_text: Optional[str] = None
    ocr_applied: bool = False
    llm_applied: bool = False
    # Метрики числового покрытия (для диагностики качества таблиц)
    numeric_tokens_total: int = 0
    numeric_tokens_in_tables: int = 0
    table_coverage: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'page': self.number,
            'extracted': self.extracted,
            'method': self.method.value,
            'char_count': self.char_count,
            'table_count': self.table_count,
            'confidence': self.confidence,
            'checksum': self.checksum,
            'errors': self.errors,
            'ocr_applied': self.ocr_applied,
            'llm_applied': self.llm_applied,
            'numeric_tokens_total': self.numeric_tokens_total,
            'numeric_tokens_in_tables': self.numeric_tokens_in_tables,
            'table_coverage': self.table_coverage
        }


class PageRegistry:
    """Реестр для отслеживания статуса извлечения каждой страницы"""
    
    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.pages: Dict[int, PageStatus] = {
            i: PageStatus(number=i) for i in range(1, total_pages + 1)
        }
    
    def update(self, page_num: int, **kwargs):
        """Обновляет статус страницы"""
        if page_num in self.pages:
            for key, value in kwargs.items():
                if hasattr(self.pages[page_num], key):
                    setattr(self.pages[page_num], key, value)
    
    def get_missing_pages(self) -> List[int]:
        """Возвращает номера страниц, которые не были извлечены"""
        return [p.number for p in self.pages.values() if not p.extracted]
    
    def get_low_confidence_pages(self, threshold: float = 0.7) -> List[int]:
        """Возвращает страницы с низкой уверенностью извлечения"""
        return [p.number for p in self.pages.values() 
                if p.extracted and p.confidence < threshold]
    
    def get_summary(self) -> Dict[str, Any]:
        """Возвращает сводную статистику"""
        extracted = [p for p in self.pages.values() if p.extracted]
        return {
            'total_pages': self.total_pages,
            'extracted_pages': len(extracted),
            'missing_pages': self.get_missing_pages(),
            'low_confidence_pages': self.get_low_confidence_pages(),
            'coverage_percent': round(len(extracted) / self.total_pages * 100, 1) if self.total_pages > 0 else 0,
            'methods_used': list(set(p.method.value for p in extracted if p.method != PageExtractionMethod.NONE)),
            'ocr_pages': sum(1 for p in extracted if p.ocr_applied),
            'llm_pages': sum(1 for p in extracted if p.llm_applied),
            'avg_confidence': round(sum(p.confidence for p in extracted) / len(extracted), 2) if extracted else 0,
            'total_chars': sum(p.char_count for p in extracted),
            'total_tables': sum(p.table_count for p in extracted),
            'total_numeric_tokens': sum(p.numeric_tokens_total for p in extracted),
            'total_numeric_in_tables': sum(p.numeric_tokens_in_tables for p in extracted)
        }
    
    def generate_report(self) -> str:
        """Генерирует текстовый отчёт о покрытии"""
        summary = self.get_summary()
        lines = [
            "=" * 60,
            "📊 ОТЧЁТ ОБ ИЗВЛЕЧЕНИИ СТРАНИЦ",
            "=" * 60,
            f"Всего страниц: {summary['total_pages']}",
            f"Извлечено: {summary['extracted_pages']} ({summary['coverage_percent']}%)",
            f"Пропущено: {len(summary['missing_pages'])}",
            f"Низкая уверенность: {len(summary['low_confidence_pages'])}",
            f"OCR применён: {summary['ocr_pages']} страниц",
            f"LLM применён: {summary['llm_pages']} страниц",
            f"Методы: {', '.join(summary['methods_used']) or 'нет данных'}",
            f"Средняя уверенность: {summary['avg_confidence']}",
            f"Всего символов: {summary['total_chars']:,}",
            f"Всего таблиц: {summary['total_tables']}",
        ]
        if summary['missing_pages']:
            lines.append(f"\n⚠️ Пропущенные страницы: {summary['missing_pages'][:20]}")
            if len(summary['missing_pages']) > 20:
                lines.append(f"   ... и ещё {len(summary['missing_pages']) - 20}")
        if summary['low_confidence_pages']:
            lines.append(f"⚠️ Низкая уверенность: {summary['low_confidence_pages'][:20]}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ==================== 3. ДЕТЕКЦИЯ ТИПА PDF ====================
def detect_pdf_type(pdf_path: str, sample_strategy: str = 'smart') -> Tuple[str, float, Dict]:
    """
    Определяет тип PDF с улучшенной стратегией выборки.
    """
    details = {'sampled_pages': [], 'avg_chars': 0, 'has_images': False}
    
    try:
        if HAS_PYMUPDF:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            if sample_strategy == 'smart' and total_pages > 5:
                sample_indices = [0, total_pages // 2, total_pages - 1]
            elif sample_strategy == 'all':
                sample_indices = range(total_pages)
            else:
                sample_indices = range(min(5, total_pages))
            
            char_counts = []
            for idx in sample_indices:
                page = doc[idx]
                text = page.get_text()
                char_counts.append(len(text.strip()))
                details['sampled_pages'].append({
                    'page_num': idx + 1,
                    'char_count': len(text.strip()),
                    'has_text': bool(text.strip())
                })
                if page.get_images():
                    details['has_images'] = True
            doc.close()
            
            avg_chars = sum(char_counts) / len(char_counts) if char_counts else 0
            details['avg_chars'] = avg_chars
            
            if avg_chars < 50:
                return "scanned", 0.92, details
            elif avg_chars < 200:
                return "mixed", 0.75, details
            else:
                return "text", 0.95, details
                
        elif HAS_PDFPLUMBER:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                sample_indices = [0, total_pages // 2, total_pages - 1] if total_pages > 5 else range(min(5, total_pages))
                
                char_counts = []
                for idx in sample_indices:
                    page = pdf.pages[idx]
                    text = page.extract_text()
                    char_counts.append(len(text.strip()) if text else 0)
                
                avg_chars = sum(char_counts) / len(char_counts) if char_counts else 0
                details['avg_chars'] = avg_chars
                
                if avg_chars < 50:
                    return "scanned", 0.90, details
                elif avg_chars < 200:
                    return "mixed", 0.70, details
                else:
                    return "text", 0.93, details
                    
        return "unknown", 0.5, details
        
    except Exception as e:
        logger.warning(f"⚠️ Ошибка детекции типа PDF: {e}")
        return "unknown", 0.5, details


# ==================== 4. OLLAMA ENGINE (ЛОКАЛЬНЫЙ LLM) ====================
class OllamaEngine:
    """Движок для работы с локальными LLM через Ollama"""
    
    def __init__(self, model_name: str = None, base_url: str = None):
        self.model_name = model_name or OLLAMA_CONFIG['model']
        self.base_url = base_url or OLLAMA_CONFIG['base_url']
        self.timeout = OLLAMA_CONFIG['timeout']
        self.pages_processed = 0
        self.max_pages = OLLAMA_CONFIG['max_pages']
        
        # Проверка доступности
        if self.is_available():
            logger.info(f"✅ Ollama доступен на {self.base_url} (модель: {self.model_name})")
        else:
            logger.warning("⚠️ Ollama не найден. Убедитесь, что сервис запущен: ollama serve")
    
    def is_available(self) -> bool:
        """Проверяет доступность Ollama"""
        if not HAS_OLLAMA:
            return False
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def structure_financial_text(self, ocr_text: str, page_num: int) -> Tuple[str, bool]:
        """
        Структурирует OCR-текст через локальную LLM.
        КРИТИЧЕСКИ ВАЖНО: Запрет на изменение чисел.
        """
        if not self.is_available():
            return ocr_text, False
        
        if self.pages_processed >= self.max_pages:
            logger.warning(f"⚠️ Достигнут лимит LLM-страниц ({self.max_pages})")
            return ocr_text, False
        
        # Промпт с жёсткими ограничениями для финансов
        prompt = f"""Ты — ассистент для обработки финансовых отчётов МСФО.
ЗАДАЧА: Исправь структуру текста после OCR, но НЕ МЕНЯЙ ЧИСЛА.

ПРАВИЛА (СТРОГО):
1. ЗАПРЕЩЕНО изменять любые цифры, суммы, даты, проценты.
2. ЗАПРЕЩЕНО выдумывать данные, которых нет в исходном тексте.
3. Исправь очевидные ошибки распознавания букв (O→0, l→1, I→1).
4. Сохрани структуру таблиц (добавь маркеры [ТАБЛИЦА]).
5. Добавь маркеры разделов [РАЗДЕЛ: ...] если видишь заголовки.
6. Если текст нечитаем — оставь как есть.

ИСХОДНЫЙ ТЕКСТ (страница {page_num}):
{ocr_text[:3000]}

ОТВЕТ (только исправленный текст, без пояснений):"""

        try:
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": OLLAMA_CONFIG['temperature'],
                    "top_p": 0.5,
                    "num_predict": 2000
                }
            }
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                self.pages_processed += 1
                return result.get('response', ocr_text), True
            else:
                logger.warning(f"⚠️ Ollama вернул ошибку: {response.status_code}")
                return ocr_text, False
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка запроса к Ollama (страница {page_num}): {e}")
            return ocr_text, False
    
    def get_stats(self) -> Dict:
        """Возвращает статистику использования LLM"""
        return {
            'pages_processed': self.pages_processed,
            'max_pages': self.max_pages,
            'model': self.model_name,
            'available': self.is_available()
        }


# ==================== 5. HYBRID OCR ENGINE ====================
class HybridOCREngine:
    """Гибридный OCR: Tesseract + Ollama для структурирования"""
    
    def __init__(self, ollama_engine: Optional[OllamaEngine] = None):
        self.ollama_engine = ollama_engine
        self.ocr_stats = {'pages_processed': 0, 'llm_enhanced': 0, 'errors': 0}
    
    def process_page(self, image, page_num: int, 
                     use_llm: bool = True) -> Tuple[str, Dict]:
        """Обрабатывает страницу через OCR с опциональным LLM-улучшением"""
        stats = {
            'page': page_num,
            'ocr_applied': True,
            'llm_applied': False,
            'char_count': 0,
            'confidence': 0.0
        }
        
        if not HAS_OCR:
            return "", stats
        
        try:
            # Шаг 1: Tesseract OCR (сначала PSM 6 — блок текста)
            ocr_text = pytesseract.image_to_string(image, lang='rus+eng', config=r'--oem 3 --psm 6')
            # Если пусто — пробуем другие PSM (таблицы, один блок, сырые строки)
            if not (ocr_text or '').strip():
                for psm in (3, 11, 4, 5, 13):
                    ocr_text = pytesseract.image_to_string(image, lang='rus+eng', config=f'--oem 3 --psm {psm}')
                    if (ocr_text or '').strip():
                        break
                if not (ocr_text or '').strip():
                    ocr_text = pytesseract.image_to_string(image, lang='eng', config=r'--oem 3 --psm 6')
            
            # Шаг 2: Пост-обработка OCR
            ocr_text = self._postprocess_ocr(ocr_text or '')
            stats['char_count'] = len(ocr_text)
            stats['confidence'] = 0.7 if len(ocr_text) > 100 else 0.5
            
            # Шаг 3: LLM только если OCR что-то нашёл (иначе не вызываем и не затираем)
            if (ocr_text or '').strip() and use_llm and self.ollama_engine and self.ollama_engine.is_available():
                structured_text, success = self.ollama_engine.structure_financial_text(ocr_text, page_num)
                if success and (structured_text or '').strip():
                    ocr_text = structured_text
                    stats['llm_applied'] = True
                    stats['confidence'] = 0.85
                    self.ocr_stats['llm_enhanced'] += 1
                    logger.info(f"🤖 LLM улучшил страницу {page_num}")
            
            self.ocr_stats['pages_processed'] += 1
            return ocr_text, stats
            
        except Exception as e:
            logger.error(f"❌ OCR ошибка (страница {page_num}): {e}")
            self.ocr_stats['errors'] += 1
            return "", stats
    
    def _postprocess_ocr(self, text: str) -> str:
        """Базовая пост-обработка OCR без LLM"""
        text = text.replace('O', '0').replace('l', '1').replace('I', '1')
        text = re.sub(r'(\d)\s+(\d{3})', r'\1\2', text)
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _preprocess_image_for_ocr(self, image) -> Any:
        """Усиление контраста и приведение к одному каналу для сложных страниц."""
        try:
            from PIL import ImageOps, ImageEnhance
            img = image.convert("L")
            img = ImageOps.autocontrast(img, cutoff=2)
            enh = ImageEnhance.Contrast(img)
            img = enh.enhance(1.5)
            return img.convert("RGB")
        except Exception:
            return image
    
    def process_pages(self, pdf_path: str, page_numbers: List[int], 
                      use_llm: bool = True) -> Dict[int, Tuple[str, Dict]]:
        """Обрабатывает указанные страницы через OCR. Рендер страниц через PyMuPDF (без poppler)."""
        results = {}
        
        if not HAS_OCR:
            logger.warning("⚠️ OCR не доступен — пропускаем обработку")
            return results
        
        # Рендер страниц в картинки: предпочитаем PyMuPDF (не требует poppler на Windows)
        page_images: Dict[int, Any] = {}
        if HAS_PYMUPDF:
            try:
                doc = fitz.open(pdf_path)
                for page_num in page_numbers:
                    if 1 <= page_num <= len(doc):
                        page = doc[page_num - 1]
                        pix = page.get_pixmap(dpi=400, alpha=False)
                        img_bytes = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        page_images[page_num] = img
                doc.close()
                logger.info(f"📷 Рендер через PyMuPDF: {len(page_images)} страниц для OCR")
            except Exception as e:
                logger.warning(f"⚠️ Рендер через PyMuPDF не удался: {e}")
        if not page_images and HAS_OCR:
            try:
                images = convert_from_path(pdf_path, dpi=300)
                for i, page_num in enumerate(page_numbers):
                    if page_num <= len(images):
                        page_images[page_num] = images[page_num - 1]
            except Exception as e:
                logger.error(f"❌ pdf2image не удался (нужен poppler?): {e}")
        
        try:
            for page_num in page_numbers:
                image = page_images.get(page_num)
                if image is not None:
                    text, stats = self.process_page(image, page_num, use_llm)
                    results[page_num] = (text, stats)
                    logger.info(f"📷 OCR страница {page_num}: {len(text)} символов, LLM={stats['llm_applied']}")
            
            # Второй проход для страниц с пустым результатом: выше DPI + предобработка
            empty_after_first = [pn for pn in page_numbers if not (results.get(pn) or ("", {}))[0].strip()]
            if empty_after_first and HAS_PYMUPDF:
                logger.info(f"🔄 Второй проход OCR (DPI 600 + предобработка) для страниц: {empty_after_first}")
                try:
                    doc = fitz.open(pdf_path)
                    for page_num in empty_after_first:
                        if 1 <= page_num <= len(doc):
                            page = doc[page_num - 1]
                            pix = page.get_pixmap(dpi=600, alpha=False)
                            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                            img = self._preprocess_image_for_ocr(img)
                            text, stats = self.process_page(img, page_num, use_llm=False)
                            if (text or "").strip():
                                results[page_num] = (text, stats)
                                logger.info(f"📷 OCR (2-й проход) страница {page_num}: {len(text)} символов")
                    doc.close()
                except Exception as e:
                    logger.warning(f"⚠️ Второй проход OCR не удался: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка OCR обработки страниц: {e}")
        
        return results


# ==================== 6. ОСНОВНОЙ КЛАСС PDFConverter ====================
class PDFConverter:
    """
    Универсальный конвертер PDF с поддержкой:
    • Мульти-парсера с fallback-логикой
    • Валидации полноты извлечения
    • Реестра страниц для диагностики
    • Нормализации финансовых чисел
    • OCR + Ollama для сканированных документов
    """
    
    def __init__(self, debug_mode: bool = False, debug_output_dir: str = 'debug',
                 ollama_model: Optional[str] = None, ollama_url: Optional[str] = None):
        self.parsers_available = []
        if HAS_PDFPLUMBER: self.parsers_available.append('pdfplumber')
        if HAS_PYMUPDF: self.parsers_available.append('pymupdf')
        if HAS_PYPDF2: self.parsers_available.append('pypdf2')
        
        logger.info(f"📚 Доступные парсеры: {self.parsers_available}")
        
        # Инициализация Ollama
        self.ollama_engine = OllamaEngine(model_name=ollama_model, base_url=ollama_url)
        
        self.debug_mode = debug_mode
        self.debug_output_dir = Path(debug_output_dir)
        if debug_mode:
            self.debug_output_dir.mkdir(parents=True, exist_ok=True)
        
        self.page_registry: Optional[PageRegistry] = None
        self.is_scanned = False
        self.ocr_pages = 0
        self.llm_pages = 0
        self.parser_used = "none"
        self.extraction_warnings: List[str] = []
        
        # Маппинг парсеров в Enum
        self.parser_to_enum = {
            'pdfplumber': PageExtractionMethod.PDFPLUMBER,
            'pymupdf': PageExtractionMethod.PYMUPDF,
            'pypdf2': PageExtractionMethod.PYPDF2
        }
    
    def extract(self, pdf_path: str, validate: bool = True, 
                return_metadata: bool = True, use_ollama_for_missing: bool = True) -> Union[str, Dict[str, Any]]:
        """
        Полное извлечение текста из PDF с валидацией и диагностикой.
        """
        result = {
            'success': False,
            'text': "",
            'tables': [],
            'metadata': {},
            'diagnostics': {},
            'warnings': []
        }
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            result['warnings'].append(f"Файл не найден: {pdf_path}")
            return result if return_metadata else ""
        
        logger.info(f"📖 Начинаю извлечение из: {pdf_path.name}")
        start_time = datetime.now()
        
        # LAYER 1: Детекция типа и инициализация реестра
        pdf_type, type_confidence, detection_details = detect_pdf_type(str(pdf_path))
        self.is_scanned = (pdf_type == "scanned")
        logger.info(f"📄 Тип PDF: {pdf_type} (уверенность: {type_confidence:.2f})")
        
        total_pages = self._get_total_pages(str(pdf_path))
        self.page_registry = PageRegistry(total_pages)
        logger.info(f"📑 Всего страниц: {total_pages}")
        
        # LAYER 2: Гибридное извлечение с fallback по страницам
        page_results = self._extract_with_fallback(str(pdf_path))
        
        # LAYER 3: OCR + Ollama для проблемных страниц
        missing_pages = self.page_registry.get_missing_pages()
        low_confidence_pages = self.page_registry.get_low_confidence_pages()
        # Дополнительно: страницы, где текст есть, но чисел не обнаружено,
        # и общий объём текста очень маленький — кандидаты на OCR
        low_numeric_pages: List[int] = []
        if self.page_registry:
            for p in self.page_registry.pages.values():
                if p.char_count < 50 and p.numeric_tokens_total == 0:
                    low_numeric_pages.append(p.number)
        problematic_pages = sorted(set(missing_pages + low_confidence_pages + low_numeric_pages))
        
        if problematic_pages and use_ollama_for_missing:
            logger.info(f"🔧 Обработка {len(problematic_pages)} проблемных страниц через OCR+Ollama...")
            logger.info(f"   Страницы: {problematic_pages[:10]}{'...' if len(problematic_pages) > 10 else ''}")
            
            ocr_results = self._process_problematic_pages_with_hybrid_ocr(
                str(pdf_path), problematic_pages
            )
            
            for page_num, (ocr_text, stats) in ocr_results.items():
                if ocr_text.strip():
                    if page_num in page_results:
                        # Заменяем только если OCR дал больше текста
                        if len(ocr_text.strip()) > len(page_results[page_num].get('text', '').strip()):
                            # Пересчитываем числовые метрики для текста после OCR
                            numeric_total = self._count_numeric_tokens_in_text(ocr_text)
                            numeric_in_tables = self._count_numeric_tokens_in_tables(page_results[page_num].get('tables', []))
                            coverage = (numeric_in_tables / numeric_total) if numeric_total > 0 else 0.0

                            page_results[page_num]['text'] = ocr_text
                            page_results[page_num]['method'] = PageExtractionMethod.OCR_LLM_HYBRID if stats['llm_applied'] else PageExtractionMethod.OCR_TESSERACT
                            self.page_registry.update(
                                page_num,
                                extracted=True,
                                method=PageExtractionMethod.OCR_LLM_HYBRID if stats['llm_applied'] else PageExtractionMethod.OCR_TESSERACT,
                                char_count=len(ocr_text),
                                confidence=stats['confidence'],
                                ocr_applied=True,
                                llm_applied=stats['llm_applied'],
                                numeric_tokens_total=numeric_total,
                                numeric_tokens_in_tables=numeric_in_tables,
                                table_coverage=coverage,
                            )
                            if stats['llm_applied']:
                                self.llm_pages += 1
                            self.ocr_pages += 1
                            logger.info(f"✅ Страница {page_num} восстановлена через OCR{' + Ollama' if stats['llm_applied'] else ''}")
                    else:
                        # Страница была полностью пустой до OCR — создаём запись с текстом OCR
                        numeric_total = self._count_numeric_tokens_in_text(ocr_text)
                        numeric_in_tables = 0  # таблиц пока нет
                        coverage = 0.0

                        page_results[page_num] = {
                            'text': ocr_text,
                            'tables': [],
                            'method': PageExtractionMethod.OCR_LLM_HYBRID if stats['llm_applied'] else PageExtractionMethod.OCR_TESSERACT,
                            'numeric_total': numeric_total,
                            'numeric_in_tables': numeric_in_tables,
                            'numeric_coverage': coverage,
                        }
                        self.page_registry.update(
                            page_num,
                            extracted=True,
                            method=PageExtractionMethod.OCR_LLM_HYBRID if stats['llm_applied'] else PageExtractionMethod.OCR_TESSERACT,
                            char_count=len(ocr_text),
                            confidence=stats['confidence'],
                            ocr_applied=True,
                            llm_applied=stats['llm_applied'],
                            numeric_tokens_total=numeric_total,
                            numeric_tokens_in_tables=numeric_in_tables,
                            table_coverage=coverage,
                        )
                        if stats['llm_applied']:
                            self.llm_pages += 1
                        self.ocr_pages += 1
        
        # LAYER 4: Сборка финального текста с форматированием
        full_text_parts = []
        all_tables = []
        current_section = "GENERAL"
        
        for page_num in range(1, total_pages + 1):
            page_data = page_results.get(page_num, {})
            page_text = page_data.get('text', '')
            page_tables = page_data.get('tables', [])
            
            if page_text.strip():
                self.page_registry.update(
                    page_num,
                    extracted=True,
                    char_count=len(page_text),
                    table_count=len(page_tables),
                    confidence=0.9 if len(page_text) > 100 else 0.7,
                    checksum=hashlib.md5(page_text.encode('utf-8')).hexdigest()[:12]
                )
                
                # Определяем раздел
                text_lower = page_text[:1000].lower()
                for section, keywords in SECTION_KEYWORDS.items():
                    if any(kw in text_lower for kw in keywords):
                        current_section = section
                        break
                
                chunk = f"[РАЗДЕЛ: {current_section}] [СТРАНИЦА {page_num}]\n{page_text}\n"
                
                # Добавляем таблицы в Markdown
                for table in page_tables:
                    md_table = self._format_table(table['cells'])
                    if md_table:
                        chunk += f"\n{md_table}\n"
                        all_tables.append(table)
                
                # Нормализация чисел
                chunk = self._normalize_numbers_in_text(chunk)
                full_text_parts.append(chunk)
                
                # Отладка: сохраняем артефакты
                if self.debug_mode:
                    self._save_debug_artifacts(page_num, page_text, page_tables)
            else:
                self.page_registry.update(page_num, errors=["Пустой текст после извлечения"])
                logger.warning(f"⚠️ Страница {page_num}: не извлечён текст")
        
        result['text'] = "\n".join(full_text_parts)
        result['tables'] = all_tables
        result['parser_used'] = self.parser_used
        result['ocr_pages'] = self.ocr_pages
        result['llm_pages'] = self.llm_pages
        
        # LAYER 5: Валидация и диагностика
        if validate and self.page_registry:
            validation_result = self._validate_extraction()
            result['diagnostics'] = {
                'page_registry_summary': self.page_registry.get_summary(),
                'validation_warnings': validation_result,
                'coverage_report': self.page_registry.generate_report()
            }
            result['warnings'].extend(validation_result)
            
            if validation_result:
                logger.warning(f"⚠️ Валидация: {len(validation_result)} предупреждений")
                for w in validation_result[:5]:
                    logger.warning(f"   • {w}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        result['metadata'] = {
            'file_name': pdf_path.name,
            'total_pages': total_pages,
            'extraction_time_sec': round(elapsed, 2),
            'pdf_type': pdf_type,
            'parsers_tried': list(set(
                p.get('method', 'unknown').value if hasattr(p.get('method'), 'value') else str(p.get('method')) 
                for p in page_results.values()
            )),
            'text_length': len(result['text']),
            'tables_found': len(all_tables),
            'ocr_pages': self.ocr_pages,
            'llm_pages': self.llm_pages
        }
        
        result['success'] = True
        logger.info(f"✅ Извлечение завершено за {elapsed:.1f}с | Страниц: {total_pages} | Символов: {len(result['text']):,}")
        
        return result if return_metadata else result['text']
    
    def _get_total_pages(self, pdf_path: str) -> int:
        """Получает общее количество страниц в PDF"""
        try:
            if HAS_PYMUPDF:
                return len(fitz.open(pdf_path))
            elif HAS_PDFPLUMBER:
                with pdfplumber.open(pdf_path) as pdf:
                    return len(pdf.pages)
            elif HAS_PYPDF2:
                with open(pdf_path, 'rb') as f:
                    return len(PyPDF2.PdfReader(f).pages)
        except:
            pass
        return 0
    
    def _extract_with_fallback(self, pdf_path: str) -> Dict[int, Dict]:
        """
        Извлекает текст с fallback-логикой: для каждой страницы
        пробуем все парсеры и берём лучший результат.
        """
        results: Dict[int, Dict] = {}
        total_pages = self._get_total_pages(pdf_path)
        
        for parser_name in self.parsers_available:
            try:
                logger.info(f"🔍 Парсер {parser_name}: извлечение...")
                page_texts, page_tables = self._extract_with_parser(pdf_path, parser_name)
                
                for page_num in range(1, total_pages + 1):
                    text = page_texts.get(page_num, '')
                    tables = page_tables.get(page_num, [])
                    
                    method_enum = self.parser_to_enum.get(parser_name, PageExtractionMethod.NONE)

                    # Подсчитываем числовые токены для оценки качества таблиц
                    numeric_total = self._count_numeric_tokens_in_text(text)
                    numeric_in_tables = self._count_numeric_tokens_in_tables(tables)
                    coverage = (numeric_in_tables / numeric_total) if numeric_total > 0 else 0.0
                    
                    # Обновляем результат, если этот парсер дал лучшее числовое покрытие
                    prev = results.get(page_num)
                    prev_coverage = 0.0
                    if prev and 'numeric_coverage' in prev:
                        prev_coverage = prev['numeric_coverage']
                    
                    should_replace = False
                    if not prev:
                        should_replace = True
                    else:
                        # Сначала сравниваем покрытие чисел в таблицах, затем длину текста
                        if coverage > prev_coverage + 0.01:
                            should_replace = True
                        elif abs(coverage - prev_coverage) <= 0.01 and len(text.strip()) > len(prev.get('text', '').strip()):
                            should_replace = True
                    
                    if should_replace:
                        results[page_num] = {
                            'text': text,
                            'tables': tables,
                            'method': method_enum,
                            'numeric_total': numeric_total,
                            'numeric_in_tables': numeric_in_tables,
                            'numeric_coverage': coverage,
                        }
                        self.page_registry.update(
                            page_num,
                            extracted=bool(text.strip()),
                            method=method_enum,
                            char_count=len(text),
                            table_count=len(tables),
                            confidence=0.85 if len(text) > 100 else 0.6,
                            numeric_tokens_total=numeric_total,
                            numeric_tokens_in_tables=numeric_in_tables,
                            table_coverage=coverage,
                        )
                
                # Если уже хорошее покрытие, можно остановиться
                coverage = self.page_registry.get_summary()['coverage_percent']
                if coverage >= 95:
                    logger.info(f"✓ Достаточное покрытие ({coverage}%), останавливаем парсеры")
                    break
                    
            except Exception as e:
                logger.error(f"⚠️ Парсер {parser_name} ошибся: {e}", exc_info=True)
                continue
        
        self.parser_used = "hybrid-fallback"
        return results
    
    def _extract_with_parser(self, pdf_path: str, parser_name: str) -> Tuple[Dict[int, str], Dict[int, List]]:
        """
        Извлекает текст и таблицы указанным парсером.
        🔧 ИСПРАВЛЕНО: Не фильтруем текст внутри таблиц полностью
        """
        page_texts: Dict[int, str] = {}
        page_tables: Dict[int, List] = {}
        
        if parser_name == 'pdfplumber' and HAS_PDFPLUMBER:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Извлекаем таблицы
                    finder = page.debug_tablefinder()
                    tables = []
                    table_bboxes = []
                    
                    for table in finder.tables:
                        table_data = table.extract()
                        if table_data and len(table_data) >= 2:
                            tables.append({'cells': table_data, 'bbox': table.bbox})
                            table_bboxes.append(table.bbox)
                    page_tables[page_num] = tables
                    
                    # 🔧 ИСПРАВЛЕНИЕ: Извлекаем ПОЛНЫЙ текст страницы (без фильтрации)
                    full_text = page.extract_text() or ""
                    
                    # Если текст пустой, но есть таблицы — конвертируем таблицы в текст
                    if len(full_text.strip()) < 50 and tables:
                        table_text_parts = []
                        for table in tables:
                            for row in table['cells']:
                                row_text = " | ".join(str(cell or "") for cell in row)
                                if row_text.strip():
                                    table_text_parts.append(row_text)
                        full_text = "\n".join(table_text_parts)
                        logger.info(f"📊 Страница {page_num}: текст получен из {len(tables)} таблиц")
                    
                    page_texts[page_num] = full_text
                    
        elif parser_name == 'pymupdf' and HAS_PYMUPDF:
            doc = fitz.open(pdf_path)
            for page_num, page in enumerate(doc, 1):
                page_texts[page_num] = page.get_text()
                table_list = page.find_tables()
                tables = []
                for table in table_list:
                    table_data = table.extract()
                    if table_data:
                        tables.append({'cells': table_data, 'bbox': table.bbox})
                page_tables[page_num] = tables
            doc.close()
            
        elif parser_name == 'pypdf2' and HAS_PYPDF2:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page_num, page in enumerate(reader.pages, 1):
                    page_texts[page_num] = page.extract_text() or ""
                    page_tables[page_num] = []
        
        return page_texts, page_tables
    
    def _process_problematic_pages_with_hybrid_ocr(self, pdf_path: str, 
                                                    page_numbers: List[int]) -> Dict[int, Tuple[str, Dict]]:
        """Обрабатывает проблемные страницы через гибридный OCR + Ollama"""
        hybrid_ocr = HybridOCREngine(ollama_engine=self.ollama_engine)
        return hybrid_ocr.process_pages(pdf_path, page_numbers, use_llm=True)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ДИАГНОСТИКИ ТАБЛИЦ ====================
    def _count_numeric_tokens_in_text(self, text: str) -> int:
        """
        Оценивает количество числовых токенов в произвольном тексте.
        Используем NumberNormalizer, чтобы учитывать разные форматы.
        """
        if not text:
            return 0
        tokens = re.findall(r'[\(\{\[]?\s*[\-+]?\s*[\d\s,\.]+\s*[\)\}\]]?', text)
        count = 0
        for tok in tokens:
            if NumberNormalizer.normalize(tok) is not None:
                count += 1
        return count

    def _count_numeric_tokens_in_tables(self, tables: List[Dict]) -> int:
        """
        Подсчёт числовых токенов только внутри ячеек таблиц.
        """
        if not tables:
            return 0
        count = 0
        for table in tables:
            cells = table.get('cells') or []
            for row in cells:
                for cell in row:
                    if cell is None:
                        continue
                    cell_text = str(cell)
                    tokens = re.findall(r'[\(\{\[]?\s*[\-+]?\s*[\d\s,\.]+\s*[\)\}\]]?', cell_text)
                    for tok in tokens:
                        if NumberNormalizer.normalize(tok) is not None:
                            count += 1
        return count
    
    def _normalize_numbers_in_text(self, text: str) -> str:
        """Применяет нормализацию чисел ко всему тексту"""
        def replace_number(match):
            original = match.group(0)
            normalized = NumberNormalizer.normalize(original)
            if normalized is not None:
                return NumberNormalizer.format_for_display(normalized)
            return original
        
        pattern = r'[\(\{\[]?\s*[\-+]?\s*[\d\s,\.]+\s*[\)\}\]]?'
        return re.sub(pattern, replace_number, text)
    
    def _format_table(self, cells: List[List[Optional[str]]]) -> Optional[str]:
        """Форматирует таблицу в Markdown с сохранением иерархии"""
        cleaned = [row for row in cells if row and any(cell and str(cell).strip() for cell in row)]
        if not cleaned:
            return None
        
        max_cols = max(len(row) for row in cleaned)
        lines = [f"[ТАБЛИЦА | Колонки: {max_cols}]"]
        
        for row_idx, row in enumerate(cleaned):
            padded = list(row) + [""] * (max_cols - len(row))
            cells_formatted = []
            
            for col_idx, cell in enumerate(padded):
                val = str(cell).strip().replace('\n', ' ').replace('|', r'\|') if cell else ""
                
                # Отступы для подуровней
                if col_idx == 0 and val:
                    spaces = len(cell) - len(cell.lstrip()) if cell else 0
                    if spaces > 0:
                        val = "▪ " * min(spaces // 2, 3) + val
                
                # Пустые ячейки
                if not val:
                    val = "–"
                elif val in ('-', '—', '–', '='):
                    val = "0"
                
                # Нормализация чисел в ячейках
                val = re.sub(r'^\s*\(\s*(\d[\d\s,]*)\s*\)\s*$', r'-\1', val)
                val = re.sub(r'(?<=\d)[\s\xa0]+(?=\d{3})', '', val)
                val = re.sub(r'(\d),(\d)', r'\1.\2', val)
                
                # Выделение итогов
                if any(val.lower().startswith(k) for k in TOTAL_KEYWORDS):
                    val = f"**{val}**"
                
                cells_formatted.append(val)
            
            lines.append("| " + " | ".join(cells_formatted) + " |")
            if row_idx == 0:
                lines.append("|" + "|".join(["---"] * max_cols) + "|")
        
        lines.append("[КОНЕЦ ТАБЛИЦЫ]")
        return "\n".join(lines)
    
    def _validate_extraction(self) -> List[str]:
        """Валидирует полноту извлечения, возвращает список предупреждений"""
        warnings = []
        if not self.page_registry:
            return ["Реестр страниц не инициализирован"]
        
        summary = self.page_registry.get_summary()
        
        # Проверка покрытия
        if summary['coverage_percent'] < 100:
            warnings.append(f"Неполное покрытие: {summary['coverage_percent']}% (пропущено {len(summary['missing_pages'])} страниц)")
        
        # Проверка ключевых страниц
        missing = summary['missing_pages']
        if missing:
            if 1 in missing:
                warnings.append("⚠️ Пропущена первая страница (может содержать заголовок отчёта)")
            if summary['total_pages'] in missing:
                warnings.append("⚠️ Пропущена последняя страница (может содержать подписи/примечания)")
            
            # Проверка критических страниц для финансовых отчётов
            critical_pages = [5, 6, 7]  # Баланс, ОПУ, ДДС
            for cp in critical_pages:
                if cp in missing:
                    warnings.append(f"⚠️ Пропущена критическая страница {cp} (финансовая отчётность)")
        
        # Проверка на "пустые" страницы
        low_content = [p.number for p in self.page_registry.pages.values() 
                      if p.extracted and p.char_count < 50 and p.table_count == 0]
        if low_content:
            warnings.append(f"Страницы с подозрительно малым контентом: {low_content[:10]}")

        # Проверка качества извлечения чисел в таблицах
        low_coverage_pages = [
            (p.number, round(p.table_coverage * 100, 1))
            for p in self.page_registry.pages.values()
            if p.extracted and p.numeric_tokens_total > 0 and p.table_coverage < 0.6
        ]
        if low_coverage_pages:
            # Показываем только первые несколько для краткости
            sample = low_coverage_pages[:10]
            warnings.append(
                f"Страницы с низким покрытием чисел таблицами (<60%): "
                f"{[{'page': n, 'coverage_pct': c} for n, c in sample]}"
            )
        
        return warnings
    
    def _save_debug_artifacts(self, page_num: int, text: str, tables: List):
        """Сохраняет отладочные артефакты для страницы"""
        try:
            page_dir = self.debug_output_dir / f"page_{page_num:03d}"
            page_dir.mkdir(exist_ok=True)
            
            (page_dir / "raw_text.txt").write_text(text, encoding='utf-8')
            
            if tables:
                (page_dir / "tables.json").write_text(
                    json.dumps(tables, ensure_ascii=False, indent=2, default=str),
                    encoding='utf-8'
                )
            
            meta = {
                'page_num': page_num,
                'char_count': len(text),
                'table_count': len(tables),
                'timestamp': datetime.now().isoformat(),
                'checksum': hashlib.md5(text.encode('utf-8')).hexdigest()
            }
            (page_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения отладки: {e}")
    
    def get_diagnostics(self) -> Dict[str, Any]:
        """Возвращает полную диагностику последнего извлечения"""
        if not self.page_registry:
            return {'error': 'Извлечение ещё не выполнялось'}
        
        return {
            'summary': self.page_registry.get_summary(),
            'report': self.page_registry.generate_report(),
            'warnings': self.extraction_warnings,
            'ocr_stats': {'pages_processed': self.ocr_pages, 'llm_enhanced': self.llm_pages},
            'ollama_stats': self.ollama_engine.get_stats() if self.ollama_engine else {},
            'parser_stats': {'available': self.parsers_available, 'used': self.parser_used}
        }


# ==================== УДОБНЫЕ ФУНКЦИИ ====================
def convert_pdf_smart(pdf_path: str, debug: bool = False, 
                      use_ollama: bool = True, ollama_model: str = 'qwen3.5:4b') -> Dict[str, Any]:
    """
    Быстрая функция для конвертации с полной диагностикой.
    """
    converter = PDFConverter(debug_mode=debug, ollama_model=ollama_model)
    return converter.extract(pdf_path, validate=True, return_metadata=True, use_ollama_for_missing=use_ollama)


def _render_clean_text_from_extracted(raw_text: str) -> str:
    """
    Преобразует внутренний формат ([[PAGE]], [[SECTION]], [[BLOCK:...]]) 
    в более «человеческий» плоский текст с таблицами в Markdown.
    
    ВАЖНО: Числа и содержимое таблиц НЕ меняем, мы только убираем служебные маркеры
    и лишний технический шум, чтобы результат был ближе к виду как в
    input/financial_text_source.txt.
    """
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    out: List[str] = []

    in_text_block = False
    in_table_block = False

    for line in lines:
        stripped = line.strip()

        # Служебные маркеры страниц/секций/блоков — не выводим
        if stripped.startswith("[[PAGE:") or stripped.startswith("[[SECTION:"):
            # Добавим мягкий разделитель между крупными блоками
            if out and out[-1]:
                out.append("")
            continue
        if stripped == "[[BLOCK:TEXT]]":
            in_text_block = True
            continue
        if stripped == "[[END_BLOCK:TEXT]]":
            in_text_block = False
            if out and out[-1]:
                out.append("")
            continue
        if stripped.startswith("[[BLOCK:TABLE"):
            in_table_block = True
            # перед таблицей оставим пустую строку
            if out and out[-1]:
                out.append("")
            continue
        if stripped == "[[END_BLOCK:TABLE]]":
            in_table_block = False
            if out and out[-1]:
                out.append("")
            continue

        # Технические строки вида "[ТАБЛИЦА | Колонки: N]" / "[КОНЕЦ ТАБЛИЦЫ]" можно скрыть
        if stripped.startswith("[ТАБЛИЦА ") and stripped.endswith("]"):
            continue
        if stripped == "[КОНЕЦ ТАБЛИЦЫ]":
            # после таблицы оставим пустую строку
            if out and out[-1]:
                out.append("")
            continue

        # Остальные строки — это либо обычный текст, либо строки markdown-таблиц
        out.append(line)

    # Уберём лишние пустые строки в начале/конце и двойные пробелы по вертикали
    # (но не схлопываем все пустые — абзацы важны)
    cleaned: List[str] = []
    blank_run = 0
    for line in out:
        if not line.strip():
            blank_run += 1
            if blank_run <= 2:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(line.rstrip())

    # Обрезаем пустоту в начале и конце
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()

    return "\n".join(cleaned)


def extract_text_only(pdf_path: str) -> str:
    """
    Простая функция для получения только текста в «чистом» виде:
    - использует стандартный PDFConverter (без изменения логики извлечения)
    - убирает внутренние служебные маркеры [[PAGE]], [[BLOCK:...]] и т.п.
    - сохраняет таблицы в Markdown, пригодные и человеку, и машине.
    """
    converter = PDFConverter()
    raw_text = converter.extract(pdf_path, validate=False, return_metadata=False)
    return _render_clean_text_from_extracted(raw_text)


def extract_first_pages_clean(pdf_path: str, max_pages: int = 10) -> str:
    """
    Возвращает «чистый» текст только для первых max_pages страниц PDF,
    в формате, максимально близком к input/financial_text_source.txt.
    
    Логику извлечения не трогаем — используем тот же PDFConverter,
    просто обрезаем внутренний текст до нужного количества [[PAGE:N]].
    """
    converter = PDFConverter()
    raw_text = converter.extract(pdf_path, validate=False, return_metadata=False)
    if not raw_text:
        return ""

    # Ищем маркеры страниц [[PAGE:N]] и обрезаем текст после max_pages
    import re

    matches = list(re.finditer(r"\[\[PAGE:(\d+)\]\]", raw_text))
    if not matches:
        subset = raw_text
    else:
        cutoff_pos = len(raw_text)
        for m in matches:
            try:
                page_num = int(m.group(1))
            except ValueError:
                continue
            if page_num > max_pages:
                cutoff_pos = m.start()
                break
        subset = raw_text[:cutoff_pos]

    return _render_clean_text_from_extracted(subset)


def validate_pdf_extraction(pdf_path: str) -> Dict[str, Any]:
    """Только валидация без полного извлечения"""
    converter = PDFConverter()
    result = converter.extract(pdf_path, validate=True, return_metadata=True)
    return {
        'file': Path(pdf_path).name,
        'diagnostics': result.get('diagnostics', {}),
        'warnings': result.get('warnings', []),
        'success': result.get('success', False)
    }


# ==================== УТИЛИТА БЕЗОПАСНОГО ВЫВОДА В КОНСОЛЬ ====================
def _safe_print(msg: str):
    """
    Печать только ASCII-символов, чтобы избежать UnicodeEncodeError
    в консоли Windows с ограниченной кодировкой.
    """
    try:
        text = str(msg)
    except Exception:
        text = repr(msg)
    ascii_text = text.encode('ascii', errors='ignore').decode('ascii', errors='ignore')
    print(ascii_text)


# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
if __name__ == "__main__":
    import sys
    
    # Путь к файлу
    target_pdf = "input/IFRS_12m2023_summary.pdf" if len(sys.argv) < 2 else sys.argv[1]
    
    if not Path(target_pdf).exists():
        _safe_print(f"[ERROR] File not found: {target_pdf}")
        _safe_print("Usage: python pdf_converter.py [pdf_path]")
        sys.exit(1)
    
    _safe_print(f"Start PDFConverter v5.0 (Ollama + fixes) for: {Path(target_pdf).name}")
    _safe_print("=" * 70)
    
    # Проверка Ollama
    _safe_print(f"\nOllama status: {'available' if HAS_OLLAMA else 'disabled'}")
    
    result = convert_pdf_smart(target_pdf, debug=False, use_ollama=True)
    
    if result['success']:
        _safe_print("\nEXTRACTION FINISHED")
        _safe_print("Metrics:")
        for key, value in result['metadata'].items():
            _safe_print(f"   - {key}: {value}")
        
        if result['diagnostics']:
            _safe_print("\nDiagnostics:")
            diag = result['diagnostics'].get('page_registry_summary', {})
            _safe_print(f"   - Coverage: {diag.get('coverage_percent', 'N/A')}%")
            _safe_print(f"   - Missing pages: {len(diag.get('missing_pages', []))}")
            _safe_print(f"   - OCR pages: {diag.get('ocr_pages', 0)}")
            _safe_print(f"   - Ollama enhanced pages: {diag.get('llm_pages', 0)}")
            if diag.get('missing_pages'):
                _safe_print(f"   - Missing page numbers (sample): {diag['missing_pages'][:10]}")
        
        if result['warnings']:
            _safe_print(f"\nWarnings ({len(result['warnings'])}):")
            for w in result['warnings'][:5]:
                _safe_print(f"   - {w}")
        
        # Проверка критических страниц
        critical_pages = [3, 4, 5, 6, 7, 114]
        _safe_print("\nCheck of critical pages:")
        for page_num in critical_pages:
            if f'[СТРАНИЦА {page_num}]' in result['text']:
                _safe_print(f"   Page {page_num}: FOUND")
            else:
                _safe_print(f"   Page {page_num}: MISSING")
        
        _safe_print("\nFirst 500 characters of text:")
        _safe_print("-" * 70)
        _safe_print(result['text'][:500])
        _safe_print("...")
        
        # Сохранение результата
        output_path = Path("output") / f"{Path(target_pdf).stem}_extracted.txt"
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(result['text'], encoding='utf-8')
        _safe_print(f"\nText saved to: {output_path}")
        
    else:
        _safe_print(f"Error: {result.get('warnings', ['Unknown error'])}")
        sys.exit(1)