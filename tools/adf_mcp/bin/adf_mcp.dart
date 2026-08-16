import 'dart:convert';
import 'dart:io';

import 'package:adf_mcp/mcp_server.dart';

/// Stdio entry point for the ADF MCP server: newline-delimited JSON-RPC 2.0
/// on stdin/stdout. Point it at the orchestration API with ORCH_API_URL
/// (default http://127.0.0.1:3847) and register it in your MCP client — see
/// tools/adf_mcp/README.md.
Future<void> main() async {
  final server = AdfMcpServer(
    input: stdin.transform(utf8.decoder).transform(const LineSplitter()),
    output: stdout,
  );
  await server.serve();
}
