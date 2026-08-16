import 'dart:async';
import 'dart:convert';

/// Observable transport state — surfaced to the UI so the operator can SEE whether
/// live push is healthy (part of "everything can be monitored").
enum LiveState {
  /// Not started, or stopped.
  idle,

  /// Opening the SSE connection (no span received yet).
  connecting,

  /// Receiving pushed spans in real time.
  live,

  /// SSE hiccupped; the source is retrying (browser EventSource auto-reconnects
  /// and carries Last-Event-ID, so the server backfills — nothing is lost).
  reconnecting,

  /// SSE gave up after repeated failures; degraded to the /traces poll so the
  /// Studio never goes dark (graceful self-healing fallback).
  polling,
}

/// One server-push message (mirrors an EventSource MessageEvent).
class LiveMessage {
  const LiveMessage(this.data, [this.lastEventId]);
  final String data;
  final String? lastEventId;
}

/// A live push source (real impl wraps the browser EventSource on web). Abstracted
/// so the self-healing client below is pure Dart and unit-testable off-web.
abstract class LiveSource {
  Stream<LiveMessage> get messages;

  /// Fires on each transport error (EventSource onError fires per failed retry).
  Stream<Object> get errors;
  Future<void> close();
}

typedef LiveSourceFactory = LiveSource Function(Uri uri, {String? since});
typedef PollFn = Future<List<Map<String, dynamic>>> Function({String? since});

/// Self-healing consumer of the runner's live span stream.
///
/// Behaviour (all three are "self-healing loops"):
///  1. SSE first — JSON-decodes each pushed span and advances a `since` cursor.
///  2. A transient drop is invisible: the (browser) source auto-reconnects with
///     Last-Event-ID and the server replays missed spans; one good message resets
///     the failure count back to healthy.
///  3. After [maxSseErrors] consecutive failures it DEGRADES to [poll] (the existing
///     /traces endpoint) on [pollInterval], so the operator never loses visibility.
///
/// [state] is published throughout so the UI can render LIVE / reconnecting / polling.
/// The (Uri, factory, poll) I/O is injected, so this class never imports dart:html
/// and is fully testable with fakes.
class LiveTraceClient {
  LiveTraceClient({
    required this.uri,
    required this.connect,
    required this.poll,
    required this.onSpan,
    this.pollInterval = const Duration(milliseconds: 1500),
    this.maxSseErrors = 3,
    String? since,
  }) : _since = since;

  final Uri uri;
  final LiveSourceFactory connect;
  final PollFn poll;
  final void Function(Map<String, dynamic> span) onSpan;
  final Duration pollInterval;
  final int maxSseErrors;

  String? _since;

  /// Last span cursor seen (timestamp / Last-Event-ID) — drives reconnect backfill.
  String? get since => _since;

  LiveSource? _source;
  StreamSubscription<LiveMessage>? _msgSub;
  StreamSubscription<Object>? _errSub;
  Timer? _pollTimer;
  int _errors = 0;
  bool _stopped = false;

  final _stateCtrl = StreamController<LiveState>.broadcast();
  Stream<LiveState> get state => _stateCtrl.stream;

  LiveState _state = LiveState.idle;
  LiveState get currentState => _state;
  void _setState(LiveState s) {
    if (_state == s) return;
    _state = s;
    if (!_stateCtrl.isClosed) _stateCtrl.add(s);
  }

  void start() {
    if (_stopped || _source != null || _pollTimer != null) return;
    _openSse();
  }

  void _openSse() {
    _setState(LiveState.connecting);
    try {
      final src = connect(uri, since: _since);
      _source = src;
      _msgSub = src.messages.listen(_onMessage, onError: (_) => _onError());
      _errSub = src.errors.listen((_) => _onError());
    } catch (_) {
      _onError();
    }
  }

  void _onMessage(LiveMessage m) {
    _errors = 0; // a good frame means the source recovered
    _setState(LiveState.live);
    if (m.lastEventId != null && m.lastEventId!.isNotEmpty) {
      _since = m.lastEventId;
    }
    final trimmed = m.data.trim();
    if (trimmed.isEmpty) return; // keep-alive comment
    Map<String, dynamic> span;
    try {
      span = jsonDecode(trimmed) as Map<String, dynamic>;
    } catch (_) {
      return; // non-JSON line (e.g. a comment that slipped through)
    }
    final ts = span['timestamp'];
    if (ts is String && ts.isNotEmpty) _since = ts;
    onSpan(span);
  }

  void _onError() {
    if (_stopped) return;
    _errors++;
    if (_errors >= maxSseErrors) {
      _degradeToPoll();
    } else {
      _setState(LiveState.reconnecting);
    }
  }

  void _degradeToPoll() {
    _teardownSse();
    _setState(LiveState.polling);
    _pollTimer?.cancel();
    _pollOnce();
    _pollTimer = Timer.periodic(pollInterval, (_) => _pollOnce());
  }

  Future<void> _pollOnce() async {
    if (_stopped) return;
    try {
      final spans = await poll(since: _since);
      for (final s in spans) {
        final ts = s['timestamp'];
        if (ts is String && ts.isNotEmpty) _since = ts;
        onSpan(s);
      }
    } catch (_) {
      // Transient poll failure — keep the timer running and try again.
    }
  }

  void _teardownSse() {
    _msgSub?.cancel();
    _msgSub = null;
    _errSub?.cancel();
    _errSub = null;
    _source?.close();
    _source = null;
  }

  Future<void> stop() async {
    _stopped = true;
    _pollTimer?.cancel();
    _pollTimer = null;
    _teardownSse();
    _setState(LiveState.idle);
    await _stateCtrl.close();
  }
}
