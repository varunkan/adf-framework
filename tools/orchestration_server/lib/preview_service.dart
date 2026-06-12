import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:shelf/shelf.dart';

import 'artifact_validator.dart';
import 'feature_store.dart';
import 'integrity_chain.dart';

/// Background flutter web build job (feature-flagged via [previewBuildEnabled]).
class _PreviewBuildJob {
  _PreviewBuildJob({required this.status, this.startedAt});

  String status;
  String? error;
  DateTime? startedAt;
  DateTime? finishedAt;
}

/// Studio preview payload: spec excerpt, integrity, crew progress, product URL.
class PreviewService {
  PreviewService(
    this.store,
    this.repoRoot, {
    required this.integrity,
    required this.validator,
    this.apiPort = 3847,
  });

  final FeatureStore store;
  final String repoRoot;
  final IntegrityChain integrity;
  final ArtifactValidator validator;
  final int apiPort;

  final Map<String, _PreviewBuildJob> _buildJobs = {};

  /// Zero-risk: preview builds off unless explicitly enabled.
  bool get previewBuildEnabled {
    final v = Platform.environment['ORCH_PREVIEW_BUILD'];
    return v == 'true' || v == '1';
  }

  /// Maps a feature id to a `products/` directory when one exists.
  String? resolveProduct(String featureId) {
    final root = Directory('$repoRoot/products');
    if (!root.existsSync()) return null;
    final exact = Directory('${root.path}/$featureId');
    if (exact.existsSync()) return featureId;
    final underscored = featureId.replaceAll('-', '_');
    if (Directory('${root.path}/$underscored').existsSync()) {
      return underscored;
    }
    for (final entity in root.listSync(followLinks: false)) {
      if (entity is! Directory) continue;
      final name = entity.path.split('/').last;
      if (name.replaceAll('_', '-') == featureId) return name;
    }
    return null;
  }

  String? readSpecExcerpt(String id, {int maxChars = 1200}) {
    final spec = File('$repoRoot/specs/$id/spec.md');
    if (!spec.existsSync()) return null;
    final text = spec.readAsStringSync().trim();
    if (text.isEmpty) return null;
    if (text.length <= maxChars) return text;
    return '${text.substring(0, maxChars).trimRight()}…';
  }

  String? readCodeExcerpt(String productId, {int maxLines = 40}) {
    final lib = Directory('$repoRoot/products/$productId/lib');
    if (!lib.existsSync()) return null;
    File? target;
    for (final entity in lib.listSync(recursive: true, followLinks: false)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final name = entity.path.split('/').last;
      if (name == 'main.dart' ||
          name.endsWith('_screen.dart') ||
          name.endsWith('_page.dart')) {
        target = entity;
        if (name != 'main.dart') break;
      }
    }
    if (target == null) {
      for (final entity in lib.listSync(recursive: true, followLinks: false)) {
        if (entity is File && entity.path.endsWith('.dart')) {
          target = entity;
          break;
        }
      }
    }
    if (target == null || !target.existsSync()) return null;
    final rel = target.path.replaceFirst('$repoRoot/', '');
    final lines = target.readAsLinesSync();
    final excerpt = lines.take(maxLines).join('\n');
    final suffix = lines.length > maxLines ? '\n// …' : '';
    return '//$rel\n$excerpt$suffix';
  }

  /// Resolve where a flutter web build should run for this feature.
  Map<String, dynamic> resolvePreviewTarget(String featureId) {
    final product = resolveProduct(featureId);
    if (product != null) {
      return {
        'kind': 'product',
        'id': product,
        'root': '$repoRoot/products/$product',
        'slug': product,
      };
    }
    if (File('$repoRoot/lib/main.dart').existsSync()) {
      return {
        'kind': 'pos',
        'id': 'pos',
        'root': repoRoot,
        'slug': 'pos',
      };
    }
    return {'kind': 'none'};
  }

  String _webRootForSlug(String slug) {
    if (slug == 'pos') return '$repoRoot/build/web';
    return '$repoRoot/products/$slug/build/web';
  }

  bool webBuildReadyForSlug(String slug) {
    return File('${_webRootForSlug(slug)}/index.html').existsSync();
  }

  bool productWebBuildReady(String productId) {
    return webBuildReadyForSlug(productId);
  }

