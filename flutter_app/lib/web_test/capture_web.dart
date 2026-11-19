import 'dart:async';
import 'dart:js_interop';
import 'dart:math' as math;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;
import 'frame_data.dart';

class CaptureController {
  static int nextId = 0;
  late final String viewType = 'an-tam-video-${nextId++}';
  final video = web.HTMLVideoElement();
  final container = web.HTMLDivElement();
  final canvas = web.HTMLCanvasElement();
  final input = web.HTMLInputElement();
  web.MediaStream? stream;
  String? objectUrl;
  Completer<bool>? selection;
  bool isFile = false;
  bool cropRight = false;
  int revision = 0;

  CaptureController() {
    container.style
      ..width = '100%'
      ..height = '100%'
      ..position = 'relative'
      ..overflow = 'hidden'
      ..contain = 'strict';
    video
      ..autoplay = true
      ..muted = true
      ..playsInline = true;
    video.style
      ..width = '100%'
      ..height = '100%'
      ..position = 'absolute'
      ..left = '0'
      ..top = '0'
      ..display = 'block'
      ..objectFit = 'contain'
      ..backgroundColor = '#10262b';
    container.append(video);
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int id) => container,
    );
    input
      ..type = 'file'
      ..accept = 'video/*';
    input.style.display = 'none';
    web.document.body!.append(input);
    input.addEventListener(
      'change',
      ((web.Event event) {
        final file = input.files?.item(0);
        if (file == null) {
          selection?.complete(false);
          selection = null;
          return;
        }
        final pending = selection;
        _release();
        isFile = true;
        final version = revision;
        objectUrl = web.URL.createObjectURL(file);
        video.autoplay = false;
        video.src = objectUrl!;
        video.controls = true;
        video.addEventListener(
          'loadeddata',
          ((web.Event event) {
            if (version == revision) {
              setCropRight(
                RegExp(
                      r'^(fall|adl)-\d+-cam[01]\.mp4$',
                      caseSensitive: false,
                    ).hasMatch(file.name) &&
                    video.videoWidth / video.videoHeight > 2.4,
              );
            }
            if (pending != null && !pending.isCompleted) {
              pending.complete(version == revision);
            }
            if (identical(selection, pending)) selection = null;
          }).toJS,
          web.AddEventListenerOptions(once: true),
        );
        video.addEventListener(
          'error',
          ((web.Event event) {
            if (pending != null && !pending.isCompleted) {
              pending.completeError(
                StateError(
                  'Video không đọc được. Dùng MP4 có codec trình duyệt hỗ trợ.',
                ),
              );
            }
            if (identical(selection, pending)) selection = null;
          }).toJS,
          web.AddEventListenerOptions(once: true),
        );
        video.load();
      }).toJS,
    );
    input.addEventListener(
      'cancel',
      ((web.Event event) {
        selection?.complete(false);
        selection = null;
      }).toJS,
    );
  }

  bool get ended => isFile && video.ended;
  double get aspectRatio =>
      video.videoHeight > 0
          ? video.videoWidth / (cropRight ? 2 : 1) / video.videoHeight
          : 4 / 3;
  void setCropRight(bool value) {
    cropRight = value;
    video.style.objectFit = value ? 'cover' : 'contain';
    video.style.objectPosition = value ? 'right center' : 'center';
  }

  Widget preview() => HtmlElementView(viewType: viewType);

  Future<void> startCamera() async {
    stop();
    final version = revision;
    isFile = false;
    setCropRight(false);
    video.controls = false;
    video.autoplay = true;
    final acquired =
        await web.window.navigator.mediaDevices
            .getUserMedia(
              web.MediaStreamConstraints(video: true.toJS, audio: false.toJS),
            )
            .toDart;
    if (version != revision) {
      for (final track in acquired.getTracks().toDart) {
        track.stop();
      }
      throw StateError('Đã hủy mở camera.');
    }
    stream = acquired;
    video.srcObject = stream;
    await video.play().toDart;
  }

  Future<bool> chooseVideo() {
    stop();
    selection = Completer<bool>();
    input.value = '';
    input.click();
    return selection!.future;
  }

  CapturedFrame? capture() {
    if (video.readyState < 2 ||
        video.videoWidth == 0 ||
        video.videoHeight == 0) {
      return null;
    }
    final sourceX = cropRight ? video.videoWidth ~/ 2 : 0;
    final sourceWidth = video.videoWidth - sourceX;
    final scale = math.min(1.0, 640 / math.max(sourceWidth, video.videoHeight));
    final width = math.max(16, (sourceWidth * scale).round());
    final height = math.max(16, (video.videoHeight * scale).round());
    canvas.width = width;
    canvas.height = height;
    final context = canvas.getContext('2d') as web.CanvasRenderingContext2D;
    context.drawImage(
      video,
      sourceX,
      0,
      sourceWidth,
      video.videoHeight,
      0,
      0,
      width,
      height,
    );
    return CapturedFrame(
      canvas.toDataURL('image/jpeg', .85.toJS),
      video.currentTime,
      width,
      height,
    );
  }

  Future<void> play() async {
    await video.play().toDart;
  }

  void _release() {
    revision++;
    video.pause();
    for (final track
        in stream?.getTracks().toDart ?? <web.MediaStreamTrack>[]) {
      track.stop();
    }
    stream = null;
    video.srcObject = null;
    video.removeAttribute('src');
    if (objectUrl != null) {
      web.URL.revokeObjectURL(objectUrl!);
      objectUrl = null;
    }
  }

  void stop() {
    _release();
    if (selection != null && !selection!.isCompleted) {
      selection!.complete(false);
    }
    selection = null;
  }

  void dispose() {
    stop();
    input.remove();
  }
}
