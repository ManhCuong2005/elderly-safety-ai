import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/semantics.dart';
import 'capture.dart';
import 'local_ai_client.dart';

SemanticsHandle? _webSemantics;
void enableWebTestSemantics() {
  _webSemantics ??= SemanticsBinding.instance.ensureSemantics();
}

class WebAiTestApp extends StatelessWidget {
  const WebAiTestApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'An Tâm • Phòng thử nhận diện',
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff007f86)),
      scaffoldBackgroundColor: const Color(0xfff1f6f6),
      cardTheme: CardTheme(
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      ),
    ),
    home: const WebAiTestPage(),
  );
}

String poseName(String? value) =>
    const {
      'STANDING': 'Đang đứng',
      'SITTING': 'Đang ngồi',
      'LYING': 'Đang nằm',
      'WALKING': 'Đang đi lại',
      'UNKNOWN': 'Chưa xác định',
    }[value] ??
    'Chưa có kết quả';
String fsmName(String? value) =>
    const {
      'NORMAL': 'Bình thường',
      'SUSPECTED_FALL': 'Nghi ngờ té ngã',
      'VERIFYING': 'Đang xác minh',
      'ALERT': 'Có cảnh báo nghi ngờ',
      'RECOVERED': 'Đã phục hồi',
    }[value] ??
    'Chưa phân tích';

String eventName(String? value) =>
    const {
      'SUSPECTED_FALL': 'Nghi ngờ té ngã',
      'POSSIBLE_FALL': 'Cảnh báo nghi ngờ sau xác minh',
      'RECOVERED': 'Quan sát thấy phục hồi',
      'UNVERIFIED_CANDIDATE': 'Chưa đủ bằng chứng xác minh',
      'LYING_TOO_LONG': 'Nằm kéo dài',
      'ABNORMAL_INACTIVITY': 'Bất động kéo dài',
    }[value] ??
    value ??
    'Sự kiện';

class WebAiTestPage extends StatefulWidget {
  const WebAiTestPage({super.key});
  @override
  State<WebAiTestPage> createState() => _WebAiTestPageState();
}

class _WebAiTestPageState extends State<WebAiTestPage> {
  final capture = CaptureController();
  final api = LocalAiClient();
  bool connected = false, busy = false, running = false;
  String? error, session, source;
  int generation = 0, frames = 0;
  double? lastTime;
  Map<String, dynamic>? result;
  final List<Map<String, dynamic>> events = [];
  @override
  void initState() {
    super.initState();
    unawaited(checkConnection());
  }

  Future<void> checkConnection() async {
    try {
      final health = await api.health();
      if (mounted) {
        setState(() {
          connected = health['model_present'] == true;
          error = null;
        });
      }
    } catch (_) {
      if (mounted) setState(() => connected = false);
    }
  }

  Future<void> start(bool camera) async {
    if (busy) return;
    final token = ++generation;
    running = false;
    capture.stop();
    final old = session;
    session = null;
    if (old != null) unawaited(api.stop(old).catchError((Object _) {}));
    setState(() {
      busy = true;
      error = null;
      result = null;
      events.clear();
      frames = 0;
      lastTime = null;
    });
    try {
      // File chooser must open in the direct user gesture, before HTTP awaits.
      final selected = camera ? null : capture.chooseVideo();
      if (camera) {
        await api.health();
        await capture.startCamera();
      } else if (!await selected!) {
        return;
      }
      if (!mounted || token != generation) {
        return;
      }
      final fresh = await api.start();
      if (!mounted || token != generation) {
        unawaited(api.stop(fresh).catchError((Object _) {}));
        return;
      }
      session = fresh;
      await capture.play();
      if (!mounted || token != generation) return;
      setState(() {
        connected = true;
        running = true;
        source = camera ? 'Webcam trình duyệt' : 'Video đã chọn';
      });
      unawaited(processFrames(token));
    } catch (e) {
      if (mounted && token == generation) {
        capture.stop();
        setState(() {
          running = false;
          error =
              'Không thể bắt đầu. Kiểm tra Python AI đang chạy và quyền camera/video. $e';
        });
      }
    } finally {
      if (mounted && token == generation) setState(() => busy = false);
    }
  }

