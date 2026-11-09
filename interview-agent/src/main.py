"""AgentCore Runtime entry point (CodeZip). Serves /ping, /invocations and /ws on port 8080.

AgentCore Runtime authenticates every request (SigV4 / OAuth) before it reaches this process,
so binding to all interfaces inside the runtime microVM is expected.
"""

import uvicorn

from interview_agent.app import create_default_app

if __name__ == "__main__":
    uvicorn.run(create_default_app(), host="0.0.0.0", port=8080, log_level="info")  # noqa: S104
