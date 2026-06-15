import 'dart:convert';
import 'dart:io';

/// Surfaces an app's **Proof of Build** to the dashboard by invoking the
/// canonical offline verifier (`scripts/orch/verify_proof.py --json`). The
/// Merkle math lives in ONE tested place (the Python sealer/verifier) so a
/// second implementation can't drift from the seal — the server just relays the
/// verdict it recomputes from the files on disk.
class ProofCheck {
  ProofCheck(this.repoRoot, {this.python = 'python3'});

  final String repoRoot;
  final String python;

  String appDir(String id) => '$repoRoot/apps/$id';

  bool hasProof(String id) =>
      File('${appDir(id)}/.adf-proof.json').existsSync();

  /// Returns `{has_proof:false}` when the app carries no seal, otherwise the
  /// verifier's report merged with `has_proof:true`:
  /// `{has_proof, ok, status:'VERIFIED'|'TAMPERED', seal, files:[...], ...}`.
  Future<Map<String, dynamic>> verify(String id) async {
    if (!hasProof(id)) return {'has_proof': false};
    final script = '$repoRoot/scripts/orch/verify_proof.py';
    if (!File(script).existsSync()) {
      return {'has_proof': true, 'error': 'verifier not found at $script'};
    }
    try {
      final r = await Process.run(python, [script, '--json', appDir(id)]);
      final out = (r.stdout as String).trim();
      if (out.isEmpty) {
        return {
          'has_proof': true,
          'error': 'verifier produced no output',
          'stderr': (r.stderr as String).trim(),
        };
      }
      final report = jsonDecode(out) as Map<String, dynamic>;
      return {'has_proof': true, ...report};
    } catch (e) {
      return {'has_proof': true, 'error': 'verifier failed: $e'};
    }
  }
}
