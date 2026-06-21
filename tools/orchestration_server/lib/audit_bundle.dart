import 'dart:convert';
import 'dart:io';

import 'cost_meter.dart';
import 'feature_store.dart';
import 'integrity_chain.dart';
import 'runner_backend.dart';

/// Builds the exportable audit bundle for a feature — one self-verifying
/// JSON document (`adf-audit-bundle/1`) that one machine can hand to another
/// as proof of what was built.
///
/// The bundle embeds the feature's full integrity-chain ledger, the sealed
/// artifact manifest, the gate map, and the cost evidence, then stamps a
/// `bundle_digest` over the whole document using the exact canonical JSON
/// encoding from [IntegrityChain.canonical]. The standalone verifier
/// (`scripts/orch/verify_audit_bundle.py`, python3 stdlib only) replicates
/// that encoding byte-for-byte, so verification needs neither this server
/// nor Dart.
class AuditBundleBuilder {
  AuditBundleBuilder(
    this.store, {
    required this.integrity,
    required this.costs,
    RunnerBackend? backend,
  }) : backend = backend ?? RunnerBackend.active();

  final FeatureStore store;
  final IntegrityChain integrity;
  final CostMeter costs;
  final RunnerBackend backend;

  static const format = 'adf-audit-bundle/1';

  /// Contract payload for `GET /features/<id>/audit-bundle`.
  ///
  /// `chain` is the feature's full ledger content (null when the feature was
  /// never sealed). The artifact list is lifted from the chain's sealed
  /// manifest — those hashes are already proven, so the repo is never
  /// re-hashed here (files are only stat'd for sizes). `bundle_digest`
  /// covers every other field.
  Map<String, dynamic> build(String id) {
    final chain = integrity.blocks(id);
    final manifest = chain.isEmpty
        ? const <String, String>{}
        : (chain.last['manifest'] as Map?)?.cast<String, String>() ??
            const <String, String>{};
    final paths = manifest.keys.toList()..sort();
    final gates = store.readState(id)['gates'] as Map<String, dynamic>? ?? {};
    final costFile = File(costs.costPath(id));

    final bundle = <String, dynamic>{
      'format': format,
      'feature_id': id,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'runner': {
        'runner': backend.kind.id,
        'runner_label': backend.kind.label,
      },
      'chain': chain.isEmpty ? null : chain,
      'artifacts': [
        for (final rel in paths)
          {
            'path': rel,
            'sha256': manifest[rel],
            'bytes': _sizeOf('${store.repoRoot}/$rel'),
          },
      ],
      'gates': gates,
      'cost': costFile.existsSync() ? costs.featureCost(id) : null,
      // The moat, attested in the same sealed document: what was generated is
      // tamper-evidently proven (Proof of Build), governed (Policy Gates), and
      // context-managed (Compaction). Summaries ride under `bundle_digest`, so a
      // forged seal or flipped policy verdict breaks the bundle.
      'moat': _moat(id),
    };
    return {
      ...bundle,
      'bundle_digest':
          IntegrityChain.hashString(IntegrityChain.canonical(bundle)),
    };
  }

  /// Lift the per-app moat artifacts (written into `apps/<id>/` by the runner)
  /// into compact, digest-covered summaries. Null when nothing was built.
  Map<String, dynamic>? _moat(String id) {
    final appDir = '${store.repoRoot}/apps/$id';
    final proof = _readJson('$appDir/.adf-proof.json');
    final policy = _readJson('$appDir/.adf-policy-report.json');
    final ctxDir = Directory('$appDir/.adf-context');
    Map<String, dynamic>? context;
    if (ctxDir.existsSync()) {
      final cards = ctxDir
          .listSync()
          .whereType<File>()
          .where((f) =>
              f.path.contains('compaction-') && f.path.endsWith('.json'))
          .toList()
        ..sort((a, b) => a.path.compareTo(b.path));
      if (cards.isNotEmpty) {
        final last = _readJson(cards.last.path);
        context = {
          'cards': cards.length,
          'last': last == null
              ? null
              : {
                  'kind': last['kind'],
                  'tokens_before': last['tokens_before'],
                  'tokens_after': last['tokens_after'],
                  'n_summarized': last['n_summarized'],
                },
        };
      }
    }
    if (proof == null && policy == null && context == null) return null;
    return {
      'proof': proof == null
          ? null
          : {
              'seal': proof['seal'],
              // Key name is 'merkle_root' per proof_of_build.py:238 (SSOT);
              // 'root' retained as legacy fallback.
              'root': proof['merkle_root'] ?? proof['root'],
              'n_files': (proof['files'] as List?)?.length,
            },
      'policy': policy == null
          ? null
          : {
              'policy_id': policy['policy_id'],
              'ok': policy['ok'],
              'n_violations': policy['n_violations'],
            },
      'context': context,
    };
  }

  static Map<String, dynamic>? _readJson(String path) {
    final f = File(path);
    if (!f.existsSync()) return null;
    try {
      return jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  /// Size on disk of a sealed artifact; -1 when it has since vanished
  /// (the chain verify flags that as a breach — the bundle just reports).
  static int _sizeOf(String path) {
    final stat = File(path).statSync();
    return stat.type == FileSystemEntityType.notFound ? -1 : stat.size;
  }
}
