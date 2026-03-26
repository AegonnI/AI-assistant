
from __future__ import annotations
import os
import sys
import json
import re
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Any, Tuple, List, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import shutil

# ==================== ЛОГИРОВАНИЕ ====================
logging.getLogger("pdfplumber").setLevel(logging.WARNING)
logging.getLogger("pdf2image").setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('pdf_to_text_extraction.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ==================== ПРОВЕРКА ЗАВИСИМОСТЕЙ ====================
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

# ==================== TORCH / GPU ДЕТЕКЦИЯ ====================

def _find_torch_whl_candidates(search_dirs):
    """Ищем локальные wheel-файлы torch с CUDA-поддержкой"""
    candidates = []
    patterns = ["torch-*.whl", "*torch*cu*.whl"]
    for base in search_dirs:
        base_path = Path(base)
        if not base_path.exists():
            continue
        for root, dirs, files in os.walk(base_path):
            for fn in files:
                fn_lower = fn.lower()
                if fn_lower.endswith('.whl') and ('torch' in fn_lower):
                    if 'cu' in fn_lower or 'cpu' in fn_lower or 'torch-' in fn_lower:
                        candidates.append(str(Path(root) / fn))
    return sorted(set(candidates))

try:
    import torch
    TORCH_AVAILABLE = True
    try:
        TORCH_CUDA_AVAILABLE = bool(torch.cuda.is_available())
    except Exception:
        TORCH_CUDA_AVAILABLE = False
except Exception as exc:
    TORCH_AVAILABLE = False
    TORCH_CUDA_AVAILABLE = False
    logger.warning(f"⚠️ torch не установлен: {exc}")
    local_search = [Path.cwd(), Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent, Path.home()]
    wheel_candidates = _find_torch_whl_candidates(local_search)
    if wheel_candidates:
        logger.info("ℹ️ Найдены локальные wheel-файлы torch (могут быть установлены вручную):")
        for p in wheel_candidates:
            logger.info(f"  - {p}")
    else:
        logger.info("ℹ️ Локальные wheel-файлы torch в известных каталогах не найдены")

try:
    SURYA_CMD = None
    HAS_SURYA = False

    # Проектный корень (одна папка выше модуля)
    project_root = Path(__file__).resolve().parent.parent

    # Проверяем стандартные имена виртуальных окружений
    for venv_name in ('.venv', 'venv', 'env', '.env'):
        venv_dir = project_root / venv_name
        if venv_dir.exists():
            scripts_dir = venv_dir / ('Scripts' if os.name == 'nt' else 'bin')
            cand = scripts_dir / ('surya_ocr.exe' if os.name == 'nt' else 'surya_ocr')
            if cand.exists():
                SURYA_CMD = str(cand)
                HAS_SURYA = True
                logger.info(f"✅ Surya найдена в виртуальном окружении: {SURYA_CMD}")
                break

    # Если не нашли — проверяем рядом с текущим интерпретатором
    if not HAS_SURYA:
        try:
            interp_scripts = Path(sys.executable).parent
            cand = interp_scripts / ('surya_ocr.exe' if os.name == 'nt' else 'surya_ocr')
            if cand.exists():
                SURYA_CMD = str(cand)
                HAS_SURYA = True
                logger.info(f"✅ Surya найдена рядом с python: {SURYA_CMD}")
        except Exception:
            pass

    # Проверяем PATH
    if not HAS_SURYA:
        which_name = 'surya_ocr.exe' if os.name == 'nt' else 'surya_ocr'
        path_cmd = shutil.which(which_name) or shutil.which('surya_ocr')
        if path_cmd:
            SURYA_CMD = path_cmd
            HAS_SURYA = True
            logger.info("✅ surya_ocr найдена в PATH")

    # Последняя попытка — запустить команду напрямую (если доступно)
    if not HAS_SURYA:
        try:
            result = subprocess.run([which_name, '--help'], capture_output=True, timeout=5)
            if result.returncode == 0:
                SURYA_CMD = which_name
                HAS_SURYA = True
                logger.info("✅ surya_ocr доступна (через запуск)")
        except Exception:
            pass

    if not HAS_SURYA:
        SURYA_CMD = None
        logger.warning("⚠️ surya_ocr не найден: pip install 'surya-ocr>=0.17.1'")

except Exception:
    HAS_SURYA = False
    SURYA_CMD = None
    logger.warning("⚠️ surya_ocr не найден: pip install 'surya-ocr>=0.17.1'")

# ==================== НОРМАЛИЗАЦИЯ ЧИСЕЛ ====================
class NumberNormalizer:
    """Нормализация финансовых чисел (русские и международные форматы)"""
    
    @staticmethod
    def normalize(text: str) -> Optional[float]:
        if not isinstance(text, str):
            return None
        
        text = text.strip()
        if not text:
            return None
        
        is_negative = False
        if text.startswith('(') and text.endswith(')'):
            is_negative = True
            text = text[1:-1].strip()
        elif text.startswith('[') and text.endswith(']'):
            is_negative = True
            text = text[1:-1].strip()
        
        text = re.sub(r'\s+', '', text)
        
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            text = text.replace(',', '.')
        
        try:
            value = float(text)
            return -value if is_negative else value
        except ValueError:
            return None

    @staticmethod
    def format_for_display(value: Optional[float], decimals: int = 2) -> str:
        if value is None:
            return "N/A"
        
        if value < 0:
            sign = "-"
            value = abs(value)
        else:
            sign = ""
        
        fmt = f"{value:,.{decimals}f}"
        parts = fmt.split('.')
        if len(parts) == 2:
            integer_part = parts[0].replace(',', ' ')
            return f"{sign}{integer_part},{parts[1]}"
        return f"{sign}{fmt.replace(',', ' ')}"

# ==================== РЕЕСТР СТРАНИЦ ====================
class PageExtractionMethod(Enum):
    """Методы извлечения текста"""
    SURYA_OCR = "surya_ocr"      # 🔥 Основной движок
    PDFPLUMBER = "pdfplumber"    # Fallback для таблиц
    PYMUPDF = "pymupdf"          # Fallback для быстрого текста
    FALLBACK = "fallback"

@dataclass
class PageStatus:
    """Статус извлечения одной страницы"""
    number: int
    extracted: bool = False
    method: PageExtractionMethod = PageExtractionMethod.FALLBACK
    char_count: int = 0
    table_count: int = 0
    confidence: float = 0.0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'page': self.number,
            'extracted': self.extracted,
            'method': self.method.value,
            'chars': self.char_count,
            'tables': self.table_count,
            'confidence': round(self.confidence, 2),
            'errors': self.errors
        }

