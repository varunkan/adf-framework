# adf_mcp

Stdio MCP server that lets any MCP client (Claude Code, Cursor, etc.) drive
the whole ADF pipeline as tools: create features, run autopilot, approve
gates, check runner health, track cost, verify integrity chains, and export
audit bundles. It speaks newline-delimited JSON-RPC 2.0 on stdin/stdout and
proxies every tool call to the orchestration HTTP API at `ORCH_API_URL`
(default `http://127.0.0.1:3847`) — start that API first with `adf start api`.

Runtime needs only the Dart SDK (`dart:io` + `dart:convert`, zero pub
dependencies). Register it in your client's `.mcp.json`, replacing
`<repo>` with this repository's absolute path:

```json
{
  "mcpServers": {
    "adf": {
      "command": "dart",
      "args": ["run", "<repo>/tools/adf_mcp/bin/adf_mcp.dart"]
    }
  }
}
```

Develop: `dart pub get && dart analyze . && dart test` (dev-only deps).
