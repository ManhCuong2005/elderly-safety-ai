import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

String timeLabel(dynamic value) =>
    value is Timestamp
        ? DateFormat('dd/MM/yyyy HH:mm:ss').format(value.toDate().toLocal())
        : 'Chưa có dữ liệu';
String postureLabel(String? value) =>
    const {
      'STANDING': 'Đang đứng',
      'SITTING': 'Đang ngồi',
      'LYING': 'Đang nằm',
      'WALKING': 'Đang đi lại',
      'UNKNOWN': 'Chưa xác định',
    }[value] ??
    'Chưa xác định';
bool heartbeatFresh(dynamic value, DateTime now) {
  if (value is! Timestamp) return false;
  final age = now.difference(value.toDate()).inSeconds;
  return age >= -5 && age <= 90;
}

class StatusCard extends StatelessWidget {
  final Map<String, dynamic> data;
  final DateTime now;
  final bool cached;
  const StatusCard({
    super.key,
    required this.data,
    required this.now,
    this.cached = false,
  });
  @override
  Widget build(BuildContext context) {
    final fresh = heartbeatFresh(data['heartbeat'], now);
    final online = fresh && data['engine_online'] == true && !cached;
    final camera = online && data['camera_online'] == true;
    final danger = data['fsm'] == 'ALERT';
    final status = data['person_status'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  danger
                      ? Icons.warning_amber_rounded
                      : Icons.health_and_safety_outlined,
                  color: danger ? Colors.red : Colors.teal,
                  size: 36,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    online
                        ? 'Đang giám sát'
                        : cached
                        ? 'Dữ liệu lưu tạm • chưa xác minh kết nối'
                        : 'AI Engine ngoại tuyến',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Text(
              online
                  ? postureLabel(data['posture'])
                  : 'Chưa có trạng thái trực tiếp',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            if (!online)
              Text(
                'Tư thế ghi nhận gần nhất: ${postureLabel(data['posture'])}',
              ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(
                  label: Text(
                    'Camera: ${camera ? 'trực tuyến' : 'ngoại tuyến'}',
                  ),
                ),
                Chip(
                  label: Text('AI: ${online ? 'trực tuyến' : 'ngoại tuyến'}'),
                ),
              ],
            ),
            if (status != 'DETECTED')
              Text(
                status == 'PERSON_NOT_DETECTED'
                    ? 'Không thấy người trong khung hình.'
                    : 'Chưa quan sát tin cậy: ${status ?? 'chưa có dữ liệu'}',
              ),
            if (danger)
              const Text(
                'Có cảnh báo cần kiểm tra trong mục Cảnh báo.',
                style: TextStyle(
                  color: Colors.red,
                  fontWeight: FontWeight.bold,
                ),
              ),
            const SizedBox(height: 12),
            Text('Cập nhật: ${timeLabel(data['updatedAt'])}'),
          ],
        ),
      ),
    );
  }
}