  String? previewUrlForSlug(String slug) {
    if (!webBuildReadyForSlug(slug)) return null;
    return 'http://127.0.0.1:$apiPort/preview/$slug/';
  }

  String? previewUrl(String productId) => previewUrlForSlug(productId);

  String _buildJobKey(Map<String, dynamic> target) {
    return '${target['kind']}:${target['id']}';
  }

  Map<String, dynamic> buildStatus(String featureId) {
    final target = resolvePreviewTarget(featureId);
    final kind = target['kind'] as String? ?? 'none';
    if (kind == 'none') {
      return {
        'enabled': previewBuildEnabled,
        'status': 'unavailable',
        'preview_url': null,
        'target': target,
      };
    }
    final slug = target['slug'] as String;
    final key = _buildJobKey(target);
    final job = _buildJobs[key];
    final ready = webBuildReadyForSlug(slug);
    var status = job?.status ?? (ready ? 'ready' : 'idle');
    if (status == 'building' && ready) status = 'ready';
    return {
      'enabled': previewBuildEnabled,
      'status': status,
      'error': job?.error,
      'started_at': job?.startedAt?.toUtc().toIso8601String(),
      'finished_at': job?.finishedAt?.toUtc().toIso8601String(),
      'preview_url': previewUrlForSlug(slug),
      'web_build_ready': ready,
      'target': target,
    };
  }

  /// Kick off a background `flutter build web` when [previewBuildEnabled].
  Future<Map<String, dynamic>> kickoffBuild(String featureId) async {
    final target = resolvePreviewTarget(featureId);
    if (target['kind'] == 'none') {
      return {
        'ok': false,
        'enabled': previewBuildEnabled,
        'error': 'No Flutter preview target for this feature',
        'target': target,
      };
    }
    if (!previewBuildEnabled) {
      return {
        'ok': false,
        'enabled': false,
        'status': 'disabled',
        'message':
            'Set ORCH_PREVIEW_BUILD=1 on the API server to enable preview builds.',
        'target': target,
        'preview_url': previewUrlForSlug(target['slug'] as String),
      };
    }
    final key = _buildJobKey(target);
    final existing = _buildJobs[key];
    if (existing?.status == 'building') {
      return {
        'ok': true,
        'status': 'building',
        'target': target,
        ...buildStatus(featureId),
      };
    }
    _buildJobs[key] = _PreviewBuildJob(
      status: 'building',
      startedAt: DateTime.now(),
    );
    unawaited(_runFlutterWebBuild(featureId, target, key));
    return {
      'ok': true,
      'status': 'building',
      'target': target,
      ...buildStatus(featureId),
    };
  }

  Future<void> _runFlutterWebBuild(
    String featureId,
    Map<String, dynamic> target,
    String key,
  ) async {
    try {
      final root = target['root'] as String;
      final result = await Process.run(
        'flutter',
        ['build', 'web', '--release'],
        workingDirectory: root,
        runInShell: true,
      ).timeout(const Duration(minutes: 8));
      final job = _buildJobs[key];
      if (job == null) return;
      if (result.exitCode == 0) {
        job.status = 'ready';
        job.finishedAt = DateTime.now();
        job.error = null;
      } else {
        job.status = 'error';
        job.finishedAt = DateTime.now();
        job.error = (result.stderr as String).trim().isNotEmpty
            ? (result.stderr as String).trim()
            : 'flutter build web failed (exit ${result.exitCode})';
      }
    } on TimeoutException {
      final job = _buildJobs[key];
      if (job != null) {
        job.status = 'error';
        job.finishedAt = DateTime.now();
        job.error = 'Preview build timed out after 8 minutes';
      }
    } catch (e) {
      final job = _buildJobs[key];
      if (job != null) {
        job.status = 'error';
        job.finishedAt = DateTime.now();
        job.error = e.toString();
      }
    }
  }

  /// Serve a file from a product/pos web build. Returns null if not found.
  Response? serveStatic(Request request) {
    final segments = request.url.pathSegments;
    if (segments.isEmpty || segments.first != 'preview') return null;
    if (segments.length < 2) {
      return Response.notFound('preview slug required');
    }
    final slug = segments[1];
    var rel = segments.length > 2 ? segments.sublist(2).join('/') : 'index.html';
    if (rel.isEmpty || rel.endsWith('/')) rel = '${rel}index.html';
    final webRoot = _webRootForSlug(slug);
    final file = File('$webRoot/$rel');
    if (!file.existsSync()) {
      return Response.notFound('preview asset not found: $rel');
    }
    final mime = _mimeForPath(rel);
    return Response.ok(
      file.readAsBytesSync(),
      headers: {
        'Content-Type': mime,
        'Cache-Control': 'no-cache',
        ..._corsHeaders,
      },
    );
  }

