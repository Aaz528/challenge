# Scenario 2: MCP File Invariants

Инварианты:
- файл MCP-сервера должен содержать `mcp = FastMCP(`
- файл MCP-сервера должен содержать `if __name__ == "__main__":`

- `mcp_servers/dadata_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/edu_pipeline_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/file_assistant_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/open_meteo_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/project_git_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/support_crm_mcp.py` -> OK (FastMCP=True, main_guard=True)
- `mcp_servers/yandex_geocoder_mcp.py` -> OK (FastMCP=True, main_guard=True)

Summary: 7/7 files passed.
