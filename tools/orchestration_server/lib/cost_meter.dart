import 'dart:convert';
import 'dart:io';

import 'feature_store.dart';

/// Meters real agent spend from terminal `{"type":"result"}` stream events.
///
/// Evidence precedence per run:
/// 1. `total_cost_usd` reported by the runner itself (Claude Code emits this)
///    — source `reported`.
/// 2. `usage` tokens priced via `ORCH_PRICE_IN_PER_MTOK` /
///    `ORCH_PRICE_OUT_PER_MTOK` when set — source `estimated`.
/// 3. Otherwise usd 0 — source `zero` (deterministic brain, ollama, custom
///    local runners).
///
/// Evidence persists per feature at `features/<id>/cost.json` via atomic
/// read-modify-write (temp file + rename), so a crash mid-write never leaves
/// a torn file behind.
class CostMeter {
  CostMeter(this.store, {Map<String, String>? env})
      : _env = env ?? Platform.environment;

  final FeatureStore store;
  final Map<String, String> _env;

  static const sourceReported = 'reported';
  static const sourceEstimated = 'estimated';
  static const sourceZero = 'zero';

  String costPath(String id) => '${store.featurePath(id)}/cost.json';

  /// Records one run from a stream-json result event such as
  /// `{"type":"result","total_cost_usd":0.04,"usage":{"input_tokens":...}}`.
  /// Missing fields degrade per the evidence precedence. Returns the run entry.
  Map<String, dynamic> recordFromResultEvent(
    String featureId,
    Map<String, dynamic> event, {
    int? phase,
  }) {
    final usage = event['usage'];
    final inputTokens = usage is Map ? _toInt(usage['input_tokens']) : 0;
    final outputTokens = usage is Map ? _toInt(usage['output_tokens']) : 0;

    final reported = event['total_cost_usd'];
    final rateIn = _rate('ORCH_PRICE_IN_PER_MTOK');
    final rateOut = _rate('ORCH_PRICE_OUT_PER_MTOK');

    double usd;
    String source;
    if (reported is num) {
      usd = reported.toDouble();
      source = sourceReported;
    } else if ((rateIn != null || rateOut != null) &&
        inputTokens + outputTokens > 0) {
      usd = inputTokens * (rateIn ?? 0) / 1e6 +
          outputTokens * (rateOut ?? 0) / 1e6;
      source = sourceEstimated;
    } else {
      usd = 0;
      source = sourceZero;
    }

    final run = <String, dynamic>{
      'at': DateTime.now().toUtc().toIso8601String(),
      'phase': phase,
      'usd': _round(usd),
      'input_tokens': inputTokens,
      'output_tokens': outputTokens,
      'source': source,
    };

    final file = File(costPath(featureId));
    final runs = _readRuns(file)..add(run);
    _writeAtomic(file, _payload(featureId, runs));
    return run;
  }

  /// Contract payload for `GET /features/<id>/cost`.
  Map<String, dynamic> featureCost(String id) {
    return _payload(id, _readRuns(File(costPath(id))));
  }

  /// Contract payload for `GET /cost/summary`. Covers every feature that has
  /// recorded cost evidence.
  Map<String, dynamic> summary() {
    var total = 0.0;
    var allZero = true;
    final byFeature = <Map<String, dynamic>>[];
    for (final id in store.listFeatures()) {
      final file = File(costPath(id));
      if (!file.existsSync()) continue;
      final cost = _payload(id, _readRuns(file));
      total += (cost['total_usd'] as num).toDouble();
      if (cost['zero_cost'] != true) allZero = false;
      byFeature.add({'feature_id': id, 'total_usd': cost['total_usd']});
    }
    return {
      'total_usd': _round(total),
      'zero_cost': allZero,
      'by_feature': byFeature,
    };
  }

  Map<String, dynamic> _payload(String id, List<Map<String, dynamic>> runs) {
    var usd = 0.0;
    var inputTokens = 0;
    var outputTokens = 0;
    var allZero = true;
    for (final run in runs) {
      usd += (run['usd'] as num? ?? 0).toDouble();
      inputTokens += _toInt(run['input_tokens']);
      outputTokens += _toInt(run['output_tokens']);
      if (run['source'] != sourceZero) allZero = false;
    }
    return {
      'feature_id': id,
      'total_usd': _round(usd),
      'total_input_tokens': inputTokens,
      'total_output_tokens': outputTokens,
      'zero_cost': allZero,
      'runs': runs,
    };
  }

  List<Map<String, dynamic>> _readRuns(File file) {
    if (!file.existsSync()) return [];
    try {
      final raw = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
      return (raw['runs'] as List? ?? const [])
          .whereType<Map>()
          .map((r) => Map<String, dynamic>.from(r))
          .toList();
    } catch (_) {
      return []; // corrupt evidence file — start a fresh run list
    }
  }

  void _writeAtomic(File file, Map<String, dynamic> payload) {
    file.parent.createSync(recursive: true);
    final tmp = File('${file.path}.tmp');
    tmp.writeAsStringSync(const JsonEncoder.withIndent('  ').convert(payload));
    tmp.renameSync(file.path);
  }

  double? _rate(String key) {
    final raw = _env[key];
    if (raw == null || raw.trim().isEmpty) return null;
    return double.tryParse(raw.trim());
  }

  static int _toInt(Object? v) => v is num ? v.toInt() : 0;

  /// Keep persisted dollars stable (no float-noise tails in cost.json).
  static double _round(double v) => double.parse(v.toStringAsFixed(6));
}
