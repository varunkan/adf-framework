import 'dart:convert';
import 'dart:io';

/// Read-only window into a generated app's live SQLite DB for the dashboard
/// **Data tab**. Shells the canonical browser (`scripts/orch/app_data.py`, stdlib
/// sqlite3, opened `mode=ro`) so the data math lives in one tested, injection-safe
/// place — ADF owns the data layer, so it can show you what your app persisted.
class AppData {
  AppData(this.repoRoot, {this.python = 'python3'});

  final String repoRoot;
  final String python;

  String appDir(String id) => '$repoRoot/apps/$id';

  /// `{has_db, db, tables:[{name, rows}]}`.
  Future<Map<String, dynamic>> tables(String id) => _run(id, null, null);

  /// `{has_db, db, table, columns:[...], rows:[[...]], truncated}` or an `error`.
  Future<Map<String, dynamic>> rows(String id, String table, {int? limit}) =>
      _run(id, table, limit);

  Future<Map<String, dynamic>> _run(String id, String? table, int? limit) async {
    final script = '$repoRoot/scripts/orch/app_data.py';
    if (!File(script).existsSync()) {
      return {'has_db': false, 'error': 'browser not found at $script'};
    }
    final args = <String>[
      script, '--app', appDir(id), '--json',
      if (table != null) ...['--table', table],
      if (limit != null) ...['--limit', '$limit'],
    ];
    try {
      final r = await Process.run(python, args);
      final out = (r.stdout as String).trim();
      if (out.isEmpty) {
        return {
          'has_db': false,
          'error': 'browser produced no output',
          'stderr': (r.stderr as String).trim(),
        };
      }
      return jsonDecode(out) as Map<String, dynamic>;
    } catch (e) {
      return {'has_db': false, 'error': 'data browse failed: $e'};
    }
  }
}
