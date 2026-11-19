import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:elderly_safety_app/web_test/local_ai_client.dart';
import 'package:elderly_safety_app/web_test/frame_data.dart';

void main() {
  test(
    'analyze carries source timestamp and session without cloud data',
    () async {
      final client = LocalAiClient(
        client: MockClient((request) async {
          expect(request.url.toString(), 'http://127.0.0.1:8765/api/analyze');
          final body = jsonDecode(request.body) as Map;
          expect(body['timestamp_s'], 1.25);
          expect(body['session_id'], 'local-session');
          expect(body.containsKey('firebase'), false);
          return http.Response(
            jsonEncode({
              'posture': 'STANDING',
              'mode': 'local',
              'notifications': false,
            }),
            200,
          );
        }),
      );
      final result = await client.analyze(
        'local-session',
        const CapturedFrame('data:image/jpeg;base64,AA==', 1.25, 640, 480),
      );
      expect(result['posture'], 'STANDING');
      client.close();
    },
  );
  test(
    'expired session remains an error instead of fabricated predictions',
    () async {
      final client = LocalAiClient(
        client: MockClient(
          (_) async =>
              http.Response(jsonEncode({'error': 'Session expired'}), 409),
        ),
      );
      await expectLater(client.start(), throwsException);
      client.close();
    },
  );
  test('HTML proxy failure is handled as an error', () async {
    final client = LocalAiClient(
      client: MockClient(
        (_) async => http.Response('<html>Bad gateway</html>', 502),
      ),
    );
    await expectLater(client.health(), throwsException);
    client.close();
  });
}
