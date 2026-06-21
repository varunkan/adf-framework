import 'dart:convert';
import 'dart:io';

/// Resolves orchestration directory for ADF v3 (Cursor, VS Code, Claude, generic).
class OrchestrationPaths {
  OrchestrationPaths(this.repoRoot);

  final String repoRoot;

  static const _legacyRelative = '.cursor/orchestration';
  static const _packageRelative = 'adf-framework/orchestration';
  static const _genericRelative = '.adf/orchestration';

  late final String orchestrationRoot = _resolveOrchestrationRoot();
  late final String featuresRoot = '$orchestrationRoot/features';
  late final String orchestrationPrefix = _relativeFromRepo(orchestrationRoot);

  String featureRel(String featureId, String file) =>
      '$orchestrationPrefix/features/$featureId/$file';

  String get otelTracesFile => '$orchestrationRoot/otel-traces.jsonl';

  String featureOtelTracesFile(String featureId) =>
      '$featuresRoot/$featureId/otel-traces.jsonl';

  String get frameworkRoutingYaml => '$orchestrationRoot/framework-routing.yaml';

  static bool hasOrchestrationAt(String repoRoot) {
    for (final rel in [_legacyRelative, _packageRelative, _genericRelative]) {
      if (Directory('$repoRoot/$rel').existsSync()) return true;
    }
    final install = File('$repoRoot/.adf-install.json');
    if (install.existsSync()) {
      try {
        final j = jsonDecode(install.readAsStringSync()) as Map<String, dynamic>;
        final dir = j['orchestration_dir'] as String?;
        if (dir != null && Directory('$repoRoot/$dir').existsSync()) return true;
      } catch (_) {}
    }
    return false;
  }

  String _resolveOrchestrationRoot() {
    final env = Platform.environment['ORCH_ORCHESTRATION_DIR'];
    if (env != null && env.isNotEmpty) {
      return Directory(env).absolute.path;
    }

    final install = _readInstallManifest();
    if (install != null) {
      final dir = install['orchestration_dir'] as String?;
      if (dir != null && dir.isNotEmpty) {
        final abs = _absUnderRepo(dir);
        if (Directory(abs).existsSync()) return abs;
      }
    }

    // CURSOR-6: prefer the new `.adf/orchestration` default; `.cursor/orchestration`
    // remains a legacy fallback so an un-migrated install still resolves (no data loss).
    for (final rel in [_genericRelative, _legacyRelative, _packageRelative]) {
      final abs = '$repoRoot/$rel';
      if (Directory(abs).existsSync()) return abs;
    }

    return '$repoRoot/$_genericRelative';
  }

  /// CURSOR-6: one-time, NO-LOSS migration of the legacy `.cursor/orchestration`
  /// data dir to the new default `.adf/orchestration`. Non-destructive: it COPIES
  /// (the legacy dir is left in place as a backup) and is idempotent — a no-op when
  /// `.adf/orchestration` already exists or there is no legacy dir. Returns true if
  /// it migrated. Wired into the server startup so existing installs move forward
  /// automatically without the operator's 28 features ever appearing to vanish.
  static bool migrateLegacyIfNeeded(String repoRoot) {
    final adf = Directory('$repoRoot/$_genericRelative');
    final legacy = Directory('$repoRoot/$_legacyRelative');
    if (adf.existsSync() || !legacy.existsSync()) return false;
    _copyDir(legacy, adf);
    return true;
  }

  static void _copyDir(Directory src, Directory dst) {
    dst.createSync(recursive: true);
    for (final e in src.listSync()) {
      final name = e.path.split(Platform.pathSeparator).last;
      if (e is Directory) {
        _copyDir(e, Directory('${dst.path}/$name'));
      } else if (e is File) {
        e.copySync('${dst.path}/$name');
      }
      // symlinks intentionally skipped
    }
  }

  Map<String, dynamic>? _readInstallManifest() {
    final file = File('$repoRoot/.adf-install.json');
    if (!file.existsSync()) return null;
    try {
      return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  String _absUnderRepo(String path) {
    if (path.startsWith('/')) return path;
    return '$repoRoot/$path';
  }

  String _relativeFromRepo(String absolute) {
    final normRepo = Directory(repoRoot).absolute.path;
    final normAbs = Directory(absolute).absolute.path;
    if (normAbs.startsWith('$normRepo${Platform.pathSeparator}')) {
      return normAbs.substring(normRepo.length + 1);
    }
    if (normAbs.startsWith('$normRepo/')) {
      return normAbs.substring(normRepo.length + 1);
    }
    return absolute;
  }
}

String resolveRepoRoot() {
  final env = Platform.environment['ORCH_REPO_ROOT'];
  if (env != null && env.isNotEmpty) {
    return Directory(env).absolute.path;
  }
  var dir = Directory.current.absolute;
  for (var i = 0; i < 10; i++) {
    if (OrchestrationPaths.hasOrchestrationAt(dir.path)) {
      return dir.path;
    }
    final parent = dir.parent;
    if (parent.path == dir.path) break;
    dir = parent;
  }
  throw StateError(
    'Could not find ADF orchestration root. Set ORCH_REPO_ROOT or run: adf install',
  );
}
