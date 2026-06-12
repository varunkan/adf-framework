import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/services/api_client.dart';

void main() {
  late List<http.Request> requests;

  ApiClient client(Map<String, dynamic> Function(http.Request) handler,
      {int status = 200, Map<String, String> headers = const {}}) {
    requests = [];
    return ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        requests.add(req);
        return http.Response(
          jsonEncode(handler(req)),
          status,
          headers: {'content-type': 'application/json', ...headers},
        );
      }),
    );
  }

  test('health true on 200, false on failure', () async {
    expect(await client((_) => {'status': 'ok'}).health(), isTrue);
    expect(
      await client((_) => {'error': 'x'}, status: 500).health(),
      isFalse,
    );
  });

  test('createFromPrompt posts prompt and returns detail', () async {
    final api = client((req) {
      expect(req.method, 'POST');
      expect(jsonDecode(req.body)['prompt'], 'build a thing');
      return {'id': 'build-thing', 'mode': 'queued'};
    }, status: 201);
    final detail = await api.createFromPrompt('build a thing');
    expect(detail['id'], 'build-thing');
  });

  test('listFeatures returns features with count', () async {
    final api = client((_) => {
          'features': [
            {'id': 'a'},
            {'id': 'b'},
          ],
          'count': 2,
        });
    final res = await api.listFeatures();
    expect(res.count, 2);
    expect(res.features.first['id'], 'a');
  });

  test('getFeature caches by ETag and serves 304 from cache', () async {
    var calls = 0;
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        calls++;
        if (req.headers['If-None-Match'] == '"v1"') {
          return http.Response('', 304, headers: {'etag': '"v1"'});
        }
        return http.Response(
          jsonEncode({'id': 'f1', 'phase': 3}),
          200,
          headers: {'etag': '"v1"'},
        );
      }),
    );
    final first = await api.getFeature('f1');
    expect(first['phase'], 3);
    final second = await api.getFeature('f1');
    expect(second['phase'], 3, reason: '304 must serve cached body');
    expect(api.wasNotModified('f1'), isTrue);
    expect(calls, 2);
  });

  test('getFeature 404 throws not found', () async {
    final api = client((_) => {'error': 'nope'}, status: 404);
    expect(() => api.getFeature('ghost'), throwsException);
  });

  test('approve posts decision payload', () async {
    final api = client((req) {
      final body = jsonDecode(req.body) as Map<String, dynamic>;
      expect(body['decision'], 'approve');
      expect(body['phase'], 2);
      expect(body['judge_waiver'], isFalse);
      return {'ok': true};
    });
    final res = await api.approve(id: 'f1', phase: 2, decision: 'approve');
    expect(res['ok'], isTrue);
  });

  test('getStudioPreview returns preview payload', () async {
    final api = client((req) {
      expect(req.url.path, '/features/f1/studio-preview');
      return {
        'integrity': {'valid': true},
        'crew': {'agents': []},
        'artifacts': [],
      };
    });
    final res = await api.getStudioPreview('f1');
    expect(res['integrity'], isA<Map>());
  });

  test('runAutopilot returns crew summary', () async {
    final api = client((req) {
      expect(req.url.path, '/features/f1/autopilot');
      return {
        'phases_completed': [1, 2, 3],
        'token_cost': 'zero',
        'agents': [
          {'agent': 'spec-writer'},
        ],
      };
    });
    final res = await api.runAutopilot('f1');
    expect(res['token_cost'], 'zero');
  });

  test('sendCommand returns assistant reply and surfaces 409', () async {
    final api = client((req) {
      expect(jsonDecode(req.body)['prompt'], 'status?');
      return {
        'ok': true,
        'assistant_message': 'phase 2',
        'llm_source': 'state',
      };
    });
    final res = await api.sendCommand('f1', prompt: 'status?');
    expect(res['assistant_message'], 'phase 2');

    final busy = client((_) => {'error': 'Runner not ready'}, status: 409);
    expect(() => busy.sendCommand('f1', prompt: 'x'), throwsException);
  });

  test('state mutation endpoints round-trip', () async {
    final api = client((req) => {'ok': true, 'path': req.url.path});
    expect((await api.syncState('f1'))['ok'], isTrue);
    expect((await api.triggerHeal('f1'))['ok'], isTrue);
    expect((await api.retryRun('f1'))['ok'], isTrue);
    expect((await api.cancelRun('f1'))['ok'], isTrue);
    expect((await api.unstickFeature('f1'))['ok'], isTrue);
    expect((await api.getPipeline('f1'))['ok'], isTrue);
    expect((await api.getRunnerHealth())['ok'], isTrue);
    expect((await api.fetchHealth())['ok'], isTrue);
  });

  test('getConversation parses message list', () async {
    final api = client((_) => {
          'messages': [
            {'role': 'user', 'text': 'hi'},
          ],
        });
    final conv = await api.getConversation('f1');
    expect(conv.single['text'], 'hi');
  });
  test('fetchPreview uses ETag cache', () async {
    var calls = 0;
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        calls++;
        if (req.headers['If-None-Match'] == '"pv1"') {
          return http.Response('', 304, headers: {'etag': '"pv1"'});
        }
        return http.Response(
          jsonEncode({'feature_id': 'f1', 'building': false}),
          200,
          headers: {'etag': '"pv1"'},
        );
      }),
    );
    final first = await api.fetchPreview('f1');
    expect(first['feature_id'], 'f1');
    final second = await api.fetchPreview('f1');
    expect(second['feature_id'], 'f1');
    expect(api.wasPreviewNotModified('f1'), isTrue);
    expect(calls, 2);
  });

}
