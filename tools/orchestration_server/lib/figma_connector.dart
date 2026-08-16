import 'dart:convert';
import 'dart:io';

/// Zero-cost design intake: pulls a Figma file via the free REST API
/// (the same data the Figma MCP server exposes) and deterministically
/// extracts screens, components, text, and colors so the artifact engine
/// can generate design-aware specs without any model calls.
class FigmaConnector {
  FigmaConnector({String? token, this.apiBase = 'https://api.figma.com'})
      : token = token ?? Platform.environment['FIGMA_TOKEN'];

  final String? token;
  final String apiBase;

  bool get configured => token != null && token!.isNotEmpty;

  /// Extracts the file key from any figma.com URL
  /// (e.g. https://www.figma.com/design/AbC123/My-App?node-id=1-2).
  static String? fileKeyFromUrl(String url) {
    final m = RegExp(r'figma\.com/(?:file|design|proto)/([A-Za-z0-9]+)')
        .firstMatch(url);
    return m?.group(1);
  }

  static bool looksLikeFigmaUrl(String text) =>
      RegExp(r'figma\.com/(?:file|design|proto)/').hasMatch(text);

  Future<Map<String, dynamic>> fetchFile(String fileKey) async {
    if (!configured) {
      throw StateError(
        'FIGMA_TOKEN not set. Create a personal access token in Figma '
        '(Settings → Security → Personal access tokens) and export '
        'FIGMA_TOKEN before starting the API.',
      );
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
    try {
      final req = await client
          .getUrl(Uri.parse('$apiBase/v1/files/$fileKey?depth=4'));
      req.headers.set('X-Figma-Token', token!);
      final res = await req.close().timeout(const Duration(seconds: 30));
      final body = await res.transform(utf8.decoder).join();
      if (res.statusCode != 200) {
        throw HttpException('Figma API ${res.statusCode}: '
            '${body.length > 200 ? body.substring(0, 200) : body}');
      }
      return jsonDecode(body) as Map<String, dynamic>;
    } finally {
      client.close();
    }
  }

  /// Deterministic extraction of design intent from a Figma file document.
  FigmaDesign parseFile(Map<String, dynamic> file) {
    final name = file['name'] as String? ?? 'Untitled';
    final document = file['document'] as Map<String, dynamic>? ?? {};
    final screens = <FigmaScreen>[];
    final components = <String>{};
    final colors = <String>{};

    void collectColors(Map<String, dynamic> node) {
      for (final fill in (node['fills'] as List? ?? [])) {
        if (fill is Map && fill['type'] == 'SOLID' && fill['color'] is Map) {
          final c = fill['color'] as Map;
          String hx(num? v) =>
              ((v ?? 0) * 255).round().toRadixString(16).padLeft(2, '0');
          colors.add('#${hx(c['r'] as num?)}${hx(c['g'] as num?)}'
                  '${hx(c['b'] as num?)}'
              .toUpperCase());
        }
      }
    }

    void walk(Map<String, dynamic> node, {FigmaScreen? screen}) {
      final type = node['type'] as String?;
      final nodeName = node['name'] as String? ?? '';
      collectColors(node);

      FigmaScreen? currentScreen = screen;
      if (type == 'FRAME' && screen == null && nodeName.isNotEmpty) {
        currentScreen = FigmaScreen(nodeName);
        screens.add(currentScreen);
      }
      if ((type == 'COMPONENT' || type == 'INSTANCE') && nodeName.isNotEmpty) {
        components.add(nodeName);
        currentScreen?.components.add(nodeName);
      }
      if (type == 'TEXT') {
        final text = (node['characters'] as String? ?? '').trim();
        if (text.isNotEmpty && text.length <= 80) {
          currentScreen?.texts.add(text);
        }
      }
      for (final child in (node['children'] as List? ?? [])) {
        if (child is Map<String, dynamic>) walk(child, screen: currentScreen);
      }
    }

    walk(document);
    return FigmaDesign(
      fileName: name,
      screens: screens,
      components: components.toList()..sort(),
      colors: colors.take(12).toList(),
    );
  }

  /// Renders the parsed design as a markdown artifact for the spec pipeline.
  String designMarkdown(FigmaDesign design, {String? sourceUrl}) {
    final buf = StringBuffer('# Design intake — ${design.fileName}\n\n')
      ..writeln('> Extracted deterministically from Figma '
          '(zero tokens).${sourceUrl != null ? ' Source: $sourceUrl' : ''}\n');
    buf.writeln('## Screens (${design.screens.length})\n');
    for (final s in design.screens.take(20)) {
      buf.writeln('### ${s.name}\n');
      if (s.components.isNotEmpty) {
        buf.writeln('- Components: ${s.components.take(10).join(', ')}');
      }
      if (s.texts.isNotEmpty) {
        buf.writeln('- Copy: ${s.texts.take(8).map((t) => '"$t"').join(', ')}');
      }
      buf.writeln();
    }
    if (design.components.isNotEmpty) {
      buf
        ..writeln('## Component inventory\n')
        ..writeln(design.components.take(30).map((c) => '- $c').join('\n'))
        ..writeln();
    }
    if (design.colors.isNotEmpty) {
      buf
        ..writeln('## Palette\n')
        ..writeln(design.colors.map((c) => '- `$c`').join('\n'));
    }
    return buf.toString();
  }
}

class FigmaScreen {
  FigmaScreen(this.name);
  final String name;
  final List<String> components = [];
  final List<String> texts = [];
}

class FigmaDesign {
  FigmaDesign({
    required this.fileName,
    required this.screens,
    required this.components,
    required this.colors,
  });

  final String fileName;
  final List<FigmaScreen> screens;
  final List<String> components;
  final List<String> colors;

  /// Requirement fragments derived from the design, one per screen.
  List<String> requirementFragments() => [
        for (final s in screens.take(12))
          'render the "${s.name}" screen'
              '${s.components.isNotEmpty ? ' with ${s.components.take(5).join(', ')}' : ''}',
      ];
}
