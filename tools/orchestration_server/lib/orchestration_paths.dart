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

    for (final rel in [_legacyRelative, _packageRelative, _genericRelative]) {
      final abs = '$repoRoot/$rel';
      if (Directory(abs).existsSync()) return abs;
    }

    return '$repoRoot/$_legacyRelative';
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
