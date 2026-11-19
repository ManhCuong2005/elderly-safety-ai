import 'dart:convert';
import 'package:http/http.dart' as http;
import 'frame_data.dart';

class LocalAiClient {
  static const base = 'http://127.0.0.1:8765';
  final http.Client client;
  LocalAiClient({http.Client? client}) : client = client ?? http.Client();
  Future<Map<String, dynamic>> health() async => decode(
    await client
        .get(Uri.parse('$base/api/health'))
        .timeout(const Duration(seconds: 3)),
  );
  Future<Map<String, dynamic>> post(
    String route,
    Map<String, dynamic> body,
  ) async => decode(
    await client
        .post(
          Uri.parse('$base/api/$route'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 15)),
  );
  Map<String, dynamic> decode(http.Response response) {
    Map<String, dynamic> body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw Exception('Python trả dữ liệu không hợp lệ. Kiểm tra terminal AI.');
    }
    if (response.statusCode != 200) {
      throw Exception(body['error'] ?? 'AI lỗi HTTP ${response.statusCode}');
    }
    return body;
  }

  Future<String> start() async =>
      (await post('start', {}))['session_id'] as String;
  Future<Map<String, dynamic>> analyze(String session, CapturedFrame frame) =>
      post('analyze', {
        'session_id': session,
        'timestamp_s': frame.timestamp,
        'frame': frame.jpeg,
      });
  Future<void> stop(String session) async {
    await post('stop', {'session_id': session});
  }

  void close() => client.close();
}
