import 'package:orchestration_server/orch_env_loader.dart';
import 'package:test/test.dart';

void main() {
  test('orchLlmConfigured returns bool from current environment', () {
    expect(orchLlmConfigured(), isA<bool>());
  });
}
