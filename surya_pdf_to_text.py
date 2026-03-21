"""
surya_pdf_to_text.py
---------------------

Экспериментальный конвертер PDF → текст на базе Surya OCR.

ВАЖНО:
- Не использует твой основной PDFConverter, ничего в нём не меняет.
- Требует установленных зависимостей:
    pip install "surya-ocr>=0.17.1" torch pillow pymupdf
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional


def _safe_print(msg: str) -> None:
    try:
        text = str(msg)
    except Exception:
        text = repr(msg)
    # Windows-консоль может быть в cp1252/cp866 → печатаем безопасно
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        # Пишем напрямую в stdout.buffer, минуя текущую кодировку консоли
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="ignore"))
    sys.stdout.flush()


def _ensure_deps() -> bool:
    """
    Проверяем только наличие CLI-утилиты surya_ocr.
    Так мы не завязаны на внутреннюю структуру Python-пакета,
    которая может меняться между версиями.
    """
    # Важно: запускать именно surya_ocr из venv, иначе он может подняться
    # из глобального Python и "не видеть" torch/зависимости.
    venv_scripts = Path(sys.executable).parent
    exe = venv_scripts / ("surya_ocr.exe" if os.name == "nt" else "surya_ocr")
    if not exe.exists():
        _safe_print(f"[ERROR] Не найден {exe}")
        _safe_print("Похоже, surya-ocr не установлен в этом venv. Установи так:")
        _safe_print("  python -m pip install \"surya-ocr>=0.17.1\"")
        return False
    return True


def _parse_page_range_first_n(max_pages: Optional[int]) -> Optional[str]:
    """
    Surya CLI использует 0-based индексацию страниц.
    Для первых N страниц -> диапазон "0-(N-1)".
    """
    if not max_pages:
        return None
    if max_pages <= 0:
        return None
    return f"0-{max_pages - 1}"


def run_surya_ocr_on_pdf(
    pdf_path: Path,
    max_pages: int | None = None,
    output_dir: Optional[Path] = None,
    debug: bool = True,
) -> Path:
    """
    Запускает CLI-утилиту surya_ocr напрямую по PDF.
    Возвращает stdout как текст и путь к output_dir, куда surya сохранит артефакты.
    """
    import subprocess

    if output_dir is None:
        output_dir = Path("output") / "surya_first_pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    page_range = _parse_page_range_first_n(max_pages)

    cmd = ["surya_ocr", "--output_dir", str(output_dir)]
    if debug:
        cmd.append("-d")
    if page_range:
        cmd.extend(["--page_range", page_range])
    cmd.append(str(pdf_path))

    # Запускаем surya_ocr именно из текущего venv
    venv_scripts = Path(sys.executable).parent
    surya_exe = venv_scripts / ("surya_ocr.exe" if os.name == "nt" else "surya_ocr")
    cmd[0] = str(surya_exe)

    _safe_print(f"[INFO] Выполняю: {' '.join(cmd)}")
    env = os.environ.copy()
    # Просим torch/Surya использовать GPU (если доступен)
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    # Чтобы кэш моделей лежал в проекте (и было понятно, что качается)
    env.setdefault("HF_HOME", str(Path("output") / "hf_cache"))

    # Запускаем так, чтобы видеть прогресс (скачивание моделей/обработка страниц)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,  # не сохраняем stdout (там часто JSON/служебное)
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
        universal_newlines=True,
    )

    assert proc.stderr is not None
    stderr_chunks: List[str] = []
    for line in iter(proc.stderr.readline, ""):
        if not line:
            break
        stderr_chunks.append(line)
        _safe_print(line.rstrip("\n"))

    rc = proc.wait()
    stderr_text = "".join(stderr_chunks)

    (output_dir / "surya_stderr.log").write_text(stderr_text, encoding="utf-8", errors="ignore")

    if rc != 0:
        _safe_print("[ERROR] surya_ocr завершился с ошибкой.")
        if stderr_text.strip():
            _safe_print(stderr_text[-4000:])
        raise SystemExit(rc)

    return output_dir


def extract_text_from_results_json(
    results_json_path: Path,
    max_pages: Optional[int] = None,
) -> str:
    """
    Превращает output Surya (results.json) в обычный .txt.
    """
    import json
    import re

    raw = results_json_path.read_text(encoding="utf-8", errors="ignore")
    data = json.loads(raw)

    root_key = results_json_path.parent.name
    if root_key not in data:
        root_key = next(iter(data.keys()))

    pages = data.get(root_key) or []
    if max_pages:
        pages = pages[:max_pages]

    page_texts: List[str] = []
    y_tol = 6.0

    for page_idx, page_pred in enumerate(pages):
        items = []
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

        items.sort(key=lambda z: (z[0], z[1]))

        # Группируем сегменты в строки по близости Y
        lines: List[str] = []
        cur_y: Optional[float] = None
        cur_parts: List[str] = []
        for y, _x, t in items:
            if cur_y is None or abs(y - cur_y) <= y_tol:
                cur_parts.append(t)
                cur_y = y if cur_y is None else (cur_y * 0.7 + y * 0.3)
            else:
                lines.append(" ".join(cur_parts))
                cur_parts = [t]
                cur_y = y
        if cur_parts:
            lines.append(" ".join(cur_parts))

        # аккуратная очистка
        page_text = "\n".join(lines)
        page_text = re.sub(r"[ \t]{2,}", " ", page_text).strip()

        page_texts.append(f"[[PAGE:{page_idx + 1}]]\n{page_text}")

    return "\n\n".join(page_texts).strip()


def main() -> None:
    if len(sys.argv) < 2:
        _safe_print("Usage: python surya_pdf_to_text.py input/IFRS_12m2023_summary.pdf [max_pages]")
        sys.exit(1)

    if not _ensure_deps():
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        _safe_print(f"[ERROR] File not found: {pdf_path}")
        sys.exit(1)

    max_pages = None
    if len(sys.argv) >= 3:
        try:
            max_pages = int(sys.argv[2])
        except ValueError:
            _safe_print(f"[WARN] Не удалось разобрать max_pages='{sys.argv[2]}', игнорирую.")

    _safe_print(
        "[INFO] Если это первый запуск Surya, она может молчать несколько минут: "
        "в это время скачиваются веса моделей в кэш (HF_HOME)."
    )

    out_dir = run_surya_ocr_on_pdf(
        pdf_path,
        max_pages=max_pages,
        output_dir=Path("output") / "surya_first10",
        debug=False,
    )

    results_json = out_dir / pdf_path.stem / "results.json"
    if not results_json.exists():
        raise SystemExit(f"[ERROR] Не найден results.json: {results_json}")

    text = extract_text_from_results_json(results_json, max_pages=max_pages)

    if not text or not text.strip():
        raise SystemExit("[ERROR] Извлечённый текст пустой. Проверь results.json и попробуй debug=True.")

    suffix = max_pages if max_pages else "all"
    out_path = Path("output") / f"{pdf_path.stem}_surya_first{suffix}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    _safe_print(f"[OK] Surya текст сохранён в: {out_path}")
    _safe_print(f"[OK] артефакты surya_ocr в папке: {out_dir}")
    _safe_print(f"Chars: {len(text)}")


if __name__ == "__main__":
    main()

