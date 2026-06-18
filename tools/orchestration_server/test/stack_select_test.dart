import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

/// N8 (stack-select) — a feature's build stack is chosen at create time,
/// persisted in state.json (`state.stack`, contract C5), and threaded to the
/// Python runner as the ADF_STACK env var so it generates/verifies with the
/// right StackProfile. Existing features (no stack field) stay on stdlib.
void main() {
  late Directory repo;
  late FeatureStore store;

  setUp(() {
    repo = Directory.systemTemp.createTempSync('adf-stack');
    store = FeatureStore(repo.path);
  });

  tearDown(() {
    if (repo.existsSync()) repo.deleteSync(recursive: true);
  });

  test('createFeature persists the chosen stack in state.json', () {
    store.createFeature(
      id: 'kanban',
      requirement: 'A kanban board',
      track: 'M',
      stack: 'react-vite-sqlite',
    );
    expect(store.readState('kanban')['stack'], 'react-vite-sqlite');
    expect(store.stackFor('kanban'), 'react-vite-sqlite');
  });

  test('createFeature defaults to stdlib (back-compat)', () {
    store.createFeature(id: 'tool', requirement: 'A small tool', track: 'S');
    expect(store.readState('tool')['stack'], 'stdlib');
    expect(store.stackFor('tool'), 'stdlib');
  });

  test('stackFor falls back to stdlib for a legacy feature with no stack field',
      () {
    store.createFeature(id: 'legacy', requirement: 'Old', track: 'S');
    final st = store.readState('legacy');
    st.remove('stack'); // simulate a feature created before stack selection
    store.writeState('legacy', st);
    expect(store.stackFor('legacy'), 'stdlib');
  });

  test('isKnownStack validates the allowlist', () {
    expect(FeatureStore.isKnownStack('stdlib'), isTrue);
    expect(FeatureStore.isKnownStack('react-vite-sqlite'), isTrue);
    expect(FeatureStore.isKnownStack('expo-rn'), isTrue); // mobile stack accepted
    expect(FeatureStore.isKnownStack('php-laravel'), isFalse);
  });

  test('a feature can be created with the mobile stack and it persists', () {
    store.createFeature(id: 'mob', requirement: 'a notes app', track: 'M',
        stack: 'expo-rn');
    expect(store.stackFor('mob'), 'expo-rn');
  });

  test('PhaseRunner.childEnvFor threads ADF_STACK from the feature state', () {
    store.createFeature(
      id: 'board',
      requirement: 'x',
      track: 'M',
      stack: 'react-vite-sqlite',
    );
    final runner = PhaseRunner(store, env: {'PATH': '/usr/bin', 'PAGER': 'less'});
    final env = runner.childEnvFor('board');
    expect(env['ADF_STACK'], 'react-vite-sqlite');
    expect(env['PATH'], '/usr/bin'); // base env preserved
    // Non-interactive hardening forces interactive settings off (PAGER less→cat).
    expect(env['PAGER'], 'cat');
    expect(env['GIT_TERMINAL_PROMPT'], '0');
    expect(env['CI'], '1');
    // A legacy/stdlib feature yields stdlib.
    store.createFeature(id: 'plain', requirement: 'y', track: 'S');
    expect(runner.childEnvFor('plain')['ADF_STACK'], 'stdlib');
  });

  test('PhaseRunner.childEnvFor passes ADF_FEATURE_ID explicitly (regression '
      'guard for the prose-parse build bug)', () {
    // The shipped bug: the runner parsed the feature id from the prompt prose, so
    // "implement phase 7" became id "phase" and the build failed. The fix is that
    // the server passes the id EXPLICITLY. If this line is ever dropped, the runner
    // silently falls back to prose-parsing and the bug returns — so assert it here.
    store.createFeature(
        id: 'snake-ladder-games', requirement: 'x', track: 'M',
        stack: 'react-vite-sqlite');
    final runner = PhaseRunner(store, env: {'PATH': '/usr/bin'});
    expect(runner.childEnvFor('snake-ladder-games')['ADF_FEATURE_ID'],
        'snake-ladder-games');
  });
}
