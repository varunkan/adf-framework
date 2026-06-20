/// Turns raw agent reasoning into Cursor/Claude-style NATURAL-LANGUAGE narration.
///
/// The agents reason in whatever form they like — often raw SQL, Dart/TS code,
/// JSON config, or shell commands. Dumping that verbatim into the live "thought"
/// stream is exactly the "machine-level code and queries for programmers" feel we
/// do NOT want. This sanitizer keeps genuine prose and rewrites a predominantly-
/// code/query/command line into a short plain-English description ("Writing a
/// database query", "Running a command"), so the stream reads like a person
/// narrating the work. The actual code still shows where it belongs — the typed
/// file/tool cards (LiveActivityList) and the file viewer.
class ThoughtSanitizer {
  /// A clean, human line for [raw] — prose kept as-is, code/query/command lines
  /// rewritten to a short natural-language summary. Returns null to DROP a line
  /// that carries no narration value (empty, a bare path, a hash/identifier).
  static String? clean(String raw) {
    final t = raw.trim();
    if (t.isEmpty) return null;
    if (_isNoise(t)) return null;
    if (_isMostlyCode(t)) return _summarize(t);
    return t;
  }

  // --- classification --------------------------------------------------------

  static final _sqlStart = RegExp(
      r'^\s*(select|insert\s+into|update|delete\s+from|create\s+(table|index|'
      r'view)|alter\s+table|drop\s+(table|index)|with\s+\w+\s+as)\b',
      caseSensitive: false);
  static final _shellStart = RegExp(
      r'^\s*(\$\s|npm |npx |yarn |pnpm |flutter |dart |git |cd |mkdir |rm |pip '
      r'|python3? |node |curl |wget |docker |kubectl |make |sudo |export )',
      caseSensitive: false);
  static final _codeStart = RegExp(
      r'^\s*(import |export |from |const |let |var |function |func |def |class '
      r'|public |private |protected |static |void |return |async |await |if\s*\('
      r'|for\s*\(|while\s*\(|switch\s*\(|@\w+|<\?php|#include|package )',
      caseSensitive: false);
  static final _codeSymbols = RegExp(r'''[{}()\[\];=<>|&/\\`]''');
  static final _callOrArrow =
      RegExp(r'=>|::|\)\s*\{|\w+\([^)]*\)\s*[;{]|;\s*$');
  static final _longToken = RegExp(r'\S{46,}');

  /// True when the line is overwhelmingly code/query/command rather than prose.
  static bool _isMostlyCode(String t) {
    if (t.startsWith('```') || t.startsWith('{') || t.startsWith('}') ||
        t.startsWith('[') || t.startsWith('//') || t.startsWith('/*') ||
        t.startsWith('<') && RegExp(r'^<\/?\w').hasMatch(t)) {
      return true;
    }
    if (_sqlStart.hasMatch(t) || _shellStart.hasMatch(t) ||
        _codeStart.hasMatch(t)) {
      return true;
    }
    if (_callOrArrow.hasMatch(t)) return true;
    // Symbol density: prose is mostly letters/spaces; code is punctuation-heavy.
    final symbols = _codeSymbols.allMatches(t).length;
    if (t.isNotEmpty && symbols / t.length > 0.12) return true;
    // A JSON-ish "key": value fragment.
    if (RegExp(r'^"[\w.-]+"\s*:').hasMatch(t)) return true;
    return false;
  }

  /// Lines that are not narration at all — bare paths, hashes, single tokens.
  static bool _isNoise(String t) {
    if (!t.contains(' ') && (t.contains('/') || _longToken.hasMatch(t))) {
      return true; // a path or an opaque identifier on its own line
    }
    final letters = RegExp(r'[A-Za-z]').allMatches(t).length;
    if (letters < 3) return true; // punctuation-only / numeric noise
    return false;
  }

  // --- summarization ---------------------------------------------------------

  static final _fromWhereJoin =
      RegExp(r'\b(from|where|join|group\s+by|order\s+by)\b', caseSensitive: false);
  static final _markup = RegExp(r'<\/?\w+[^>]*>|/>');

  /// A short plain-English label for a code/query/command line.
  static String _summarize(String t) {
    final l = t.toLowerCase();
    if (_sqlStart.hasMatch(t) || (_fromWhereJoin.hasMatch(t) && t.contains(' '))) {
      return 'Writing a database query';
    }
    if (_shellStart.hasMatch(t)) return 'Running a command';
    if (t.startsWith('{') || t.startsWith('[') ||
        RegExp(r'^"[\w.-]+"\s*:').hasMatch(t)) {
      return 'Updating configuration';
    }
    if (_markup.hasMatch(t)) return 'Writing the markup';
    if (l.contains('test') &&
        RegExp(r'\b(expect|assert|describe|it\()').hasMatch(l)) {
      return 'Writing a test';
    }
    return 'Writing code';
  }
}
