import 'package:flutter/material.dart';

/// Non-web fallback: the live iframe preview only exists on the web build.
Widget buildAppPreviewFrame(String url, {Key? key}) {
  return const Center(
    child: Padding(
      padding: EdgeInsets.all(24),
      child: Text(
        'Live app preview is available in the web dashboard.',
        textAlign: TextAlign.center,
      ),
    ),
  );
}
