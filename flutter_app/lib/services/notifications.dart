import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AlertLink {
  final String profileId, alertId;
  const AlertLink(this.profileId, this.alertId);
  static AlertLink? parse(Map<String, dynamic> data) {
    final profile = data['profileId'], alert = data['alertId'];
    final valid = RegExp(r'^[A-Za-z0-9_-]{1,100}$');
    if (profile is! String ||
        alert is! String ||
        !valid.hasMatch(profile) ||
        !valid.hasMatch(alert)) {
      return null;
    }
    return AlertLink(profile, alert);
  }
}

class Notifications {
  static final instance = Notifications._();
  Notifications._();
  final local = FlutterLocalNotificationsPlugin();
  final error = ValueNotifier<String?>(null);
  StreamSubscription<String>? refresh;
  String? uid;
  late String deviceId;
  bool enabled = true;
  bool initialized = false;
  AlertLink? pending;
  void Function(AlertLink)? onOpen;
  DocumentReference<Map<String, dynamic>> ref(String user) => FirebaseFirestore
      .instance
      .collection('users')
      .doc(user)
      .collection('devices')
      .doc(deviceId);

  void accept(AlertLink? link) {
    if (link == null) return;
    pending = link;
    flush();
  }

  void flush() {
    if (uid != null && pending != null && onOpen != null) {
      final link = pending!;
      pending = null;
      onOpen!(link);
    }
  }

  Future<void> initialize() async {
    if (initialized) return;
    final prefs = await SharedPreferences.getInstance();
    deviceId =
        prefs.getString('deviceId') ??
        List.generate(
          16,
          (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
        ).join();
    await prefs.setString('deviceId', deviceId);
    enabled = prefs.getBool('notificationsEnabled') ?? true;
    await local.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('ic_safety_notification'),
      ),
      onDidReceiveNotificationResponse: (response) {
        try {
          accept(AlertLink.parse(jsonDecode(response.payload ?? '{}')));
        } catch (_) {
          /* Ignore malformed external payloads. */
        }
      },
    );
    await local
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.createNotificationChannel(
          const AndroidNotificationChannel(
            'safety_alerts',
            'Cảnh báo an toàn',
            description: 'Sự kiện cần người thân kiểm tra',
            importance: Importance.high,
          ),
        );
    FirebaseMessaging.onMessage.listen((message) async {
      if (!enabled || uid == null) return;
      final link = AlertLink.parse(message.data);
      if (link == null) return;
      try {
        // Check current membership before showing a foreground alert.
        final member =
            await FirebaseFirestore.instance
                .doc('profiles/${link.profileId}/caregivers/$uid')
                .get();
        if (!member.exists) return;
        await local.show(
          link.alertId.hashCode & 0x7fffffff,
          message.data['kind'] == 'SIMULATED_TRANSPORT_TEST'
              ? '[KIỂM THỬ] An Tâm'
              : 'Cảnh báo an toàn',
          message.data['kind'] == 'SIMULATED_TRANSPORT_TEST'
              ? 'Thử đường truyền, không phải phát hiện ngã.'
              : 'Có sự kiện cần kiểm tra.',
          const NotificationDetails(
            android: AndroidNotificationDetails(
              'safety_alerts',
              'Cảnh báo an toàn',
              importance: Importance.high,
              priority: Priority.high,
            ),
          ),
          payload: jsonEncode(message.data),
        );
      } catch (_) {
        error.value =
            'Không thể kiểm tra quyền nhận cảnh báo. Hãy kiểm tra kết nối.';
      }
    });
    FirebaseMessaging.onMessageOpenedApp.listen(
      (m) => accept(AlertLink.parse(m.data)),
    );
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) accept(AlertLink.parse(initial.data));
    final launch = await local.getNotificationAppLaunchDetails();
    if (launch?.didNotificationLaunchApp ?? false) {
      try {
        accept(
          AlertLink.parse(
            jsonDecode(launch?.notificationResponse?.payload ?? '{}'),
          ),
        );
      } catch (_) {
        /* Invalid payload */
      }
    }
    initialized = true;
  }

  Future<void> bind(User user) async {
    try {
      await initialize();
      uid = user.uid;
      await refresh?.cancel();
      refresh = FirebaseMessaging.instance.onTokenRefresh.listen(
        (token) {
          unawaited(
            register(token).catchError((Object _) {
              error.value = 'Chưa đồng bộ được mã thông báo mới.';
            }),
          );
        },
        onError: (Object _) {
          error.value = 'Không thể cập nhật thông báo.';
        },
      );
      if (enabled) {
        final permission = await FirebaseMessaging.instance.requestPermission();
        if (permission.authorizationStatus == AuthorizationStatus.denied) {
          error.value =
              'Quyền thông báo bị từ chối. Bật quyền trong Cài đặt Android.';
        } else {
          final token = await FirebaseMessaging.instance.getToken();
          if (token != null) await register(token);
        }
      }
    } catch (_) {
      error.value =
          'Chưa đăng ký được thông báo. Kiểm tra Internet và Google Play Services.';
    }
  }

  Future<void> register(String token) async {
    final user = uid;
    if (user == null ||
        !enabled ||
        FirebaseAuth.instance.currentUser?.uid != user) {
      return;
    }
    await ref(user).set({
      'token': token,
      'platform': 'android',
      'enabled': true,
      'updatedAt': FieldValue.serverTimestamp(),
    });
    error.value = null;
  }

  Future<void> setEnabled(bool value) async {
    final user = uid;
    if (!initialized) await initialize();
    if (value && user != null) {
      enabled = true;
      await bind(FirebaseAuth.instance.currentUser!);
    } else if (user != null) {
      await ref(user).delete();
      enabled = false;
      await local.cancelAll();
    } else {
      enabled = value;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('notificationsEnabled', enabled);
  }

  Future<void> signOut() async {
    await refresh?.cancel();
    if (uid != null && initialized) {
      await ref(uid!).delete();
      await FirebaseMessaging.instance.deleteToken();
    }
    await local.cancelAll();
    uid = null;
    onOpen = null;
    pending = null;
    await FirebaseAuth.instance.signOut();
  }
}
