import 'dart:io';

import 'package:orchestration_server/runner_health.dart';
import 'package:test/test.dart';

void main() {
  test('resolveAgent finds binary or returns null gracefully', () {
    final h = RunnerHealth(repoRoot: Directory.current.path);
    final path = h.resolveAgent();
    if (path != null) {
      expect(File(path).existsSync(), isTrue);
    }
  });

  test('probe returns structured health map', () async {
    final h = RunnerHealth(repoRoot: Directory.current.path);
    final health = await h.probe();
    expect(health.containsKey('ready'), isTrue);
    expect(health.containsKey('agent_path'), isTrue);
  });

  test('probe identifies the active runner for the dashboard', () async {
    final h = RunnerHealth(repoRoot: Directory.current.path);
    final health = await h.probe();
    expect(health['runner'], isIn(['cursor', 'claude', 'custom']));
    expect(health['runner_label'], isA<String>());
    // Cursor and Claude expose a copyable login command; custom has none.
    if (health['runner'] != 'custom') {
      expect(health['login_command'], isA<String>());
    }
  });
}