  static const _corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, HEAD',
    'Access-Control-Allow-Headers': 'Content-Type, Accept, Origin, Authorization',
  };

  String _mimeForPath(String path) {
    if (path.endsWith('.html')) return 'text/html; charset=utf-8';
    if (path.endsWith('.js')) return 'application/javascript';
    if (path.endsWith('.css')) return 'text/css; charset=utf-8';
    if (path.endsWith('.json')) return 'application/json';
    if (path.endsWith('.png')) return 'image/png';
    if (path.endsWith('.svg')) return 'image/svg+xml';
    if (path.endsWith('.woff2')) return 'font/woff2';
    return 'application/octet-stream';
  }

  List<Map<String, dynamic>> readCrewAgents(String id) {
    final file = File('${store.featurePath(id)}/crew-log.jsonl');
    if (!file.existsSync()) return [];
    return file
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => jsonDecode(l) as Map<String, dynamic>)
        .toList();
  }

  Future<Map<String, dynamic>> studioPreview(String id, {int? phase}) async {
    final state = store.readState(id);
    final workPhase = phase ??
        (state['pending_approval_phase'] as num?)?.toInt() ??
        (state['current_phase'] as num?)?.toInt() ??
        1;
    final product = resolveProduct(id);
    final target = resolvePreviewTarget(id);
    final slug = target['slug'] as String?;
    final build = buildStatus(id);
    Map<String, dynamic>? checklist;
    if (workPhase >= 1 && workPhase <= 9) {
      try {
        checklist = await validator.checklist(id, workPhase);
      } catch (_) {}
    }
    final integrityResult = integrity.verify(id);
    final agents = readCrewAgents(id);
    final gates = Map<String, dynamic>.from(
      state['gates'] as Map<String, dynamic>? ?? {},
    );
    final artifactItems = _artifactProgress(gates, checklist);
    return {
      'feature_id': id,
      'phase': workPhase,
      'spec_excerpt': readSpecExcerpt(id),
      'spec_path': store.artifactExists('specs/$id/spec.md')
          ? 'specs/$id/spec.md'
          : null,
      'integrity': {
        'valid': integrityResult['valid'] == true,
        'blocks': integrityResult['blocks'],
        'sealed_files': integrityResult['sealed_files'],
        'breaches': integrityResult['breaches'] ?? [],
      },
      'crew': {
        'agents': agents,
        'completed': agents.where((a) => a['status'] == 'done').length,
        'total': agents.length,
        'running': agents.any((a) => a['status'] == 'running'),
      },
      'artifacts': artifactItems,
      'artifacts_pass': checklist?['pass'],
      'product': product == null && slug == null
          ? null
          : {
              'id': product ?? slug,
              'kind': target['kind'],
              'web_build_ready': slug != null && webBuildReadyForSlug(slug),
              'preview_url':
                  slug != null ? previewUrlForSlug(slug) : null,
              'code_excerpt': product != null ? readCodeExcerpt(product) : null,
            },
      'build': build,
      'building': build['status'] == 'building' ||
          agents.any((a) => a['status'] == 'running') ||
          (state['status'] == 'active' &&
              workPhase <= 6 &&
              agents.isEmpty &&
              !store.bootstrapComplete(id, state)),
    };
  }

  List<Map<String, dynamic>> _artifactProgress(
    Map<String, dynamic> gates,
    Map<String, dynamic>? checklist,
  ) {
    final items = <Map<String, dynamic>>[];
    for (final entry in FeatureStore.phaseGateMap.entries) {
      items.add({
        'phase': entry.key,
        'gate': entry.value,
        'done': gates[entry.value] == true,
      });
    }
    final files =
        (checklist?['artifacts'] as List<dynamic>?)?.cast<Map<String, dynamic>>();
    if (files != null) {
      for (final f in files) {
        items.add({
          'phase': checklist?['phase'],
          'file': f['path'],
          'done': f['present'] == true && f['valid'] != false,
          'required': f['required'] == true,
        });
      }
    }
    return items;
  }
}
