"""
Event loop policy configuration.

psycopg's async driver cannot run on Windows' default ProactorEventLoop:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to
    run in async mode.

Since the FastAPI runtime is intentionally async
(FastAPI -> SQLAlchemy Async -> psycopg -> PostgreSQL), the selector-based
policy must be installed before any event loop is created. Importing
``app.db.session`` triggers this, so every entry point that reaches the
database (uvicorn, pytest, seed scripts) is covered.

Alembic is unaffected: it runs on a synchronous engine by design.
"""

import asyncio
import sys


def install_windows_event_loop_policy() -> bool:
    """
    Install the selector event loop policy on Windows.

    Returns True if the policy was installed, False on other platforms
    (where the default policy already works with psycopg).
    """
    if sys.platform != "win32":
        return False

    policy = asyncio.get_event_loop_policy()
    if isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):
        return True

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return True
