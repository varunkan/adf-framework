/// Turns a tool call (name + raw JSON input) into a Cursor/Claude-style line:
/// "Reading lib/db.dart", "$ npm install", "Searching: bookmark table",
/// "Fetching fda.gov" — never the raw JSON. Shared by PlainThoughtFormatter (the
/// prose stream) and TraceSpan.body (the activity cards) so they read identically.
class ToolNarration {
  static String humanize(String? name, String? input) {
    final display = name ?? 'tool';
    final n = display.toLowerCase();

    if (n.contains('read')) return _withPath('Reading', input) ?? 'Reading a file';
    if (n.contains('write') || n.contains('create_file')) {
      return _withPath('Writing', input) ?? 'Writing a file';
    }
    if (n.contains('edit') || n.contains('str_replace') || n.contains('replace')) {
      return _withPath('Editing', input) ?? 'Editing a file';
    }
    if (n.contains('bash') || n.contains('exec') || n.contains('shell') ||
        n == 'run' || n.contains('command')) {
      final cmd = _key(input, const ['command', 'cmd']);
      return cmd != null ? '\$ ${_clip(cmd, 60)}' : 'Running a command';
    }
    if (n.contains('search') || n.contains('grep') || n.contains('glob') ||
        n.contains('find')) {
      final q = _key(input, const ['query', 'pattern', 'search', 'q']);
      return q != null ? 'Searching: ${_clip(q, 50)}' : 'Searching the code';
    }
    if (n.contains('fetch') || n.contains('web') || n.contains('url') ||
        n.contains('http') || n.contains('scrape')) {
      final u = _key(input, const ['url']);
      return u != null ? 'Fetching ${_domain(u)}' : 'Fetching a page';
    }
    final p = _path(input);
    return p != null ? 'Using $name · $p' : 'Using $name';
  }

  // --- helpers ---------------------------------------------------------------

  static String? _withPath(String verb, String? input) {
    final p = _path(input);
    return p == null ? null : '$verb $p';
  }

  /// Shorten a file_path to its last 3 segments.
  static String? _path(String? input) {
    final raw = _key(input, const ['file_path', 'path', 'filename', 'file']);
    if (raw == null) return null;
    final parts = raw.split('/');
    return parts.length > 3 ? '…/${parts.sublist(parts.length - 3).join('/')}' : raw;
  }

  /// First string value for any of [keys] in the JSON-ish [input].
  static String? _key(String? input, List<String> keys) {
    if (input == null || input.isEmpty) return null;
    for (final k in keys) {
      final m = RegExp('"' + k + r'"\s*:\s*"([^"]+)"').firstMatch(input);
      if (m != null) return m.group(1);
    }
    return null;
  }

  static String _domain(String url) {
    final m = RegExp(r'^[a-z]+://([^/]+)', caseSensitive: false).firstMatch(url);
    var host = m != null ? m.group(1)! : url;
    if (host.startsWith('www.')) host = host.substring(4);
    return host;
  }

  static String _clip(String s, int n) {
    final t = s.replaceAll(RegExp(r'\s+'), ' ').trim();
    return t.length <= n ? t : '${t.substring(0, n - 1)}…';
  }
}
