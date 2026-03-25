from __future__ import annotations

"""Session management for the ContaBot database.

Provides ``get_session`` as a context manager::

    with get_session() as session:
        session.query(Invoice).get(1)
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from contabot.db.models import SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a session and closes it on exit.

    Performs automatic rollback on exception.

    Yields:
        Session: SQLAlchemy session ready for queries.
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
