"""Phase E: the AI Job Assistant MCP server.

Re-exposes the four Phase C tools over the Model Context Protocol so a host such
as Claude Desktop can orchestrate them. Run with `python -m app.mcp_server`.
"""
from app.mcp_server.server import mcp

__all__ = ["mcp"]