import 'dart:convert';
import 'dart:io';

/// Raised when the orchestration API is unreachable or replies with a
/// non-success status. The [message] is written for an agent operator and
/// already contains the recovery action.
class OrchApiException implements Exception {
  OrchApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Minimal JSON client for the orchestration HTTP API.
///
/// The base URL comes from `ORCH_API_URL` (default `http://127.0.0.1:3847`);
/// tests inject their own server via [baseUrl]. Only `dart:io` is used so the
/// MCP server stays dependency-free.
class OrchHttpProxy {
  OrchHttpProxy({String? baseUrl})
      : baseUrl = _stripTrailingSlash(baseUrl ??
            Platform.environment['ORCH_API_URL'] ??
            'http://127.0.0.1:3847');

  /// Root of the orchestration API, without a trailing slash.
  final String baseUrl;

  static String _stripTrailingSlash(String url) =>
      url.endsWith('/') ? url.substring(0, url.length - 1) : url;

  /// GET [path] (must start with `/`) and return the decoded JSON body.
  Future<Object?> getJson(String path) => _request('GET', path);

  /// POST [body] as JSON to [path] and return the decoded JSON body.
  Future<Object?> postJson(String path, [Map<String, dynamic>? body]) =>
      _request('POST', path, body: body);

  Future<Object?> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await client.openUrl(method, uri);
      request.headers.contentType = ContentType.json;
      if (body != null) request.write(jsonEncode(body));
      final response = await request.close();
      final text = await response.transform(utf8.decoder).join();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final detail = text.trim().isEmpty ? '(empty body)' : text.trim();
        throw OrchApiException(
            'Orchestration API returned HTTP ${response.statusCode} for '
            '$method $path: $detail');
      }
      if (text.trim().isEmpty) return null;
      try {
        return jsonDecode(text);
      } on FormatException {
        return text;
      }
    } on OrchApiException {
      rethrow;
    } on IOException catch (e) {
      throw OrchApiException(
          'Cannot reach the orchestration API at $baseUrl ($e). '
          'Start it with `adf start api`, or point ORCH_API_URL at a '
          'running instance.');
    } finally {
      client.close(force: true);
    }
  }
}
