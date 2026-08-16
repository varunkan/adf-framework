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
  // The target after FROM/INTO/DELETE-FROM in real SQL is an IDENTIFIER, not an
  // English article — that separates "DELETE FROM sessions" from "delete from your
  // mind", and "SELECT * FROM users" from "Select the rows from the cache".
  static const String _notArticle =
      r'(?!(?:the|a|an|all|any|each|some|every|both|one|your|my|our|his|her|'
      r'their|its|this|that|these|those)\b)';
  // These are RAW strings: interpolation would mean dropping the r-prefix and
  // double-escaping every backslash in the pattern, which is how regex bugs get
  // introduced. Concatenating a raw fragment is the safer form, so the lint is
  // suppressed on each composing line rather than the pattern being rewritten.
  static final RegExp _sqlStrong = RegExp(
    // ignore: prefer_interpolation_to_compose_strings
    r'\binsert\s+into\s+' + _notArticle + r'\w'
        // ignore: prefer_interpolation_to_compose_strings
        r'|\bdelete\s+from\s+' + _notArticle + r'\w'
        r'|\bupdate\s+\w+\s+set\b'
        r'|\bcreate\s+(table|index|view)\b'
        r'|\balter\s+table\b|\bdrop\s+(table|index)\b',
    caseSensitive: false,
  );
  // SELECT…FROM only when the table after FROM is a non-article identifier.
  static final RegExp _sqlSelect = RegExp(
      r'\bselect\b.*\bfrom\s+' + _notArticle + r'\w',
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
  // Line-anchored statement SHAPES — a bare `=>`/`::` ANYWHERE is prose-incidental
  // ("The request => response", "ci.example.com::8080"), so we require: ends with
  // ; or { (a statement terminator), an arrow at the line head, or a call that is
  // the WHOLE line ("verify(); confirm…" has prose after → not code).
  static final RegExp _codeShape = RegExp(
    r'[;{]\s*$'
    r'|^\s*\w+\s*=>'
    r'|^\s*[\w.]+\([^)]*\)\s*[;{]?\s*$',
  );

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
    if (_sqlSelect.hasMatch(t)) return true;
    if (_shellStart.hasMatch(t) || _codeStart.hasMatch(t)) return true;
    if (RegExp(r'^"[\w.-]+"\s*:').hasMatch(t)) return true; // JSON "key": fragment
    if (_codeShape.hasMatch(t)) return true;
    final symbols = _symbols.allMatches(t).length;
    return t.length > 40 && symbols / t.length > 0.12;
  }
}
