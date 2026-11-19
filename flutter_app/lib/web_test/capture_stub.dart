import 'package:flutter/material.dart';
import 'frame_data.dart';

class CaptureController {
  bool get isFile => false;
  bool get ended => false;
  bool get cropRight => false;
  void setCropRight(bool value) {}
  double get aspectRatio => 4 / 3;
  Widget preview() => const SizedBox.shrink();
  Future<void> startCamera() async =>
      throw UnsupportedError('Web capture only');
  Future<bool> chooseVideo() async => false;
  CapturedFrame? capture() => null;
  Future<void> play() async {}
  void stop() {}
  void dispose() {}
}
