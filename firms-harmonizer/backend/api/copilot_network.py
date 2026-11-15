"""Request-local offline override: one failed provider must not mutate other requests."""
from contextlib import contextmanager
from contextvars import ContextVar
import os

_FORCED=ContextVar('copilot_offline',default=False)


def is_forced_offline():
    return _FORCED.get()


def is_offline():
    return _FORCED.get() or os.getenv('COPILOT_OFFLINE')=='1'


@contextmanager
def offline_context():
    token=_FORCED.set(True)
    try:
        yield
    finally:
        _FORCED.reset(token)
