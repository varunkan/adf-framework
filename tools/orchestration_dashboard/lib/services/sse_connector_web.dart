import 'dart:async';
// ignore: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;

import 'live_trace_client.dart';

/// Web: wrap the browser EventSource as a [LiveSource]. EventSource parses SSE
/// framing and auto-reconnects on its own (re-sending Last-Event-ID), so the
/// server backfills missed spans. For the INITIAL connect we append `?since=` so a
/// client opening mid-build replays what it missed before the socket existed.
LiveSource connectSse(Uri uri, {String? since}) {
  final u = (since != null && since.isNotEmpty)
      ? uri.replace(queryParameters: {...uri.queryParameters, 'since': since})
      : uri;
  return _WebLiveSource(u.toString());
}

class _WebLiveSource implements LiveSource {
  _WebLiveSource(String url) : _es = html.EventSource(url) {
    _es.onMessage.listen((me) {
      final d = me.data;
      _messages.add(LiveMessage(d is String ? d : '', me.lastEventId));
    });
    _es.onError.listen(_errors.add);
  }

  final html.EventSource _es;
  final _messages = StreamController<LiveMessage>.broadcast();
  final _errors = StreamController<Object>.broadcast();

  @override
  Stream<LiveMessage> get messages => _messages.stream;
  @override
  Stream<Object> get errors => _errors.stream;
  @override
  Future<void> close() async {
    _es.close();
    await _messages.close();
    await _errors.close();
  }
}
