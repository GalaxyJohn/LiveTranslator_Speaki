from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication


def _prepare_runtime() -> None:
    # Avoid .pyc write/rename failures in locked __pycache__ folders.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    # Remove stale temporary pyc files like *.pyc.123456 left by failed rename.
    root = Path(__file__).resolve().parent
    for pycache_dir in root.rglob("__pycache__"):
        for tmp_pyc in pycache_dir.glob("*.pyc.*"):
            try:
                tmp_pyc.unlink(missing_ok=True)
            except Exception:
                pass


def _configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "speaki.log"

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)


def main() -> None:
    _prepare_runtime()
    _configure_logging()

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)

    # Keep controls flat as requested.
    app.setStyleSheet(
        """
        QLineEdit, QComboBox, QPushButton, QPlainTextEdit, QTextEdit {
            border-radius: 0px;
        }
    """
    )

    window = MainWindow()
    window.resize(900, 600)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # Required for Windows frozen apps using multiprocessing (PyInstaller).
    multiprocessing.freeze_support()
    main()