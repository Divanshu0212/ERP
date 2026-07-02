"""Django model registry for the ``suerp_common`` app.

Models live in their functional modules (``outbox``, ``inbox``); this module
re-exports them so Django's app loader discovers them.
"""

from .inbox import ProcessedEvent
from .outbox import OutboxEvent

__all__ = ["OutboxEvent", "ProcessedEvent"]
