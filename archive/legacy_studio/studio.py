"""
OrionFlow Studio launcher.

The studio is implemented in the ``studio_app`` package; this file is just a
thin entry point so existing instructions (``python studio.py``) keep working.

Run:
    python studio.py

Then open: http://127.0.0.1:7860
"""
from __future__ import annotations

import uvicorn

from studio_app.app import app  # re-export for ``uvicorn studio:app`` users


def main() -> None:
    host = "127.0.0.1"
    port = 7860
    print(f"\n  OrionFlow Studio  ->  http://{host}:{port}\n")
    uvicorn.run("studio_app.app:app", host=host, port=port, log_level="info", reload=False)


if __name__ == "__main__":
    main()
