import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:orchestration_dashboard/screens/new_feature_screen.dart';
import 'package:orchestration_dashboard/services/api_client.dart';

void main() {
  group('parseSourceLinks (P4)', () {
    test('keeps http(s) links, splits on newline/comma, drops noise', () {
      expect(
          parseSourceLinks(
              'https://a.com\nhttp://b.com, not-a-link\n  https://c.com '),
          ['https://a.com', 'http://b.com', 'https://c.com']);
      expect(parseSourceLinks(''), isEmpty);
      expect(parseSourceLinks('just some text'), isEmpty);
    });
  });

  test('createFeature sends sources as [{url}] when links given (P4)', () async {
    Map<String, dynamic>? sentBody;
    final api = ApiClient(
      baseUrl: 'http://t',
      client: MockClient((req) async {
        sentBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'id': 'x'}), 201,
            headers: {'content-type': 'application/json'});
      }),
    );
    await api.createFeature(
        id: 'x', requirement: 'r', track: 'M', sourceLinks: ['https://a.com']);
    expect(sentBody!['sources'], [
      {'url': 'https://a.com'}
    ]);
  });

  test('createFeature omits sources when no links (back-compat)', () async {
    Map<String, dynamic>? sentBody;
    final api = ApiClient(
      baseUrl: 'http://t',
      client: MockClient((req) async {
        sentBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'id': 'x'}), 201,
            headers: {'content-type': 'application/json'});
      }),
    );
    await api.createFeature(id: 'x', requirement: 'r', track: 'M');
    expect(sentBody!.containsKey('sources'), isFalse);
  });
}
