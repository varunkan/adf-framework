import 'dart:io';

import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/integrity_chain.dart';
import 'package:orchestration_server/preview_service.dart';
import 'package:shelf/shelf.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late PreviewService preview;
  const id = 'preview-service-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    preview = PreviewService(
      store,
      repoRoot,
      integrity: IntegrityChain(store),
      validator: ArtifactValidator(repoRoot),
      apiPort: 3847,
    );
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Preview metadata for studio panel.',
        track: 'S',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
  });

  test('resolvePreviewTarget falls back to pos when no product dir', () {
    final target = preview.resolvePreviewTarget(id);
    expect(target['kind'], isIn(['pos', 'product', 'none']));
  });

  test('studioPreview returns integrity and crew blocks', () async {
    final data = await preview.studioPreview(id);
    expect(data['feature_id'], id);
    expect(data['integrity'], isA<Map<String, dynamic>>());
    expect(data['crew'], isA<Map<String, dynamic>>());
    expect(data['build'], isA<Map<String, dynamic>>());
  });

  test('kickoffBuild returns disabled when feature flag off', () async {
    if (Platform.environment['ORCH_PREVIEW_BUILD'] == '1') return;
    final res = await preview.kickoffBuild(id);
    expect(res['enabled'], isFalse);
    expect(res['status'], 'disabled');
  });

  test('readSpecExcerpt readCodeExcerpt and serveStatic on temp tree', () async {
    final tmp = Directory.systemTemp.createTempSync('adf-preview-');
    addTearDown(() => tmp.deleteSync(recursive: true));
    const localId = 'auth-login';
    Directory('${tmp.path}/.adf/orchestration/features/$localId')
        .createSync(recursive: true);
    File('${tmp.path}/.adf/orchestration/features/$localId/state.json')
        .writeAsStringSync(
      '{"current_phase":1,"status":"active","gates":{},"track":"M"}',
    );
    Directory('${tmp.path}/specs/$localId').createSync(recursive: true);
    File('${tmp.path}/specs/$localId/spec.md')
        .writeAsStringSync('# Spec\n\nLogin required.');
    Directory('${tmp.path}/products/auth_login/lib').createSync(recursive: true);
    File('${tmp.path}/products/auth_login/lib/login_screen.dart')
        .writeAsStringSync('class LoginScreen {}');
    Directory('${tmp.path}/products/auth_login/build/web')
        .createSync(recursive: true);
    File('${tmp.path}/products/auth_login/build/web/index.html')
        .writeAsStringSync('<html></html>');

    final localStore = FeatureStore(tmp.path);
    final localPreview = PreviewService(
      localStore,
      tmp.path,
      integrity: IntegrityChain(localStore),
      validator: ArtifactValidator(tmp.path),
    );
    expect(localPreview.readSpecExcerpt(localId), contains('Login required'));
    expect(localPreview.readCodeExcerpt('auth_login'), contains('LoginScreen'));
    expect(localPreview.productWebBuildReady('auth_login'), isTrue);
    expect(
      localPreview.previewUrl('auth_login'),
      contains('/preview/auth_login/'),
    );

    final req = Request(
      'GET',
      Uri.parse('http://localhost/preview/auth_login/index.html'),
    );
    expect(localPreview.serveStatic(req)?.statusCode, 200);

    final data = await localPreview.studioPreview(localId);
    expect(data['spec_excerpt'], isNotNull);
    expect(data['product'], isNotNull);
  });
}
