__all__ = []

# Попытки импортировать экспортируемые функции безопасно — без ошибки при отсутствии файлов
try:
	from .main_pdf_parser import extract_text_from_pdf
	__all__.append("extract_text_from_pdf")
except Exception:
	extract_text_from_pdf = None

try:
	from .main_pdf_parser1 import extract_pdf_simple, main_result_parsing
	__all__.extend(["extract_pdf_simple", "main_result_parsing"])
except Exception:
	# fallback: попробуем взять extract_pdf_simple прямо из pdf_to_text_extractor_main
	try:
		from .pdf_to_text_extractor_main import extract_pdf_simple
		__all__.append("extract_pdf_simple")
	except Exception:
		extract_pdf_simple = None
	main_result_parsing = None
