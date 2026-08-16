// Renders the live built app inside the dashboard. The real implementation is
// web-only (it embeds an <iframe> via HtmlElementView); the stub covers non-web
// analysis/builds. Conditional import keeps `flutter analyze` clean everywhere.
export 'app_preview_frame_stub.dart'
    if (dart.library.html) 'app_preview_frame_web.dart';