  Future<void> processFrames(int token) async {
    while (mounted && running && generation == token) {
      final before = DateTime.now();
      try {
        if (capture.ended) {
          running = false;
          final old = session;
          session = null;
          if (mounted) setState(() => source = 'Video đã kết thúc');
          if (old != null) {
            try {
              await api.stop(old);
            } catch (_) {
              /* Already expired */
            }
          }
          break;
        }
        final frame = capture.capture();
        if (frame == null) {
          await Future<void>.delayed(const Duration(milliseconds: 100));
          continue;
        }
        if (lastTime != null &&
            capture.isFile &&
            (frame.timestamp < lastTime! - .001 ||
                frame.timestamp - lastTime! > 1)) {
          session = await api.start();
          if (!mounted || generation != token) break;
          lastTime = null;
          if (mounted) {
            setState(() {
              result = null;
              events.clear();
              frames = 0;
            });
          }
        }
        if (lastTime != null && frame.timestamp <= lastTime! + .001) {
          await Future<void>.delayed(const Duration(milliseconds: 70));
          continue;
        }
        final answer = await api.analyze(session!, frame);
        if (!mounted || generation != token) break;
        lastTime = frame.timestamp;
        setState(() {
          result = answer;
          frames++;
          for (final event in (answer['events'] as List? ?? [])) {
            if (event is Map && event['kind'] != 'POSTURE_CHANGE') {
              events.insert(0, Map<String, dynamic>.from(event));
            }
          }
          if (events.length > 10) events.removeRange(10, events.length);
        });
      } catch (e) {
        if (mounted && generation == token) {
          capture.stop();
          setState(() {
            running = false;
            error = 'Phân tích đã dừng: $e';
          });
        }
        break;
      }
      final wait = 100 - DateTime.now().difference(before).inMilliseconds;
      if (wait > 0) await Future<void>.delayed(Duration(milliseconds: wait));
    }
  }

  Future<void> stop() async {
    generation++;
    running = false;
    capture.stop();
    final old = session;
    session = null;
    if (mounted) setState(() => busy = false);
    if (old != null) {
      try {
        await api.stop(old);
      } catch (_) {
        /* Backend may already have expired the session. */
      }
    }
  }