class PageRegistry:
    """Реестр для отслеживания статуса каждой страницы"""
    
    def __init__(self, total_pages: int):
        self.total_pages = total_pages
        self.pages: Dict[int, PageStatus] = {
            i: PageStatus(number=i) for i in range(1, total_pages + 1)
        }

    def update(self, page_num: int, **kwargs):
        if page_num in self.pages:
            for key, value in kwargs.items():
                if hasattr(self.pages[page_num], key):
                    setattr(self.pages[page_num], key, value)

    def get_missing_pages(self) -> List[int]:
        return [p.number for p in self.pages.values() if not p.extracted]

    def get_summary(self) -> Dict[str, Any]:
        extracted = [p for p in self.pages.values() if p.extracted]
        return {
            'total_pages': self.total_pages,
            'extracted_pages': len(extracted),
            'coverage_percent': round(len(extracted) / self.total_pages * 100, 1) if self.total_pages > 0 else 0,
            'methods': list(set(p.method.value for p in extracted)),
            'total_chars': sum(p.char_count for p in extracted),
            'total_tables': sum(p.table_count for p in extracted),
            'avg_confidence': round(sum(p.confidence for p in extracted) / len(extracted), 2) if extracted else 0,
        }

# ==================== ОСНОВНОЙ ЭКСТРАКТОР ====================
class PDFToTextExtractor:
    """
    🔥 ГИБРИДНОЕ ИЗВЛЕЧЕНИЕ: Surya OCR как ОСНОВНОЙ движок
    Приоритет парсеров:
    1️⃣ Surya OCR — основной (пакетная обработка для скорости)
    2️⃣ pdfplumber — fallback для таблиц
    3️⃣ PyMuPDF — fallback для простого текста
    
    🆕 УЛУЧШЕНИЯ:
    - Структурированный JSON вывод
    - Markdown таблицы
    - Умная обработка колонок
    """

    def __init__(self, 
                 max_pages: Optional[int] = None, 
                 debug: bool = False,
                 surya_first: bool = True,
                 use_surya_batch: bool = True,
                 min_confidence: float = 0.7,
                 force_cpu: bool = False):
        """
        Args:
            max_pages: Максимум страниц для обработки
            debug: Включить отладочный вывод
            surya_first: Использовать Surya как основной парсер (по умолчанию True)
            use_surya_batch: Использовать пакетную обработку Surya (по умолчанию True)
            min_confidence: Минимальный порог уверенности для принятия результата
        """
        self.max_pages = max_pages
        self.debug = debug
        self.page_registry: Optional[PageRegistry] = None
        self.surya_first = surya_first
        self.use_surya_batch = use_surya_batch
        self.min_confidence = min_confidence
        self.force_cpu = force_cpu
        
        # Определяем доступность вычислений
        self.torch_available = TORCH_AVAILABLE
        self.gpu_available = TORCH_CUDA_AVAILABLE
        self.selected_cuda_devices = ''
        self.compute_device = 'cpu' if force_cpu else ('cuda' if TORCH_CUDA_AVAILABLE else 'cpu')

        # 🔥 Формируем приоритет парсеров
        self.parsers = []
        
        if surya_first and HAS_SURYA:
            self.parsers.append('surya')
            logger.info("✅ Surya OCR установлен как ОСНОВНОЙ парсер (приоритет №1)")
        
        if HAS_PDFPLUMBER:
            self.parsers.append('pdfplumber')
        
        if HAS_PYMUPDF:
            self.parsers.append('pymupdf')
        
        # Если Surya не первый, но доступен — добавляем в конец как fallback
        if not surya_first and HAS_SURYA:
            self.parsers.append('surya')
            logger.info("✅ Surya OCR доступна как fallback-парсер")
        
        if not self.parsers:
            raise RuntimeError(
                "❌ Не установлены необходимые библиотеки. "
                "Минимум требуется: pip install 'surya-ocr>=0.17.1'"
            )
        
        logger.info(f"📋 Активные парсеры (по приоритету): {self.parsers}")

    def _get_surya_execution_plan(self) -> Tuple[str, str]:
        """Возвращает (CUDA_VISIBLE_DEVICES, compute_device)
        compute_device: 'cuda' или 'cpu'.
        """
        if self.force_cpu:
            return '', 'cpu'

        env_cuda = os.environ.get('CUDA_VISIBLE_DEVICES')
        if env_cuda is not None:
            env_cuda = env_cuda.strip()
            if env_cuda == '' or env_cuda == '-1':
                return '', 'cpu'
            return env_cuda, 'cuda'

        if self.torch_available and self.gpu_available:
            return '0', 'cuda'

        return '', 'cpu'

    def extract(self, pdf_path: Union[str, Path]) -> Dict[str, Any]:
        """
        🆕 Основной метод извлечения текста из PDF
        Возвращает структурированные данные для машинного считывания
        """
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            logger.error(f"❌ Файл не найден: {pdf_path}")
            return {'success': False, 'text': '', 'error': 'File not found'}
        
        logger.info(f"📖 Начинаю извлечение: {pdf_path.name}")
        start_time = datetime.now()
        
        try:
            total_pages = self._get_total_pages(str(pdf_path))
            logger.info(f"📑 Всего страниц: {total_pages}")
            
            self.page_registry = PageRegistry(total_pages)
            
            # 🔥 Извлечение с Surya-first логикой
            extraction_result = self._extract_surya_first_structured(str(pdf_path), total_pages)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # 🆕 Формируем структурированный результат
            result = {
                'success': True,
                'text': extraction_result['plain_text'],  # Для обратной совместимости
                'structured': extraction_result['structured'],  # 🆕 JSON структура
                'filename': pdf_path.name,
                'total_pages': total_pages,
                'extraction_time_sec': round(elapsed, 2),
                'char_count': len(extraction_result['plain_text']),
                'stats': self.page_registry.get_summary() if self.page_registry else {},
                'metadata': {
                    'extraction_date': datetime.now().isoformat(),
                    'surya_version': '0.17.1+',
                    'parsers_used': self.parsers,
                    'torch_available': self.torch_available,
                    'gpu_available': self.gpu_available,
                    'compute_device': self.compute_device,
                    'cuda_visible_devices': self.selected_cuda_devices
                }
            }
            
            logger.info(f"✅ Готово за {elapsed:.1f}с | Символов: {len(extraction_result['plain_text']):,}")
            return result
        
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}", exc_info=self.debug)
            return {'success': False, 'text': '', 'error': str(e)}

    def _get_total_pages(self, pdf_path: str) -> int:
        """Получает количество страниц в PDF"""
        if HAS_PYMUPDF:
            try:
                with fitz.open(pdf_path) as doc:
                    return doc.page_count
            except Exception as e:
                logger.warning(f"⚠️ PyMuPDF ошибка: {e}")
        
        if HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    return len(pdf.pages)
            except Exception as e:
                logger.warning(f"⚠️ pdfplumber ошибка: {e}")
        
        return 0

    def _extract_surya_first_structured(self, pdf_path: str, total_pages: int) -> Dict[str, Any]:
        """
        🔥 ИЗВЛЕЧЕНИЕ С SURYA-FIRST ЛОГИКОЙ (СТРУКТУРИРОВАННОЕ)
        
        1. Если Surya доступна и use_surya_batch=True → запускаем ОДИН раз для ВСЕХ страниц
        2. Для каждой страницы берём результат Surya, если confidence >= min_confidence
        3. Если Surya не справился → пробуем fallback-парсеры (pdfplumber → PyMuPDF)
        
        🆕 Возвращает: {'plain_text': str, 'structured': List[Dict]}
        """
        all_text = []
        structured_pages = []
        surya_cache: Dict[int, Tuple[str, float, List[Dict]]] = {}
        
        # 🚀 ПАКЕТНАЯ ОБРАБОТКА SURYA (если включена)
        if HAS_SURYA and self.use_surya_batch and 'surya' in self.parsers:
            logger.info(f"🚀 Запуск Surya в пакетном режиме для {total_pages} страниц...")
            surya_cache = self._extract_all_pages_surya(pdf_path, total_pages)
            logger.info(f"✅ Surya batch: обработано {len(surya_cache)}/{total_pages} страниц")
        
        # Обрабатываем каждую страницу
        for page_num in range(1, total_pages + 1):
            if self.max_pages and page_num > self.max_pages:
                break
            
            page_text = ""
            page_blocks = []
            best_method = None
            best_confidence = 0.0
            
            # 🔥 1️⃣ Сначала пробуем Surya (из кэша batch-обработки)
            if page_num in surya_cache:
                text, confidence, blocks = surya_cache[page_num]
                if text.strip() and confidence >= self.min_confidence:
                    page_text = text
                    page_blocks = blocks
                    best_confidence = confidence
                    best_method = 'surya'
                    if self.debug:
                        logger.debug(f"✓ Page {page_num}: Surya batch ({len(text)} chars, conf={confidence:.2f})")
            
            # 🔁 2️⃣ Если Surya не справился — пробуем fallback-парсеры
            if not page_text or best_confidence < self.min_confidence:
                fallback_parsers = [p for p in self.parsers if p != 'surya']
                
                for parser_name in fallback_parsers:
                    try:
                        text, confidence = self._extract_page_standard(pdf_path, page_num, parser_name)
                        if text.strip() and confidence > best_confidence:
                            page_text = text
                            page_blocks = [{'type': 'text', 'content': text}]
                            best_confidence = confidence
                            best_method = parser_name
                            if self.debug:
                                logger.debug(f"✓ Page {page_num}: fallback {parser_name} ({len(text)} chars)")
                            # Если fallback дал хороший результат — останавливаем перебор
                            if confidence >= 0.85:
                                break
                    except Exception as e:
                        logger.debug(f"⚠️ {parser_name} failed on page {page_num}: {e}")
            
            # 🔄 3️⃣ Если всё ещё пусто и Surya доступна — пробуем постраничный Surya fallback
            if not page_text and HAS_SURYA and page_num not in surya_cache:
                try:
                    text, confidence = self._extract_page_surya_single(pdf_path, page_num)
                    if text.strip() and confidence >= self.min_confidence:
                        page_text = text
                        page_blocks = [{'type': 'text', 'content': text}]
                        best_confidence = confidence
                        best_method = 'surya'
                        if self.debug:
                            logger.debug(f"✓ Page {page_num}: Surya single-page fallback")
                except Exception as e:
                    logger.debug(f"⚠️ Surya single-page fallback failed for page {page_num}: {e}")
            
            # 📊 Обновляем реестр страницы
            if self.page_registry:
                method_map = {
                    'pymupdf': PageExtractionMethod.PYMUPDF,
                    'pdfplumber': PageExtractionMethod.PDFPLUMBER,
                    'surya': PageExtractionMethod.SURYA_OCR
                }
                method = method_map.get(best_method, PageExtractionMethod.FALLBACK)
                self.page_registry.update(
                    page_num,
                    extracted=bool(page_text),
                    char_count=len(page_text),
                    table_count=page_text.count('### TABLE') if page_text else 0,
                    confidence=best_confidence,
                    method=method
                )
            
            # Добавляем текст в результат
            if page_text:
                all_text.append(f"[[PAGE:{page_num}]]\n{page_text}")
                
                # 🆕 Добавляем структурированные данные страницы
                structured_pages.append({
                    'page_number': page_num,
                    'method': best_method,
                    'confidence': round(best_confidence, 2),
                    'char_count': len(page_text),
                    'blocks': page_blocks if page_blocks else [{'type': 'text', 'content': page_text}]
                })
                
                if self.debug:
                    logger.info(f"  ✓ Page {page_num}: {len(page_text)} chars ({best_method})")
            else:
                logger.warning(f"  ⚠️ Page {page_num}: все парсеры не справились")
                structured_pages.append({
                    'page_number': page_num,
                    'method': None,
                    'confidence': 0.0,
                    'char_count': 0,
                    'blocks': [],
                    'error': 'All parsers failed'
                })
        
        # ============ ФИНАЛЬНАЯ ОБРАБОТКА ============
        full_text = "\n\n".join(all_text)
        
        # 1️⃣ Очищаем HTML-теги
        full_text = self._clean_html_tags(full_text)
        
        # 2️⃣ Восстанавливаем таблицы и числа
        full_text = self._post_process_numbers(full_text)
        
        return {
            'plain_text': full_text,
            'structured': structured_pages
        }

    def _extract_all_pages_surya(self, pdf_path: str, total_pages: int) -> Dict[int, Tuple[str, float, List[Dict]]]:
        """
        🔥 ПАКЕТНАЯ ОБРАБОТКА: Surya для ВСЕХ страниц за один запуск
        
        🆕 Возвращает: {page_num: (text, confidence, blocks)}
        """
        results = {}
        
        if not HAS_SURYA:
            return results
        
        try:
            max_page = self.max_pages if self.max_pages else total_pages
            page_range = f"0-{max_page - 1}"  # Surya использует 0-based индексацию
            
            temp_suffix = int(time.time() * 1000) % 100000
            output_dir = Path(tempfile.gettempdir()) / f"surya_batch_{temp_suffix}"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                SURYA_CMD,
                '--output_dir', str(output_dir),
                '--page_range', page_range,
                pdf_path
            ]
            
            logger.info(f"🚀 Surya batch: {' '.join(cmd)}")

            cuda_val, compute_device = self._get_surya_execution_plan()
            self.selected_cuda_devices = cuda_val
            self.compute_device = compute_device

            logger.info(f"🔧 Surya batch выберет устройство: {compute_device} (CUDA_VISIBLE_DEVICES={cuda_val!r})")

            # Запускаем Surya и транслируем вывод в реальном времени (показывает прогресс загрузки весов)
            proc_env = {**os.environ, 'CUDA_VISIBLE_DEVICES': cuda_val, 'HF_HOME': str(Path(tempfile.gettempdir()) / 'hf_cache')}
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=proc_env)
            except FileNotFoundError as e:
                logger.error(f"⚠️ Не удалось запустить Surya: {e}")
                return results

            out_lines: List[str] = []
            if proc.stdout:
                for line in proc.stdout:
                    out_lines.append(line)
                    # Печатаем в логы в режиме INFO чтобы пользователь видел прогресс
                    logger.info(line.rstrip())

            proc.wait(timeout=1800)
            returncode = proc.returncode
            full_output = "".join(out_lines)

            if returncode != 0:
                logger.error(f"⚠️ Surya batch failed with code {returncode}.")
                # Диагностика по выводу
                if 'pad_token_id' in full_output or 'SuryaDecoderConfig' in full_output:
                    logger.warning(
                        "⚠️ Ошибка инициализации модели Surya (возможно несовместимая версия 'transformers'). "
                        "Попробуйте обновить/понизить пакет: python -m pip install --force-reinstall \"transformers>=4.0.0,<5\""
                    )
                return results
            
            # Ищем results.json
            pdf_stem = Path(pdf_path).stem
            results_json = output_dir / pdf_stem / 'results.json'
            
            if not results_json.exists():
                found_jsons = list(output_dir.glob('**/results.json'))
                if found_jsons:
                    results_json = found_jsons[0]
                else:
                    logger.warning(f"⚠️ Surya: results.json not found")
                    return results
            
            with open(results_json, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
            
            root_key = pdf_stem if pdf_stem in data else (next(iter(data.keys()), None) if data else None)
            if not root_key:
                return results
            
            pages = data.get(root_key, [])
            logger.info(f"📄 Surya extracted {len(pages)} pages")
            
            for page_idx, page_pred in enumerate(pages):
                page_num = page_idx + 1
                
                # ГРУППИРОВКА С УЧЕТОМ КОЛОНОК
                items = []
                y_tol = 6.0
                
                for tl in (page_pred.get("text_lines") or []):
                    t = (tl.get("text") or "").strip()
                    if not t:
                        continue
                    
                    poly = tl.get("polygon")
                    if poly and isinstance(poly, list) and poly:
                        try:
                            xs = [pt[0] for pt in poly]
                            ys = [pt[1] for pt in poly]
                            y = sum(ys) / len(ys)
                            x = min(xs)
                        except Exception:
                            y, x = float("inf"), float("inf")
                    else:
                        y, x = float("inf"), float("inf")
                    
                    items.append((y, x, t))
                
                # 🆕 Сортировка с учетом колонок (сначала Y, потом X)
                items.sort(key=lambda z: (z[0] // 10 * 10, z[1]))
                
                # 🆕 Группировка в строки с учетом X-координат для многоколоночных документов
                lines = []
                blocks = []
                cur_y = None
                cur_parts = []
                cur_x_cluster = None
                x_threshold = 100.0  # 🆕 Порог для определения новой колонки
                
                for y, x, t in items:
                    # Проверяем, не новая ли это колонка
                    is_new_column = False
                    if cur_x_cluster is not None and abs(x - cur_x_cluster) > x_threshold:
                        is_new_column = True
                    
                    if cur_y is None or abs(y - cur_y) <= y_tol:
                        if is_new_column and cur_parts:
                            # Завершаем текущую строку и начинаем новую колонку
                            lines.append("  ".join(cur_parts))
                            blocks.append({'type': 'text_line', 'content': "  ".join(cur_parts), 'y': cur_y})
                            cur_parts = [t]
                            cur_x_cluster = x
                        else:
                            cur_parts.append(t)
                            cur_y = y if cur_y is None else (cur_y * 0.7 + y * 0.3)
                            if cur_x_cluster is None:
                                cur_x_cluster = x
                    else:
                        if cur_parts:
                            lines.append("  ".join(cur_parts))
                            blocks.append({'type': 'text_line', 'content': "  ".join(cur_parts), 'y': cur_y})
                        cur_parts = [t]
                        cur_y = y
                        cur_x_cluster = x
                
                if cur_parts:
                    lines.append("  ".join(cur_parts))
                    blocks.append({'type': 'text_line', 'content': "  ".join(cur_parts), 'y': cur_y})
                
                page_text = "\n".join(lines)
                page_text = re.sub(r"[ \t]{2,}", "  ", page_text).strip()
                
                # 🆕 Определяем блоки (таблицы, заголовки, текст)
                page_blocks = self._identify_blocks(page_text, blocks)
                
                confidence = 0.98 if page_text.strip() else 0.0
                results[page_num] = (page_text, confidence, page_blocks)
            
            logger.info(f"✅ Surya batch: успешно {len(results)} страниц")
            return results
        
        except Exception as e:
            logger.error(f"❌ Surya batch error: {e}")
            return results

    def _identify_blocks(self, text: str, lines: List[Dict]) -> List[Dict]:
        """
        🆕 Идентификация смысловых блоков на странице
        """
        blocks = []
        
        # Простая эвристика: если строка короткая и заглавная — возможно заголовок
        for line in lines:
            content = line.get('content', '')
            if len(content) < 100 and content.isupper():
                line['type'] = 'heading'
            elif '### TABLE' in content or '|' in content:
                line['type'] = 'table'
            else:
                line['type'] = 'text'
            blocks.append(line)
        
        return blocks

    def _extract_page_standard(self, pdf_path: str, page_num: int, parser_name: str) -> Tuple[str, float]:
        """Извлечение одной страницы стандартными парсерами (pdfplumber / PyMuPDF)"""
        
        if parser_name == 'pdfplumber' and HAS_PDFPLUMBER:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    if page_num > len(pdf.pages):
                        return "", 0.0
                    
                    page = pdf.pages[page_num - 1]
                    text = page.extract_text() or ""
                    
                    # Извлечение таблиц
                    table_text = ""
                    tables = []
                    
                    for table_config in [
                        {},  # Дефолт
                        {"vertical_strategy": "lines", "horizontal_strategy": "lines", "intersection_tolerance": 5},
                        {"vertical_strategy": "text", "horizontal_strategy": "text"}
                    ]:
                        try:
                            tables = page.extract_tables(table_config)
                            if tables and any(any(cell for cell in row) for row in tables):
                                break
                        except:
                            continue
                    
                    if tables:
                        table_text = self._format_tables(tables)
                    
                    # Комбинация текста и таблиц
                    if text.strip() and table_text.strip():
                        full_text = text + "\n\n" + table_text
                    else:
                        full_text = text or table_text
                    
                    full_text = self._post_process_numbers(full_text)
                    confidence = 0.9 if full_text.strip() else 0.1
                    
                    return full_text, confidence
            except Exception as e:
                logger.debug(f"pdfplumber error page {page_num}: {e}")
                return "", 0.0
        
        elif parser_name == 'pymupdf' and HAS_PYMUPDF:
            try:
                with fitz.open(pdf_path) as doc:
                    if page_num > doc.page_count:
                        return "", 0.0
                    
                    page = doc[page_num - 1]
                    text = page.get_text() or ""
                    confidence = 0.75 if text.strip() else 0.2
                    
                    return text, confidence
            except Exception as e:
                logger.debug(f"PyMuPDF error page {page_num}: {e}")
                return "", 0.0
        
        return "", 0.0

    def _extract_page_surya_single(self, pdf_path: str, page_num: int) -> Tuple[str, float]:
        """Постраничный fallback для Surya (если batch не сработал)"""
        try:
            page_range = f"{page_num - 1}-{page_num - 1}"
            temp_suffix = int(time.time() * 1000) % 100000
            output_dir = Path(tempfile.gettempdir()) / f"surya_page_{page_num}_{temp_suffix}"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            cmd = [SURYA_CMD, '--output_dir', str(output_dir), '--page_range', page_range, pdf_path]
            
            cuda_val, compute_device = self._get_surya_execution_plan()
            self.selected_cuda_devices = cuda_val
            self.compute_device = compute_device

            logger.debug(f"🔧 Surya single-page выберет устройство: {compute_device} (CUDA_VISIBLE_DEVICES={cuda_val!r})")
            proc_env = {**os.environ, 'CUDA_VISIBLE_DEVICES': cuda_val, 'HF_HOME': str(Path(tempfile.gettempdir()) / 'hf_cache')}
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=proc_env)
            except FileNotFoundError as e:
                logger.error(f"⚠️ Не удалось запустить Surya: {e}")
                return "", 0.0

            out_lines: List[str] = []
            if proc.stdout:
                for line in proc.stdout:
                    out_lines.append(line)
                    logger.info(line.rstrip())

            proc.wait(timeout=120)
            returncode = proc.returncode
            full_output = "".join(out_lines)

            if returncode != 0:
                logger.error(f"⚠️ Surya single-page failed with code {returncode}.")
                if 'pad_token_id' in full_output or 'SuryaDecoderConfig' in full_output:
                    logger.warning(
                        "⚠️ Ошибка инициализации модели Surya (возможно несовместимая версия 'transformers'). "
                        "Попробуйте: python -m pip install --force-reinstall \"transformers>=4.0.0,<5\""
                    )
                return "", 0.0
            
            pdf_stem = Path(pdf_path).stem
            results_json = output_dir / pdf_stem / 'results.json'
            
            if not results_json.exists():
                found = list(output_dir.glob('**/results.json'))
                results_json = found[0] if found else None
            
            if not results_json or not results_json.exists():
                return "", 0.0
            
            with open(results_json, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
            
            root_key = pdf_stem if pdf_stem in data else (next(iter(data.keys()), None) if data else None)
            if not root_key or root_key not in data:
                return "", 0.0
            
            pages = data.get(root_key, [])
            if not pages:
                return "", 0.0
            
            page_pred = pages[0]
            items = []
            y_tol = 6.0
            
            for tl in page_pred.get('text_lines', []):
                t = (tl.get('text') or '').strip()
                if not t:
                    continue
                poly = tl.get('polygon')
                if poly and isinstance(poly, list) and poly:
                    try:
                        xs = [pt[0] for pt in poly]
                        ys = [pt[1] for pt in poly]
                        y = sum(ys) / len(ys)
                        x = min(xs)
                    except:
                        y, x = float('inf'), float('inf')
                else:
                    y, x = float('inf'), float('inf')
                items.append((y, x, t))
            
            items.sort(key=lambda z: (z[0], z[1]))
            
            lines = []
            cur_y = None
            cur_parts = []
            
            for y, _x, t in items:
                if cur_y is None or abs(y - cur_y) <= y_tol:
                    cur_parts.append(t)
                    cur_y = y if cur_y is None else (cur_y * 0.7 + y * 0.3)
                else:
                    if cur_parts:
                        lines.append(' '.join(cur_parts))
                    cur_parts = [t]
                    cur_y = y
            
            if cur_parts:
                lines.append(' '.join(cur_parts))
            
            text = '\n'.join(lines)
            text = re.sub(r'[ \t]{2,}', ' ', text).strip()
            text = text.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
            
            confidence = 0.98 if text.strip() else 0.0
            return text, confidence
            
        except Exception as e:
            logger.debug(f"Surya single-page error page {page_num}: {e}")
            return "", 0.0

    def _clean_html_tags(self, text: str) -> str:

        # Убираем теги переноса строки (заменяем на пробел для сохранения разделения)
        text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
        
        # Убираем прочие парные теги
        text = re.sub(r'</?\w+[^>]*>', '', text)
        
        # Убираем HTML-сущности
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        
        # Очищаем множественные пробелы (могли образоваться после удаления тегов)
        text = re.sub(r'  +', ' ', text)
        
        return text

    def _post_process_numbers(self, text: str) -> str:
        """
        🔧 РАСШИРЕННАЯ ПОСТОБРАБОТКА: восстановление финансовых таблиц
        
        ⚠️ ПРОБЛЕМА: pdfplumber и Surya часто разбивают таблицы:
           Исходное: "637 469 | 180 175" (одна строка)
           Извлекается как:
               637 469 180 175     (строка 1)
               127 658 110 035     (строка 2)  ← РАЗНЫЕ СТРОКИ, НЕПРАВИЛЬНО!
        
        ✅ РЕШЕНИЕ: Этот алгоритм:
           1. Обнаруживает "осиротелые" числа (отдельные на строке)
           2. Восстанавливает таблицы, объединяя числа по вертикали
           3. Сохраняет финансовый формат (123 456 789)
        """
        
        # ============ ШАГ 1: Распознавание таблиц ============
        # Таблица = несколько подряд идущих строк с только числами/пробелами/|
        lines = text.split('\n')
        table_regions = self._identify_table_regions(lines)
        
        # ============ ШАГ 2: Восстановление таблиц ============
        result = []
        i = 0
        
        while i < len(lines):
            # Проверяем, находимся ли в таблице
            in_table = False
            for start, end in table_regions:
                if start <= i < end:
                    in_table = True
                    break
            
            if in_table:
                # Ищем начало таблицы
                table_start = i
                for start, end in table_regions:
                    if start <= i < end:
                        table_start = start
                        i = end
                        break
                
                # Восстанавливаем таблицу
                table_lines = lines[table_start:i]
                recovered_table = self._recover_table_structure(table_lines)
                result.extend(recovered_table)
            else:
                # Обычная строка - просто очищаем пробелы
                line = lines[i]
                if any(c.isdigit() for c in line):
                    line = re.sub(r'[ \t]{2,}', ' ', line).strip()
                result.append(line)
                i += 1
        
        return '\n'.join(result)

    def _identify_table_regions(self, lines: List[str]) -> List[Tuple[int, int]]:

        regions = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Проверяем, похожа ли строка на табличные данные
            # (только числа, пробелы, разделители)
            if self._looks_like_table_row(line):
                start = i
                
                # Ищем конец таблицы (последовательность таких строк)
                while i < len(lines) and self._looks_like_table_row(lines[i]):
                    i += 1
                
                # Таблица должна быть минимум 2 строки
                if i - start >= 2:
                    regions.append((start, i))
                else:
                    i = start + 1
            else:
                i += 1
        
        return regions

    def _looks_like_table_row(self, line: str) -> bool:
        """Проверяет, похожа ли строка на строку таблицы"""
        if not line.strip():
            return False
        
        # Удаляем разделители
        cleaned = line.replace('|', ' ').replace('-', ' ').replace('=', ' ').strip()
        
        if not cleaned:
            return False
        
        # Проверяем состав символов
        # Разрешены: цифры, пробелы, запятые, точки, скобки, минус
        allowed = set('0123456789 .,()-')
        
        for char in cleaned:
            if char not in allowed:
                return False
        
        # Должно быть хотя бы одно число
        return any(c.isdigit() for c in cleaned)

    def _recover_table_structure(self, table_lines: List[str]) -> List[str]:

        # ============ ШАГ 1: Парсим числовые колонки ============
        parsed_rows = []
        
        for line in table_lines:
            # Убираем разделители строк (|, -, =)
            cleaned = line
            for sep in ['|', '-', '=']:
                cleaned = cleaned.replace(sep, ' ')
            
            # Находим все числа (включая те, что разделены пробелами)
            # Например: "637 469 180 175" → ["637 469", "180 175"]
            # или "127 658 110 035" → ["127 658", "110 035"]
            
            numbers = self._extract_numbers_from_line(cleaned)
            parsed_rows.append(numbers)
        
        # ============ ШАГ 2: Выравниваем колонки ============
        if not parsed_rows:
            return table_lines
        
        # Определяем количество колонок (максимум в любой строке)
        num_cols = max(len(row) for row in parsed_rows) if parsed_rows else 1
        
        # Выравниваем все строки
        aligned_rows = []
        for row in parsed_rows:
            # Дополняем до нужного количества колонок
            while len(row) < num_cols:
                row.append("")
            aligned_rows.append(row[:num_cols])
        
        # ============ ШАГ 3: Форматируем вывод ============
        result = []
        
        for row in aligned_rows:
            # Форматируем каждое число
            formatted_cells = []
            
            for cell in row:
                if not cell or not cell.strip():
                    formatted_cells.append("")
                else:
                    # Очищаем и форматируем число
                    formatted = self._format_financial_number(cell.strip())
                    formatted_cells.append(formatted)
            
            # Собираем строку с правильным разделением
            # Добавляем пробелы между колонками для визуального разделения
            line = " | ".join(f"{cell:>15}" for cell in formatted_cells)
            result.append(line.rstrip())
        
        return result

    def _extract_numbers_from_line(self, line: str) -> List[str]:

        
        numbers = []
        i = 0
        
        while i < len(line):
            # Пропускаем ведущие пробелы
            while i < len(line) and line[i] == ' ':
                i += 1
            
            if i >= len(line):
                break
            
            # Начинаем читать число
            start = i
            current_num = ""
            
            while i < len(line):
                if line[i].isdigit() or line[i] in '.,()-':
                    current_num += line[i]
                    i += 1
                elif line[i] == ' ':
                    # Проверяем, это разделитель между частями числа или между числами?
                    space_count = 0
                    j = i
                    while j < len(line) and line[j] == ' ':
                        space_count += 1
                        j += 1
                    
                    if j < len(line) and line[j].isdigit():
                        # Следующий символ - цифра
                        
                        # Если после последней цифры в current_num идут скобки (отрицательное число)
                        # или если это продолжение числа (одинарный проб), то продолжаем
                        
                        # Эвристика: в финансовых числах пробелы для 1000-разделителя идут регулярно
                        # Обычно: "123 456 789" (пробелы через каждые 3 цифры)
                        
                        if space_count == 1:
                            # Скорее всего, это разделитель внутри числа (1000-separator)
                            current_num += ' '
                            i = j
                        else:
                            # 2+ пробела = разделитель между числами
                            break
                    else:
                        # После пробелов нет цифр
                        break
                else:
                    # Не цифра, не пробел, не разделитель - конец числа
                    break
            
            if current_num.strip():
                numbers.append(current_num.strip())
        
        return numbers

    def _format_financial_number(self, num_str: str) -> str:
        
        
        if not num_str or not num_str.strip():
            return ""
        
        # Проверяем на скобки (отрицательные)
        is_negative = num_str.strip().startswith('(') and num_str.strip().endswith(')')
        
        if is_negative:
            num_str = num_str.strip()[1:-1]
        
        # Убираем все пробелы и оставляем только цифры (и точку/запятую)
        num_str = num_str.strip()
        
        # Убираем существующие пробелы
        num_str = num_str.replace(' ', '')
        
        # Пробуем распарсить как число
        try:
            # Заменяем запятую на точку для парсинга
            parsed = num_str.replace(',', '.')
            float(parsed)
        except ValueError:
            # Не число - возвращаем как есть
            return num_str
        
        # Убираем дробную часть для форматирования
        if '.' in num_str:
            parts = num_str.split('.')
            integer_part = parts[0]
            fractional_part = '.'.join(parts[1:])
        elif ',' in num_str:
            parts = num_str.split(',')
            integer_part = parts[0]
            fractional_part = ','.join(parts[1:])
        else:
            integer_part = num_str
            fractional_part = ""
        
        # Добавляем пробелы в целую часть (каждые 3 цифры справа)
        # Например: "1234567" → "1 234 567"
        if len(integer_part) > 3:
            reversed_int = integer_part[::-1]
            formatted_int = ' '.join(
                reversed_int[i:i+3] 
                for i in range(0, len(reversed_int), 3)
            )[::-1]
        else:
            formatted_int = integer_part
        
        # Собираем результат
        result = formatted_int
        if fractional_part:
            result += '.' + fractional_part
        
        if is_negative:
            result = f"({result})"
        
        return result

    def _format_tables(self, tables: List[List[List[str]]]) -> str:
        """
        🆕 Форматирование таблиц из pdfplumber в Markdown
        
        Markdown лучше для машинного парсинга чем ASCII-арт
        """
        if not tables:
            return ""
        
        result = []
        for table_idx, table in enumerate(tables):
            if not table or not any(any(cell for cell in row) for row in table):
                continue
            
            # 🆕 Markdown заголовок таблицы
            result.append(f"\n### TABLE {table_idx + 1}\n")
            
            formatted_rows = []
            for row in table:
                cells = []
                for cell in row:
                    if cell is None:
                        cells.append("")
                    else:
                        text = str(cell).strip()
                        text = text.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
                        text = re.sub(r'\s+', ' ', text)
                        cells.append(text)
                if any(cells):
                    formatted_rows.append(cells)
            
            if not formatted_rows:
                continue
            
            # 🆕 Markdown формат таблицы
            # Заголовок
            header = formatted_rows[0] if len(formatted_rows) > 1 else [""] * len(formatted_rows[0])
            result.append("| " + " | ".join(header) + " |")
            
            # Разделитель
            result.append("| " + " | ".join(["---"] * len(header)) + " |")
            
            # Тело таблицы
            for row in formatted_rows[1:]:
                result.append("| " + " | ".join(row) + " |")
        
        return "\n".join(result)

    def save_to_file(self, result: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
        """
         Сохранение результата в файл (TXT + JSON)
        """
        if not output_path:
            filename = result['filename'].replace('.pdf', '')
            suffix = f"_first{self.max_pages}" if self.max_pages else "_all"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path('output') / f"extracted_{filename}{suffix}_{timestamp}.txt"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        #  Сохраняем plain text для обратной совместимости
        output_path.write_text(result['text'], encoding='utf-8')
        
        logger.info(f"💾 Сохранено TXT: {output_path}")
        
        #  Сохраняем структурированный JSON для машинного считывания
        json_path = output_path.with_suffix('.json')
        json_data = {
            'metadata': result.get('metadata', {}),
            'stats': result.get('stats', {}),
            'pages': result.get('structured', [])
        }
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        logger.info(f"💾 Сохранено JSON: {json_path}")
        
        return output_path

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def extract_pdf(pdf_path: str,
                max_pages: Optional[int] = None,
                save_output: bool = True,
                debug: bool = False,
                surya_first: bool = True,
                use_surya_batch: bool = True,
                min_confidence: float = 0.7,
                force_cpu: bool = False) -> Dict[str, Any]:
    """
     Быстрая функция извлечения PDF → текст (Surya-first)
    
    Args:
        pdf_path: Путь к PDF файлу
        max_pages: Максимум страниц (None = все)
        save_output: Сохранить ли в файл
        debug: Отладочный вывод
        surya_first: Использовать Surya как основной парсер
        use_surya_batch: Пакетная обработка Surya
        min_confidence: Порог уверенности для принятия результата

    Returns:
        Dict: {'success': bool, 'text': str, 'structured': list, 'stats': dict, 'error': str}
    """
    extractor = PDFToTextExtractor(
        max_pages=max_pages,
        debug=debug,
        surya_first=surya_first,
        use_surya_batch=use_surya_batch,
        min_confidence=min_confidence,
        force_cpu=force_cpu
    )
    result = extractor.extract(pdf_path)

    if result['success'] and save_output:
        output_path = extractor.save_to_file(result)
        result['output_file'] = str(output_path)

    return result

def _safe_print(msg: str):
    """Безопасный вывод в консоль (Windows-compatible)"""
    try:
        sys.stdout.write(msg + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="ignore"))
    sys.stdout.flush()
def extract_pdf_simple(input_path: str, output_dir: str, force_cpu: bool = False, use_surya_batch: Optional[bool] = None) -> Dict[str, Any]:
    """
     МАКСИМАЛЬНО ПРОСТАЯ ФУНКЦИЯ
    
    Просто передайте путь к файлу и папку для результатов.
    Всё остальное функция сделает сама.
    
    Args:
        input_path (str): Путь к PDF файлу
        output_dir (str): Папка для сохранения результатов
    
    Returns:
        Dict: {'success': bool, 'text': str, 'output_file': str, 'error': str}
    """
    from pathlib import Path
    
    # Проверка входного файла
    if not Path(input_path).exists():
        _safe_print(f"❌ Файл не найден: {input_path}")
        return {'success': False, 'text': '', 'error': 'File not found'}
    
    # Создание выходной папки
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    _safe_print(f"📄 Обработка: {input_path}")
    _safe_print(f"📁 Выходная папка: {output_dir}")
    
    # Запуск основной функции извлечения
    # Если не указан режим batch — используем поведение по умолчанию (True)
    if use_surya_batch is None:
        _use_surya_batch = True
    else:
        _use_surya_batch = bool(use_surya_batch)

    result = extract_pdf(
        pdf_path=input_path,
        max_pages=None,
        save_output=False,  # Мы сами сохраним ниже
        debug=False,
        surya_first=True,
        use_surya_batch=_use_surya_batch,
        min_confidence=0.7,
        force_cpu=force_cpu
    )
    
    # Сохранение результатов в указанную папку
    if result['success']:
        filename = Path(input_path).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # TXT файл
        txt_path = output_path / f"{filename}_{timestamp}.txt"
        txt_path.write_text(result['text'], encoding='utf-8')
        
        # JSON файл — сохраняем в полном формате (metadata + stats + pages)
        json_path = output_path / f"{filename}_{timestamp}.json"
        json_data = {
            'metadata': result.get('metadata', {}),
            'stats': result.get('stats', {}),
            'pages': result.get('structured', [])
        }
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        # Вывод в консоль (как в терминале)
        _safe_print("\n" + "="*70)
        _safe_print("✅ SUCCESS")
        _safe_print(f"  Файл: {result['filename']}")
        _safe_print(f"  Страниц: {result['total_pages']}")
        _safe_print(f"  Символов: {result['char_count']:,}")
        _safe_print(f"  Время: {result['extraction_time_sec']}s")
        _safe_print(f"  Coverage: {result['stats']['coverage_percent']}%")
        _safe_print(f"  Methods: {', '.join(result['stats']['methods'])}")
        _safe_print(f"  TXT: {txt_path}")
        _safe_print(f"  JSON: {json_path}")
        _safe_print("="*70)
        
        result['output_file'] = str(txt_path)
        result['json_file'] = str(json_path)
    else:
        _safe_print(f"\n❌ Error: {result.get('error', 'Unknown error')}")
    
    return result
# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
if __name__ == "__main__":
    result = extract_pdf_simple("input/IFRS_12m2023_summary.pdf", "output/")