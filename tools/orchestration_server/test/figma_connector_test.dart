import 'package:orchestration_server/figma_connector.dart';
import 'package:test/test.dart';

Map<String, dynamic> fixtureFile() => {
      'name': 'POS Redesign',
      'document': {
        'type': 'DOCUMENT',
        'children': [
          {
            'type': 'CANVAS',
            'name': 'Page 1',
            'children': [
              {
                'type': 'FRAME',
                'name': 'Checkout Screen',
                'fills': [
                  {
                    'type': 'SOLID',
                    'color': {'r': 1, 'g': 1, 'b': 1},
                  }
                ],
                'children': [
                  {
                    'type': 'INSTANCE',
                    'name': 'PrimaryButton',
                    'children': [
                      {'type': 'TEXT', 'characters': 'Pay now'},
                    ],
                  },
                  {'type': 'TEXT', 'characters': 'Order total'},
                ],
              },
              {
                'type': 'FRAME',
                'name': 'Receipt Screen',
                'children': [
                  {'type': 'COMPONENT', 'name': 'ReceiptCard'},
                ],
              },
            ],
          },
        ],
      },
    };

void main() {
  final connector = FigmaConnector(token: 'test-token');

  test('extracts file key from design and file URLs', () {
    expect(
      FigmaConnector.fileKeyFromUrl(
          'https://www.figma.com/design/AbC123xyz/My-App?node-id=1-2'),
      'AbC123xyz',
    );
    expect(
      FigmaConnector.fileKeyFromUrl('https://figma.com/file/K9y8/POS'),
      'K9y8',
    );
    expect(FigmaConnector.fileKeyFromUrl('https://example.com/x'), isNull);
    expect(
      FigmaConnector.looksLikeFigmaUrl('see https://figma.com/design/A1/x'),
      isTrue,
    );
  });

  test('parses screens, components, copy, and palette from file JSON', () {
    final design = connector.parseFile(fixtureFile());
    expect(design.fileName, 'POS Redesign');
    expect(design.screens.map((s) => s.name),
        containsAll(['Checkout Screen', 'Receipt Screen']));
    expect(design.components, containsAll(['PrimaryButton', 'ReceiptCard']));
    final checkout =
        design.screens.firstWhere((s) => s.name == 'Checkout Screen');
    expect(checkout.texts, contains('Pay now'));
    expect(design.colors, contains('#FFFFFF'));
  });

  test('design markdown and requirement fragments are spec-ready', () {
    final design = connector.parseFile(fixtureFile());
    final md = connector.designMarkdown(design, sourceUrl: 'https://x');
    expect(md, contains('## Screens (2)'));
    expect(md, contains('### Checkout Screen'));
    expect(md, contains('`#FFFFFF`'));

    final fragments = design.requirementFragments();
    expect(fragments, hasLength(2));
    expect(fragments.first, contains('"Checkout Screen"'));
    expect(fragments.first, contains('PrimaryButton'));
  });

  test('unconfigured connector fails with actionable error', () {
    final bare = FigmaConnector(token: '');
    expect(bare.configured, isFalse);
    expect(() => bare.fetchFile('abc'), throwsStateError);
  });
}