  Future<void> reset() async {
    if (!running || busy) return;
    final token = ++generation;
    setState(() => busy = true);
    try {
      session = await api.start();
      lastTime = null;
      if (mounted) {
        setState(() {
          result = null;
          events.clear();
          frames = 0;
        });
        unawaited(processFrames(token));
      }
    } catch (e) {
      if (mounted) setState(() => error = 'Không thể tạo lại phiên: $e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> setRgbPanel(bool value) async {
    capture.setCropRight(value);
    setState(() {
      result = null;
      events.clear();
      frames = 0;
    });
    if (running) await reset();
  }

  @override
  void dispose() {
    generation++;
    running = false;
    capture.dispose();
    api.close();
    super.dispose();
  }

  Widget previewPanel() => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.videocam_outlined, color: Color(0xff007f86)),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  source ?? 'Chọn nguồn hình ảnh',
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (running) const Chip(label: Text('Đang phân tích')),
            ],
          ),
          const SizedBox(height: 16),
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: AspectRatio(
              aspectRatio: capture.aspectRatio,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  const ColoredBox(color: Color(0xff10262b)),
                  capture.preview(),
                  if (source == null)
                    const IgnorePointer(
                      child: Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              Icons.accessibility_new_rounded,
                              size: 64,
                              color: Colors.white54,
                            ),
                            SizedBox(height: 16),
                            Text(
                              'Webcam hoặc video để bắt đầu',
                              style: TextStyle(
                                color: Colors.white70,
                                fontSize: 17,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  IgnorePointer(
                    child: CustomPaint(
                      painter: PosePainter(result?['landmarks'] as List?),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          if (capture.isFile && source != null)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: const Text(
                'Dùng nửa RGB bên phải (video UR Fall ghép depth/RGB)',
              ),
              subtitle: const Text('Tắt với video RGB thông thường.'),
              value: capture.cropRight,
              onChanged: busy ? null : setRgbPanel,
            ),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              FilledButton.icon(
                onPressed: busy ? null : () => start(true),
                icon: const Icon(Icons.videocam),
                label: const Text('Bật webcam'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : () => start(false),
                icon: const Icon(Icons.video_file_outlined),
                label: const Text('Chọn video'),
              ),
              OutlinedButton.icon(
                onPressed: running || busy ? stop : null,
                icon: const Icon(Icons.stop_rounded),
                label: const Text('Dừng'),
              ),
              TextButton.icon(
                onPressed: running && !busy ? reset : null,
                icon: const Icon(Icons.restart_alt),
                label: const Text('Chọn lại người / reset'),
              ),
            ],
          ),
          if (busy)
            const Padding(
              padding: EdgeInsets.only(top: 12),
              child: LinearProgressIndicator(),
            ),
          const SizedBox(height: 12),
          const Text(
            'Đặt camera thấy toàn thân và một người trong khung hình. Có thể tua video; hệ thống tạo lại bằng chứng khi phát lại.',
          ),
        ],
      ),
    ),
  );

  Widget metric(String label, String value, IconData icon, {Color? color}) =>
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color ?? const Color(0xff007f86)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(color: Colors.black54)),
                  const SizedBox(height: 4),
                  Text(
                    value,
                    style: TextStyle(
                      fontSize: 21,
                      fontWeight: FontWeight.w600,
                      color: color,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );

  Widget resultPanel() {
    final features = result?['features'] as Map?;
    final confidence = (features?['confidence'] as num?);
    final inference = result?['inference_ms'] as num?;
    final person = result?['person_status'] as String?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Kết quả nhận diện',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 14),
                metric(
                  'Tư thế / hành động',
                  poseName(result?['posture']),
                  Icons.accessibility_new,
                ),
                const Divider(),
                metric(
                  'Trạng thái phân tích',
                  fsmName(result?['fsm']),
                  Icons.health_and_safety_outlined,
                  color:
                      ['SUSPECTED_FALL', 'ALERT'].contains(result?['fsm'])
                          ? Colors.deepOrange
                          : null,
                ),
                const Divider(),
                metric(
                  'Độ tin cậy pose',
                  confidence == null
                      ? 'Chưa đủ bằng chứng'
                      : '${(confidence * 100).toStringAsFixed(0)}%',
                  Icons.insights_outlined,
                ),
                Text(
                  '$frames frame đã xử lý${inference == null ? '' : ' • ${inference.toStringAsFixed(0)} ms AI/frame'}',
                ),
                if (person != null && person != 'DETECTED')
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      person.contains('RESET')
                          ? 'Mục tiêu chưa rõ. Kiểm tra cảnh rồi bấm chọn lại người.'
                          : person == 'PERSON_NOT_DETECTED'
                          ? 'Không thấy người trong khung hình.'
                          : 'Pose chưa đủ tin cậy để nhận diện.',
                      style: const TextStyle(color: Colors.deepOrange),
                    ),
                  ),
                const SizedBox(height: 14),
                const Text(
                  'Độ tin cậy pose là chất lượng khớp cơ thể, không phải xác suất té ngã.',
                  style: TextStyle(fontSize: 12, color: Colors.black54),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Sự kiện trong phiên',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 14),
                if (events.isEmpty) const Text('Chưa có sự kiện bất thường.'),
                ...events.map(
                  (event) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      '${eventName(event['kind'])} • ${(event['timestamp'] as num).toStringAsFixed(2)}s',
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1380),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  alignment: WrapAlignment.spaceBetween,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  runSpacing: 12,
                  children: [
                    const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.health_and_safety_rounded,
                          size: 40,
                          color: Color(0xff007f86),
                        ),
                        SizedBox(width: 12),
                        Text(
                          'An Tâm',
                          style: TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                    ActionChip(
                      avatar: Icon(
                        connected ? Icons.check_circle : Icons.link_off,
                        color: connected ? Colors.teal : Colors.deepOrange,
                      ),
                      label: Text(
                        connected
                            ? 'Python AI đã kết nối'
                            : 'Chưa kết nối Python AI',
                      ),
                      onPressed: checkConnection,
                    ),
                  ],
                ),
                const SizedBox(height: 28),
                const Text(
                  'Phòng thử nhận diện',
                  style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Chọn webcam hoặc video và xem kết quả từ thuật toán Python đang có.',
                  style: TextStyle(fontSize: 16, color: Colors.black54),
                ),
                const SizedBox(height: 18),
                if (!connected)
                  Card(
                    color: const Color(0xfffff3dc),
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Wrap(
                        spacing: 16,
                        runSpacing: 10,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          const Text(
                            'Mở terminal ở project và chạy: scripts\\run-web-ai.cmd',
                          ),
                          TextButton.icon(
                            onPressed:
                                () => Clipboard.setData(
                                  const ClipboardData(
                                    text: '.\\scripts\\run-web-ai.cmd',
                                  ),
                                ),
                            icon: const Icon(Icons.copy, size: 16),
                            label: const Text('Sao chép lệnh'),
                          ),
                          TextButton(
                            onPressed: checkConnection,
                            child: const Text('Kiểm tra kết nối'),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Card(
                      color: const Color(0xffffe9e5),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(
                          error!,
                          style: const TextStyle(color: Color(0xff9b2616)),
                        ),
                      ),
                    ),
                  ),
                const SizedBox(height: 6),
                LayoutBuilder(
                  builder:
                      (context, box) =>
                          box.maxWidth >= 980
                              ? Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(flex: 3, child: previewPanel()),
                                  const SizedBox(width: 18),
                                  Expanded(flex: 2, child: resultPanel()),
                                ],
                              )
                              : Column(
                                children: [
                                  previewPanel(),
                                  const SizedBox(height: 16),
                                  resultPanel(),
                                ],
                              ),
                ),
                const SizedBox(height: 18),
                const Text(
                  'LOCAL TEST • Thuật toán V1 đang thử nghiệm. Phiên này không gửi Firebase hoặc thông báo.',
                  style: TextStyle(color: Colors.black54, fontSize: 12),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class PosePainter extends CustomPainter {
  final List? points;
  PosePainter(this.points);
  static const edges = [
    [11, 12],
    [11, 23],
    [12, 24],
    [23, 24],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
    [23, 25],
    [25, 27],
    [24, 26],
    [26, 28],
  ];
  @override
  void paint(Canvas canvas, Size size) {
    if (points == null || points!.length != 33) return;
    final line =
        Paint()
          ..color = const Color(0xff4de1b5)
          ..strokeWidth = 3;
    final dot = Paint()..color = const Color(0xffffd166);
    for (final edge in edges) {
      final a = points![edge[0]] as List, b = points![edge[1]] as List;
      if ((a[3] as num) < .5 || (b[3] as num) < .5) continue;
      final p = Offset((a[0] as num) * size.width, (a[1] as num) * size.height);
      final q = Offset((b[0] as num) * size.width, (b[1] as num) * size.height);
      canvas.drawLine(p, q, line);
      canvas.drawCircle(p, 4, dot);
      canvas.drawCircle(q, 4, dot);
    }
  }

  @override
  bool shouldRepaint(covariant PosePainter oldDelegate) =>
      oldDelegate.points != points;
}
