// Web-only: embed the live app at [url] as an <iframe> via HtmlElementView.
// This file is only compiled on web (conditional import in app_preview_frame.dart).
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

// A view factory can only be registered once per viewType. We key the viewType
// by the exact URL (port changes on each app launch, so the key changes too,
// giving us a fresh iframe automatically after a rebuild/restart).
final Set<String> _registered = <String>{};

Widget buildAppPreviewFrame(String url, {Key? key}) {
  final viewType = 'adf-app-preview-${url.hashCode}';
  if (!_registered.contains(viewType)) {
    _registered.add(viewType);
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) => html.IFrameElement()
        ..src = url
        ..title = 'Live app preview'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allow = 'clipboard-write; clipboard-read',
    );
  }
  return HtmlElementView(key: key ?? ValueKey(viewType), viewType: viewType);
}
