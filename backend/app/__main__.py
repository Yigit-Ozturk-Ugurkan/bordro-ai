"""Windows-safe development entry point for the Bordro AI API."""

import asyncio
import selectors
import sys

import uvicorn


def _selector_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def main() -> None:
    """Run Uvicorn with a psycopg-compatible selector loop on Windows."""
    if sys.platform != "win32":
        uvicorn.run("app.main:app", host="127.0.0.1", port=8001)
        return

    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        loop="none",
    )
    server = uvicorn.Server(config)
    with asyncio.Runner(loop_factory=_selector_loop) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()
