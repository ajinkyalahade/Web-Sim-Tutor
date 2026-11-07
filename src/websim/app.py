"""Command line entry point and Qt bootstrap."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import traceback

from . import APP_NAME, __version__
from .paths import log_file


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)
    logging.getLogger("websim").setLevel(level)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websim", description="WebSim — virtual camera studio for tutors")
    parser.add_argument("file", nargs="?", help="video, PDF or image to open on startup")
    parser.add_argument("--test-pattern", action="store_true", help="start with a camera test pattern and a 440 Hz tone")
    parser.add_argument("--preview-only", action="store_true", help="never open the virtual camera")
    parser.add_argument("--doctor", action="store_true", help="print a setup/readiness report and exit")
    parser.add_argument("--no-global-shortcuts", action="store_true", help="do not start pynput global shortcuts")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"WebSim {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    if args.doctor:
        from .doctor import report

        print(report())
        return 0

    # Qt's macOS plugin wants to live in the main thread, which it is.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .config import SettingsStore
    from .ui.main_window import MainWindow
    from .ui.style import apply_theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("WebSim")
    app.setOrganizationName("WebSim")
    apply_theme(app)

    store = SettingsStore()
    if args.no_global_shortcuts:
        store.settings.global_shortcuts = False
    if args.preview_only:
        store.settings.monitor_enabled = False

    window = MainWindow(store, preview_only=args.preview_only)
    window.show()

    def boot() -> None:
        try:
            window.start(test_pattern=args.test_pattern, open_path=args.file)
        except Exception:  # noqa: BLE001
            logging.exception("Startup failed")
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                window,
                "WebSim could not start",
                "WebSim hit an error while starting. Details were written to\n"
                f"{log_file()}\n\n{traceback.format_exc(limit=3)}",
            )

    QTimer.singleShot(0, boot)

    def excepthook(exc_type, exc_value, exc_tb) -> None:
        logging.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
