from __future__ import annotations

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from employee_core import PDF_DIR, TRANSPORT_SECURITY, initialize_csv
from employee_mcp import mcp
import employee_tools  # noqa: F401 - import 시 MCP 도구가 등록됩니다.


initialize_csv()

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    host="0.0.0.0",
    transport_security=TRANSPORT_SECURITY,
)

app = Starlette(
    routes=[
        *mcp_app.routes,
        Mount("/pdf", app=StaticFiles(directory=str(PDF_DIR)), name="pdf"),
    ],
    lifespan=mcp_app.router.lifespan_context,
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
