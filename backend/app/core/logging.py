"""Logging con identificador de petición en cada línea."""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_HANDLER_NAME = "app-console"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(request_id)s | %(name)s | %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx registra cada petición en INFO; no aporta y ensucia el log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
