from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen


class _NullStream:
    """Write sink used when stdout/stderr are absent in windowed EXE runs."""

    def write(self, _data: str) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _prepare_runtime() -> None:
    # Avoid .pyc write/rename failures in locked __pycache__ folders.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    # In --windowed frozen mode, std streams can be None.
    # Some dependencies (e.g. torch.hub) call sys.stdout.write directly.
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()

    # Keep torch hub cache in user-local storage, not beside the EXE.
    # This avoids missing/corrupted model paths in packaged runs.
    local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    torch_home = local_appdata / "Speaki" / "torch"
    try:
        torch_home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TORCH_HOME", str(torch_home))
    except Exception:
        pass

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


def _create_splash() -> QSplashScreen:
    pixmap = QPixmap(500, 280)
    pixmap.fill(QColor("#151821"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QColor("#2a2f3a"))
    painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1)

    painter.setPen(QColor("#f0f3f9"))
    title_font = QFont("Segoe UI", 24)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(0, 95, pixmap.width(), 40, int(Qt.AlignHCenter), "Speaki")

    msg_font = QFont("Segoe UI", 11)
    painter.setFont(msg_font)
    painter.setPen(QColor("#b9c2d0"))
    painter.drawText(0, 215, pixmap.width(), 24, int(Qt.AlignHCenter), "Initializing modules...")

    painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.showMessage(
        "Loading...",
        int(Qt.AlignHCenter | Qt.AlignBottom),
        QColor("#c7d0dd"),
    )
    return splash


def main() -> None:
    _prepare_runtime()
    _configure_logging()

    app = QApplication(sys.argv)

    icon_path = Path(__file__).resolve().parent / "speaki.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash = _create_splash()
    splash.show()
    app.processEvents()

    from ui.main_window import MainWindow

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
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    # Required for Windows frozen apps using multiprocessing (PyInstaller).
    multiprocessing.freeze_support()
    main()
