import logging
from contextvars import ContextVar
from typing import Final, override

PARSER_WARNING: Final = ContextVar("pdf_parser_warning", default=False)


class PdfDiagnosticHandler(logging.Handler):
    """Retain a request-local warning flag without emitting document-derived log text."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            _ = PARSER_WARNING.set(True)


PDF_LOGGER: Final = logging.getLogger("pypdf")
PDF_LOGGER.setLevel(logging.WARNING)
PDF_LOGGER.addHandler(PdfDiagnosticHandler())
PDF_LOGGER.propagate = False
