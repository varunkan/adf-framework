/// CANONICAL "is this text code rather than prose?" predicate — the single source
/// of truth (D3). An IDENTICAL copy lives at
/// tools/orchestration_server/lib/code_heuristics.dart; both are pinned to the
/// SAME contract vector tools/code_heuristics_golden.json (each package's test
/// loads it), so editing one copy without the other fails CI. Keep them in sync.
///
/// This is the CLASSIFIER only. `<<<FILE>>>`/code-fence handling and the client's
/// prose→NL summarisation layer on top of it. Threshold 0.12 + a >40-char guard
/// (the reconciled values — the server used 0.10, the client 0.12).
class CodeHeuristics {
  // Unambiguous SQL pairs — these word-pairs essentially never occur in prose, so
  // they are safe even case-insensitive. (Bare SELECT/UPDATE are NOT here: they
  // collide with "Select the format" / "Update the spec".)
  static final RegExp _sqlStrong = RegExp(
    r'\binsert\s+into\b|\bdelete\s+from\b|\bcreate\s+(table|index|view)\b'
    r'|\balter\s+table\b|\bdrop\s+(table|index)\b|\bupdate\s+\w+\s+set\b',
    caseSensitive: false,
  );
  // SELECT…FROM is ambiguous with prose ("Select the data from the cache"); only
  // code when a SQL signal is also present (*, ;, =, comma, or a clause keyword).
  static final RegExp _sqlSelect =
      RegExp(r'\bselect\b.*\bfrom\b', caseSensitive: false);
  static final RegExp _sqlSignal = RegExp(
      r'[*;=,]|\b(where|join|group\s+by|order\s+by|limit)\b',
      caseSensitive: false);
  // Shell/CLI + code keyword starts: case-SENSITIVE lowercase. Real code is
  // lowercase at line start; a prose sentence capitalises its first word, so
  // "Return the id" / "Flutter rebuilds" / "Static analysis" / "Import the data"
  // stay prose while `return x;` / `flutter pub get` / `import 'x'` are caught.
  static final RegExp _shellStart = RegExp(
    r'^\s*(\$\s|npm |npx |yarn |pnpm |flutter |dart |git |cd |mkdir |rm |pip '
    r'|python3? |node |curl |wget |docker |kubectl |make |sudo |export )',
  );
  static final RegExp _codeStart = RegExp(
    r'^\s*(import |export |from |const |let |var |function |func |def |class '
    r'|public |private |protected |static |void |return |async |await |if\s*\('
    r'|for\s*\(|while\s*\(|switch\s*\(|@\w+|<\?php|#include|package )',
  );
  static final RegExp _symbols = RegExp(r'''[{}()\[\];=<>|&/\\`]''');
  static final RegExp _callOrArrow =
      RegExp(r'=>|::|\)\s*\{|\w+\([^)]*\)\s*[;{]|;\s*$');

  /// True when [text] reads as code/SQL/shell/JSON rather than natural language.
  static bool isCodeLike(String text) {
    final t = text.trimLeft();
    if (t.isEmpty) return false;
    if (t.startsWith('```') ||
        t.startsWith('{') ||
        t.startsWith('}') ||
        t.startsWith('[') ||
        t.startsWith('//') ||
        t.startsWith('/*') ||
        (t.startsWith('<') && RegExp(r'^<\/?\w').hasMatch(t))) {
      return true;
    }
    if (_sqlStrong.hasMatch(t)) return true;
    if (_sqlSelect.hasMatch(t) && _sqlSignal.hasMatch(t)) return true;
    if (_shellStart.hasMatch(t) || _codeStart.hasMatch(t)) return true;
    if (RegExp(r'^"[\w.-]+"\s*:').hasMatch(t)) return true; // JSON "key": fragment
    if (_callOrArrow.hasMatch(t)) return true;
    final symbols = _symbols.allMatches(t).length;
    return t.length > 40 && symbols / t.length > 0.12;
  }
}
