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
    };
    return {
      ...bundle,
      'bundle_digest':
          IntegrityChain.hashString(IntegrityChain.canonical(bundle)),
    };
  }

  /// Size on disk of a sealed artifact; -1 when it has since vanished
  /// (the chain verify flags that as a breach — the bundle just reports).
  static int _sizeOf(String path) {
    final stat = File(path).statSync();
    return stat.type == FileSystemEntityType.notFound ? -1 : stat.size;
  }
}
