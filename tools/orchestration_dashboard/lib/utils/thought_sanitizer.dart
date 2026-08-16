import 'code_heuristics.dart';

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

  // Labelling regexes (used ONLY by _summarize to pick the NL phrase — NOT for
  // the code/prose decision, which delegates to the shared CodeHeuristics).
  static final _sqlStart = RegExp(
      r'^\s*(select|insert\s+into|update|delete\s+from|create\s+(table|index|'
      r'view)|alter\s+table|drop\s+(table|index)|with\s+\w+\s+as)\b',
      caseSensitive: false);
  static final _shellStart = RegExp(
      r'^\s*(\$\s|npm |npx |yarn |pnpm |flutter |dart |git |cd |mkdir |rm |pip '
      r'|python3? |node |curl |wget |docker |kubectl |make |sudo |export )',
      caseSensitive: false);
  static final _longToken = RegExp(r'\S{46,}');

  /// True when the line is overwhelmingly code rather than prose. Delegates to the
  /// canonical, golden-pinned predicate so server + client agree (D3 SSOT).
  static bool _isMostlyCode(String t) => CodeHeuristics.isCodeLike(t);

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
