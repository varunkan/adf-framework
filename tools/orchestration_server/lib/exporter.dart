import 'dart:convert';
import 'dart:io';

/// Exports a generated app as a portable, self-verifying zip (source + sealed
/// audit bundle + Proof of Build) by shelling the canonical packager
/// (`scripts/orch/export_app.py`, stdlib zipfile). The ownership half of the moat:
/// your code, your machine, provable elsewhere. The zip is written under the
/// repo's `.adf-exports/` (outside the app, so re-exports never nest).
class Exporter {
  Exporter(this.repoRoot, {this.python = 'python3'});

  final String repoRoot;
  final String python;

  String appDir(String id) => '$repoRoot/apps/$id';
  String exportsDir() => '$repoRoot/.adf-exports';

  /// Build `<.adf-exports>/<id>.zip` embedding `auditBundle`. Returns
  /// `{ok, out, files, bytes}` or `{ok:false, error}`.
  Future<Map<String, dynamic>> export(
      String id, Map<String, dynamic>? auditBundle) async {
    if (!Directory(appDir(id)).existsSync()) {
      return {'ok': false, 'error': 'no app built for $id'};
    }
    final script = '$repoRoot/scripts/orch/export_app.py';
    if (!File(script).existsSync()) {
      return {'ok': false, 'error': 'exporter not found at $script'};
    }
    final dir = Directory(exportsDir())..createSync(recursive: true);
    final out = '${dir.path}/$id.zip';
    String? bundlePath;
    if (auditBundle != null) {
      bundlePath = '${dir.path}/$id.audit-bundle.json';
      File(bundlePath).writeAsStringSync(jsonEncode(auditBundle));
    }
    final args = <String>[
      script, '--app', appDir(id), '--out', out, '--id', id, '--json',
      if (bundlePath != null) ...['--bundle', bundlePath],
    ];
    try {
      final r = await Process.run(python, args);
      final o = (r.stdout as String).trim();
      if (o.isEmpty) {
        return {
          'ok': false,
          'error': 'exporter produced no output',
          'stderr': (r.stderr as String).trim(),
        };
      }
      return jsonDecode(o) as Map<String, dynamic>;
    } catch (e) {
      return {'ok': false, 'error': 'export failed: $e'};
    }
  }
}
