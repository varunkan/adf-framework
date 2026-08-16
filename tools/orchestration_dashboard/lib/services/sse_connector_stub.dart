import 'dart:async';

import 'live_trace_client.dart';

/// Non-web (desktop/CI/tests): there is no browser EventSource, so hand back a
/// source that immediately and repeatedly errors. LiveTraceClient counts the
/// failures and self-heals to the /traces poll — a single unified code path on
/// every platform, with graceful degradation off-web.
LiveSource connectSse(Uri uri, {String? since}) => _NoSse();

class _NoSse implements LiveSource {
  _NoSse() {
    // Drip errors so the client crosses its maxSseErrors threshold and degrades;
    // close() cancels the timer once it tears the source down.
    _t = Timer.periodic(const Duration(milliseconds: 1), (_) {
      if (!_errors.isClosed) _errors.add('sse-unavailable-off-web');
    });
  }

  Timer? _t;
  final _errors = StreamController<Object>.broadcast();

  @override
  Stream<LiveMessage> get messages => const Stream<LiveMessage>.empty();
  @override
  Stream<Object> get errors => _errors.stream;
  @override
  Future<void> close() async {
    _t?.cancel();
    await _errors.close();
  }
}
