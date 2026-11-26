import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:elderly_safety_app/widgets/status_card.dart';
import 'package:elderly_safety_app/services/notifications.dart';

void main() {
  test('heartbeat expires and rejects future timestamps', () {
    final now = DateTime.utc(2026, 11, 9, 12);
    expect(
      heartbeatFresh(
        Timestamp.fromDate(now.subtract(const Duration(seconds: 30))),
        now,
      ),
      true,
    );
    expect(
      heartbeatFresh(
        Timestamp.fromDate(now.subtract(const Duration(seconds: 91))),
        now,
      ),
      false,
    );
    expect(
      heartbeatFresh(
        Timestamp.fromDate(now.add(const Duration(minutes: 5))),
        now,
      ),
      false,
    );
    expect(heartbeatFresh(null, now), false);
  });
  test('notification link validates identifiers', () {
    expect(AlertLink.parse({'profileId': 'p1', 'alertId': 'a1'}), isNotNull);
    expect(
      AlertLink.parse({'profileId': '../private', 'alertId': 'a1'}),
      isNull,
    );
    expect(AlertLink.parse({'profileId': 1, 'alertId': 'a1'}), isNull);
  });
  testWidgets('stale status is never presented as live', (tester) async {
    final now = DateTime.utc(2026, 11, 9, 12);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusCard(
            now: now,
            data: {
              'posture': 'STANDING',
              'engine_online': true,
              'camera_online': true,
              'heartbeat': Timestamp.fromDate(
                now.subtract(const Duration(minutes: 2)),
              ),
            },
          ),
        ),
      ),
    );
    expect(find.text('AI Engine ngoại tuyến'), findsOneWidget);
    expect(find.text('Chưa có trạng thái trực tiếp'), findsOneWidget);
  });
  testWidgets('cached status does not claim verified connectivity', (
    tester,
  ) async {
    final now = DateTime.utc(2026, 11, 9, 12);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatusCard(
            now: now,
            cached: true,
            data: {
              'posture': 'LYING',
              'engine_online': true,
              'camera_online': true,
              'heartbeat': Timestamp.fromDate(now),
            },
          ),
        ),
      ),
    );
    expect(
      find.text('Dữ liệu lưu tạm • chưa xác minh kết nối'),
      findsOneWidget,
    );
  });
  test('bending posture label is supported in Vietnamese', () {
    expect(postureLabel('BENDING'), 'Đang cúi người');
  });
}
