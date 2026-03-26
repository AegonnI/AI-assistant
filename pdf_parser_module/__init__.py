__all__ = []

# Экспортируем основной экстрактор напрямую из pdf_to_text_extractor_main
try:
	from .pdf_to_text_extractor_main import extract_pdf_simple, extract_pdf
	__all__.extend(["extract_pdf_simple", "extract_pdf"]) 
except Exception:
	# Если по какой-то причине основной модуль недоступен — попробуем старые варианты
	try:
		from .main_pdf_parser1 import extract_pdf_simple, main_result_parsing
		__all__.extend(["extract_pdf_simple", "main_result_parsing"])
	except Exception:
		extract_pdf_simple = None
		extract_pdf = None
		main_result_parsing = None
