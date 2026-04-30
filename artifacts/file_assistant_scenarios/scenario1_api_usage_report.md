# Scenario 1: API Usage Map

## Pattern `/api/support/ask`

- scripts/run_file_assistant_scenarios.py:54:        r"/api/support/ask",
- frontend/src/api.ts:245:    await fetch("/api/support/ask", {
- api/main.py:1052:@app.post("/api/support/ask")

## Pattern `/api/mcp/file-assistant-demo`

- scripts/run_file_assistant_scenarios.py:55:        r"/api/mcp/file-assistant-demo",
- api/main.py:955:@app.post("/api/mcp/file-assistant-demo", response_model=MCPFileAssistantDemoOut)

## Pattern `/api/mcp/project-git-demo`

- scripts/run_file_assistant_scenarios.py:56:        r"/api/mcp/project-git-demo",
- api/main.py:859:@app.post("/api/mcp/project-git-demo", response_model=MCPProjectGitDemoOut)

Files involved: **3**
