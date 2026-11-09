"""AWS Lambda entrypoint: runs the FastAPI app behind API Gateway (HTTP API).

Mangum adapts API Gateway events to ASGI. ``lifespan="off"`` because the app defines no
startup/shutdown handlers and Lambda has no long-lived process to run them in.
"""

from __future__ import annotations

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
