import 'dart:async';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'web_test/web_app.dart';
import 'firebase_options.dart';
import 'services/notifications.dart';
import 'widgets/status_card.dart';

final navigatorKey = GlobalKey<NavigatorState>();
@pragma('vm:entry-point')
Future<void> backgroundMessage(RemoteMessage message) async {
  await Firebase.initializeApp(options: DefaultFirebaseOptions.android);
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (kIsWeb) {
    enableWebTestSemantics();
    runApp(const WebAiTestApp());
    return;
  }
  try {
    await Firebase.initializeApp(options: DefaultFirebaseOptions.android);
    FirebaseMessaging.onBackgroundMessage(backgroundMessage);
    runApp(const SafetyApp());
  } catch (_) {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: Padding(
              padding: EdgeInsets.all(32),
              child: Text(
                'Không thể khởi tạo Firebase. Kiểm tra google-services.json và cấu hình Android, rồi mở lại ứng dụng.',
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class SafetyApp extends StatelessWidget {
  const SafetyApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    navigatorKey: navigatorKey,
    debugShowCheckedModeBanner: false,
    title: 'An Tâm • Người thân',
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff007f86)),
      scaffoldBackgroundColor: const Color(0xfff3f7f8),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
      cardTheme: CardThemeData(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        elevation: 0,
      ),
    ),
    home: StreamBuilder<User?>(
      stream: FirebaseAuth.instance.authStateChanges(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return snapshot.data == null
            ? const LoginPage()
            : HomePage(key: ValueKey(snapshot.data!.uid), user: snapshot.data!);
      },
    ),
  );
}

String friendlyError(Object? error) {
  if (error is FirebaseException) {
    return switch (error.code) {
      'permission-denied' => 'Bạn chưa được cấp quyền xem hồ sơ này.',
      'unavailable' || 'network-request-failed' =>
        'Không thể kết nối. Kiểm tra Internet rồi thử lại.',
      'invalid-credential' ||
      'wrong-password' ||
      'user-not-found' => 'Email hoặc mật khẩu không đúng.',
      'invalid-email' => 'Email chưa đúng định dạng.',
      'too-many-requests' => 'Có quá nhiều yêu cầu. Vui lòng thử lại sau.',
      'user-disabled' => 'Tài khoản đã bị vô hiệu hóa.',
      _ => 'Không thể hoàn tất thao tác (${error.code}).',
    };
  }
  return 'Đã có lỗi. Kiểm tra kết nối và thử lại.';
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final email = TextEditingController(), password = TextEditingController();
  final form = GlobalKey<FormState>();
  bool busy = false, hidden = true;
  String? error;
  @override
  void dispose() {
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit({bool reset = false}) async {
    if (reset ? !email.text.contains('@') : !form.currentState!.validate()) {
      if (reset) {
        setState(
          () => error = 'Nhập email để nhận hướng dẫn đặt lại mật khẩu.',
        );
      }
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (reset) {
        await FirebaseAuth.instance.sendPasswordResetEmail(
          email: email.text.trim(),
        );
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Nếu email có tài khoản, bạn sẽ nhận được hướng dẫn đặt lại mật khẩu.',
              ),
            ),
          );
        }
      } else {
        await FirebaseAuth.instance.signInWithEmailAndPassword(
          email: email.text.trim(),
          password: password.text,
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = friendlyError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Form(
              key: form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(
                    Icons.health_and_safety_rounded,
                    size: 72,
                    color: Color(0xff007f86),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'An Tâm',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.displaySmall,
                  ),
                  const Text(
                    'Kết nối và chăm sóc người thân',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 32),
                  TextFormField(
                    controller: email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    decoration: const InputDecoration(
                      labelText: 'Email',
                      prefixIcon: Icon(Icons.mail_outline),
                    ),
                    validator:
                        (v) =>
                            v != null && v.contains('@')
                                ? null
                                : 'Nhập email hợp lệ',
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: password,
                    obscureText: hidden,
                    autofillHints: const [AutofillHints.password],
                    onFieldSubmitted: (_) => busy ? null : submit(),
                    decoration: InputDecoration(
                      labelText: 'Mật khẩu',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(
                        onPressed: () => setState(() => hidden = !hidden),
                        icon: Icon(
                          hidden
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined,
                        ),
                      ),
                    ),
                    validator:
                        (v) => v == null || v.isEmpty ? 'Nhập mật khẩu' : null,
                  ),
                  const SizedBox(height: 16),
                  if (error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: Text(
                        error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  FilledButton(
                    onPressed: busy ? null : () => submit(),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(busy ? 'Đang kết nối…' : 'Đăng nhập'),
                    ),
                  ),
                  TextButton(
                    onPressed: busy ? null : () => submit(reset: true),
                    child: const Text('Quên mật khẩu?'),
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'Hồ sơ và quyền người chăm sóc do quản trị viên liên kết.',
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class MessageState extends StatelessWidget {
  final String text;
  final IconData icon;
  const MessageState(this.text, {super.key, this.icon = Icons.info_outline});
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 48, color: Colors.teal),
          const SizedBox(height: 16),
          Text(text, textAlign: TextAlign.center),
        ],
      ),
    ),
  );
}

class HomePage extends StatefulWidget {
  final User user;
  const HomePage({super.key, required this.user});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String? selected;
  int tab = 0;
  @override
  void initState() {
    super.initState();
    unawaited(
      Notifications.instance.bind(widget.user).then((_) {
        if (!mounted) return;
        Notifications.instance.onOpen = (link) {
          navigatorKey.currentState?.push(
            MaterialPageRoute(
              builder:
                  (_) => AlertDetail(
                    profileId: link.profileId,
                    alertId: link.alertId,
                  ),
            ),
          );
        };
        Notifications.instance.flush();
      }),
    );
  }

  @override
  void dispose() {
    Notifications.instance.onOpen = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('An Tâm'),
      actions: [
        IconButton(
          tooltip: 'Cài đặt',
          onPressed:
              () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const SettingsPage()),
              ),
          icon: const Icon(Icons.settings_outlined),
        ),
      ],
    ),
    body: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
      stream: FirebaseFirestore.instance
          .collection('users')
          .doc(widget.user.uid)
          .collection('profiles')
          .snapshots(includeMetadataChanges: true),
      builder: (context, s) {
        if (s.hasError) return MessageState(friendlyError(s.error));
        if (!s.hasData) return const Center(child: CircularProgressIndicator());
        final links = s.data!.docs;
        if (links.isEmpty) {
          return const MessageState(
            'Chưa có hồ sơ được liên kết. Liên hệ quản trị viên để cấp quyền người chăm sóc.',
          );
        }
        final profile =
            links.any((d) => d.id == selected) ? selected! : links.first.id;
        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
              child: DropdownButtonFormField<String>(
                initialValue: profile,
                decoration: const InputDecoration(
                  labelText: 'Hồ sơ đang theo dõi',
                ),
                items:
                    links
                        .map(
                          (d) =>
                              DropdownMenuItem(value: d.id, child: Text(d.id)),
                        )
                        .toList(),
                onChanged: (id) => setState(() => selected = id),
              ),
            ),
            if (s.data!.metadata.isFromCache)
              const Padding(
                padding: EdgeInsets.all(8),
                child: Text(
                  'Đang dùng dữ liệu lưu tạm. Kiểm tra kết nối Internet.',
                ),
              ),
            Expanded(
              child: KeyedSubtree(
                key: ValueKey('$profile-$tab'),
                child: ProfileAccessGate(
                  profileId: profile,
                  child: switch (tab) {
                    0 => Dashboard(profileId: profile),
                    1 => EventList(profileId: profile, alerts: false),
                    2 => EventList(profileId: profile, alerts: true),
                    _ => ProfilePage(profileId: profile),
                  },
                ),
              ),
            ),
          ],
        );
      },
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: tab,
      onDestinationSelected: (value) => setState(() => tab = value),
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.dashboard_outlined),
          selectedIcon: Icon(Icons.dashboard),
          label: 'Tổng quan',
        ),
        NavigationDestination(icon: Icon(Icons.history), label: 'Hoạt động'),
        NavigationDestination(
          icon: Icon(Icons.notifications_outlined),
          label: 'Cảnh báo',
        ),
        NavigationDestination(icon: Icon(Icons.person_outline), label: 'Hồ sơ'),
      ],
    ),
  );
}

class Dashboard extends StatefulWidget {
  final String profileId;
  const Dashboard({super.key, required this.profileId});
  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  late Timer timer;
  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
        stream:
            FirebaseFirestore.instance
                .doc('profiles/${widget.profileId}')
                .snapshots(),
        builder: (c, s) {
          if (s.hasError) return MessageState(friendlyError(s.error));
          return Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              s.data?.data()?['displayName'] ?? 'Đang tải hồ sơ…',
              style: Theme.of(c).textTheme.headlineSmall,
            ),
          );
        },
      ),
      StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
        stream: FirebaseFirestore.instance
            .doc('profiles/${widget.profileId}/status/current')
            .snapshots(includeMetadataChanges: true),
        builder: (c, s) {
          if (s.hasError) return MessageState(friendlyError(s.error));
          if (!s.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          if (!s.data!.exists) {
            return const MessageState(
              'Chưa có dữ liệu giám sát. Khởi chạy AI Engine ở Connected Mode.',
            );
          }
          return StatusCard(
            data: s.data!.data()!,
            now: DateTime.now(),
            cached: s.data!.metadata.isFromCache,
          );
        },
      ),
      const SizedBox(height: 16),
      Text('Cảnh báo gần đây', style: Theme.of(context).textTheme.titleLarge),
      AlertSummary(profileId: widget.profileId),
      const Padding(
        padding: EdgeInsets.all(12),
        child: Text(
          'Chỉ đồng bộ trạng thái và sự kiện. Hình ảnh camera được xử lý trên laptop.',
        ),
      ),
    ],
  );
}

String kindLabel(String? kind) =>
    const {
      'POSSIBLE_FALL': 'Nghi ngờ té ngã',
      'SUSPECTED_FALL': 'Đang xác minh chuyển động',
      'LYING_TOO_LONG': 'Nằm kéo dài',
      'ABNORMAL_INACTIVITY': 'Bất động kéo dài',
      'RECOVERED': 'Quan sát thấy phục hồi',
      'UNVERIFIED_CANDIDATE': 'Chưa đủ bằng chứng ngã',
      'STATUS_CHANGE': 'Cập nhật trạng thái',
      'POSTURE_CHANGE': 'Đổi tư thế',
      'SIMULATED_TRANSPORT_TEST': 'Kiểm thử đường truyền',
    }[kind] ??
    kind ??
    'Sự kiện';

class AlertSummary extends StatelessWidget {
  final String profileId;
  const AlertSummary({super.key, required this.profileId});
  @override
  Widget build(
    BuildContext context,
  ) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
    stream:
        FirebaseFirestore.instance
            .collection('profiles/$profileId/alerts')
            .orderBy('createdAt', descending: true)
            .limit(5)
            .snapshots(),
    builder: (c, s) {
      if (s.hasError) return MessageState(friendlyError(s.error));
      if (!s.hasData) return const LinearProgressIndicator();
      final docs = s.data!.docs;
      if (docs.isEmpty) {
        return const Card(
          child: Padding(
            padding: EdgeInsets.all(20),
            child: Text('Chưa có cảnh báo.'),
          ),
        );
      }
      final unresolved = docs.where((d) => d.data()['safeAt'] == null).length;
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(8),
            child: Text(
              '${docs.length} cảnh báo gần nhất • $unresolved chưa xác nhận an toàn',
            ),
          ),
          ...docs.map(
            (d) => EventTile(
              profileId: profileId,
              id: d.id,
              data: d.data(),
              alert: true,
            ),
          ),
        ],
      );
    },
  );
}

class EventList extends StatefulWidget {
  final String profileId;
  final bool alerts;
  const EventList({super.key, required this.profileId, required this.alerts});
  @override
  State<EventList> createState() => _EventListState();
}

class _EventListState extends State<EventList> {
  int limit = 30;
  @override
  Widget build(
    BuildContext context,
  ) => StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
    stream: FirebaseFirestore.instance
        .collection(
          'profiles/${widget.profileId}/${widget.alerts ? 'alerts' : 'events'}',
        )
        .orderBy('createdAt', descending: true)
        .limit(limit)
        .snapshots(includeMetadataChanges: true),
    builder: (c, s) {
      if (s.hasError) return MessageState(friendlyError(s.error));
      if (!s.hasData) return const Center(child: CircularProgressIndicator());
      final docs = s.data!.docs;
      if (docs.isEmpty) {
        return MessageState(
          widget.alerts ? 'Chưa có cảnh báo.' : 'Chưa có lịch sử hoạt động.',
        );
      }
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (s.data!.metadata.isFromCache)
            const Text('Lịch sử lưu tạm • chưa đồng bộ máy chủ'),
          ...docs.map(
            (d) => EventTile(
              profileId: widget.profileId,
              id: d.id,
              data: d.data(),
              alert: widget.alerts,
            ),
          ),
          if (docs.length == limit && limit < 300)
            TextButton(
              onPressed: () => setState(() => limit += 30),
              child: const Text('Tải thêm lịch sử'),
            ),
        ],
      );
    },
  );
}

class EventTile extends StatelessWidget {
  final String profileId, id;
  final Map<String, dynamic> data;
  final bool alert;
  const EventTile({
    super.key,
    required this.profileId,
    required this.id,
    required this.data,
    required this.alert,
  });
  @override
  Widget build(BuildContext context) => Card(
    child: ListTile(
      leading: Icon(
        alert ? Icons.warning_amber_rounded : Icons.timeline,
        color:
            alert && data['safeAt'] == null ? Colors.deepOrange : Colors.teal,
      ),
      title: Text(kindLabel(data['kind'])),
      subtitle: Text(
        '${timeLabel(data['createdAt'])}\n${alert ? (data['safeAt'] != null
                ? 'Đã xác nhận an toàn'
                : data['seenAt'] != null
                ? 'Đã xem • chưa xác nhận an toàn'
                : 'Chưa xem') : postureLabel(data['posture'])}',
      ),
      isThreeLine: true,
      trailing: alert ? const Icon(Icons.chevron_right) : null,
      onTap:
          alert
              ? () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder:
                      (_) => AlertDetail(profileId: profileId, alertId: id),
                ),
              )
              : null,
    ),
  );
}

class ProfileAccessGate extends StatefulWidget {
  final String profileId;
  final Widget child;
  const ProfileAccessGate({
    super.key,
    required this.profileId,
    required this.child,
  });
  @override
  State<ProfileAccessGate> createState() => _ProfileAccessGateState();
}

class _ProfileAccessGateState extends State<ProfileAccessGate> {
  late Future<DocumentSnapshot<Map<String, dynamic>>> membership;
  void load() {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    membership = FirebaseFirestore.instance
        .doc('profiles/${widget.profileId}/caregivers/$uid')
        .get(const GetOptions(source: Source.server))
        .timeout(const Duration(seconds: 12));
  }

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void didUpdateWidget(covariant ProfileAccessGate oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.profileId != widget.profileId) load();
  }

  @override
  Widget build(BuildContext context) =>
      FutureBuilder<DocumentSnapshot<Map<String, dynamic>>>(
        future: membership,
        builder: (context, s) {
          if (s.hasError) {
            return Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                MessageState(friendlyError(s.error)),
                TextButton(
                  onPressed: () => setState(load),
                  child: const Text('Kiểm tra lại quyền truy cập'),
                ),
              ],
            );
          }
          if (!s.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          if (!s.data!.exists ||
              !['caregiver', 'viewer'].contains(s.data!.data()?['role'])) {
            return const MessageState('Bạn chưa được cấp quyền xem hồ sơ này.');
          }
          return widget.child;
        },
      );
}

class AlertDetail extends StatefulWidget {
  final String profileId, alertId;
  const AlertDetail({
    super.key,
    required this.profileId,
    required this.alertId,
  });
  @override
  State<AlertDetail> createState() => _AlertDetailState();
}

class _AlertDetailState extends State<AlertDetail> {
  bool busy = false;
  Future<void> acknowledge(bool safe) async {
    if (safe) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder:
            (c) => AlertDialog(
              title: const Text('Xác nhận người thân an toàn?'),
              content: const Text(
                'Chỉ xác nhận sau khi bạn đã kiểm tra trực tiếp hoặc liên hệ được với người thân.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(c, false),
                  child: const Text('Quay lại'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(c, true),
                  child: const Text('Đã kiểm tra an toàn'),
                ),
              ],
            ),
      );
      if (confirmed != true) return;
    }
    if (!mounted) return;
    setState(() => busy = true);
    try {
      final uid = FirebaseAuth.instance.currentUser!.uid;
      await FirebaseFirestore.instance
          .doc('profiles/${widget.profileId}/alerts/${widget.alertId}')
          .update(
            safe
                ? {'safeBy': uid, 'safeAt': FieldValue.serverTimestamp()}
                : {'seenBy': uid, 'seenAt': FieldValue.serverTimestamp()},
          );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(friendlyError(e))));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Chi tiết cảnh báo')),
    body: ProfileAccessGate(
      profileId: widget.profileId,
      child: StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
        stream: FirebaseFirestore.instance
            .doc('profiles/${widget.profileId}/alerts/${widget.alertId}')
            .snapshots(includeMetadataChanges: true),
        builder: (c, s) {
          if (s.hasError) return MessageState(friendlyError(s.error));
          if (!s.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          if (!s.data!.exists) {
            return const MessageState('Cảnh báo không còn tồn tại.');
          }
          final data = s.data!.data()!;
          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const Icon(
                Icons.warning_amber_rounded,
                size: 64,
                color: Colors.deepOrange,
              ),
              const SizedBox(height: 16),
              Text(
                kindLabel(data['kind']),
                style: Theme.of(c).textTheme.headlineSmall,
              ),
              const SizedBox(height: 16),
              Text('Hồ sơ: ${widget.profileId}'),
              Text('Thời gian: ${timeLabel(data['createdAt'])}'),
              Text(
                'Mức độ: ${data['severity'] == 'high' ? 'Cao' : 'Cần chú ý'}',
              ),
              Text(
                'Xác minh tự động: ${data['verification'] ?? 'Chưa có kết quả'}',
              ),
              Text(
                'Nguồn: ${data['origin'] == 'algorithm' ? 'Thuật toán phân tích pose' : 'Sự kiện kiểm thử'}',
              ),
              const SizedBox(height: 24),
              Text('Đã xem: ${timeLabel(data['seenAt'])}'),
              Text('Xác nhận an toàn: ${timeLabel(data['safeAt'])}'),
              if (s.data!.metadata.isFromCache)
                const Text('Chưa xác minh kết nối máy chủ.'),
              if (s.data!.metadata.hasPendingWrites)
                const Text('Đang chờ máy chủ xác nhận thao tác…'),
              const SizedBox(height: 24),
              StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
                stream:
                    FirebaseFirestore.instance
                        .doc(
                          'profiles/${widget.profileId}/caregivers/${FirebaseAuth.instance.currentUser?.uid}',
                        )
                        .snapshots(),
                builder: (c, role) {
                  if (role.data?.data()?['role'] != 'caregiver') {
                    return const Text('Quyền hiện tại chỉ cho phép xem.');
                  }
                  final blocked =
                      busy ||
                      s.data!.metadata.isFromCache ||
                      s.data!.metadata.hasPendingWrites;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      OutlinedButton(
                        onPressed:
                            blocked || data['seenAt'] != null
                                ? null
                                : () => acknowledge(false),
                        child: const Text('Tôi đã xem cảnh báo'),
                      ),
                      const SizedBox(height: 12),
                      FilledButton(
                        onPressed:
                            blocked || data['safeAt'] != null
                                ? null
                                : () => acknowledge(true),
                        child: const Text('Đã kiểm tra • người thân an toàn'),
                      ),
                    ],
                  );
                },
              ),
            ],
          );
        },
      ),
    ),
  );
}

class ProfilePage extends StatelessWidget {
  final String profileId;
  const ProfilePage({super.key, required this.profileId});
  @override
  Widget build(
    BuildContext context,
  ) => StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
    stream: FirebaseFirestore.instance.doc('profiles/$profileId').snapshots(),
    builder: (c, s) {
      if (s.hasError) return MessageState(friendlyError(s.error));
      if (!s.hasData) return const Center(child: CircularProgressIndicator());
      if (!s.data!.exists) return const MessageState('Chưa có hồ sơ.');
      final d = s.data!.data()!;
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const CircleAvatar(radius: 40, child: Icon(Icons.person, size: 48)),
          const SizedBox(height: 24),
          Text(
            d['displayName'] ?? 'Chưa có tên',
            textAlign: TextAlign.center,
            style: Theme.of(c).textTheme.headlineSmall,
          ),
          const SizedBox(height: 24),
          ListTile(title: const Text('Mã hồ sơ'), subtitle: Text(profileId)),
          ListTile(
            title: const Text('Ghi chú'),
            subtitle: Text(d['notes'] ?? 'Chưa có thông tin bổ sung'),
          ),
          const Padding(
            padding: EdgeInsets.all(16),
            child: Text(
              'Liên hệ quản trị viên để cập nhật hồ sơ hoặc liên kết người chăm sóc.',
            ),
          ),
        ],
      );
    },
  );
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool busy = false;
  Future<void> run(Future<void> Function() action) async {
    setState(() => busy = true);
    try {
      await action();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(friendlyError(e))));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Cài đặt')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ListTile(
          leading: const Icon(Icons.account_circle_outlined),
          title: const Text('Tài khoản'),
          subtitle: Text(FirebaseAuth.instance.currentUser?.email ?? ''),
        ),
        SwitchListTile(
          title: const Text('Nhận cảnh báo trên thiết bị này'),
          subtitle: const Text('Cần bật quyền thông báo trong Android.'),
          value: Notifications.instance.enabled,
          onChanged:
              busy
                  ? null
                  : (value) =>
                      run(() => Notifications.instance.setEnabled(value)),
        ),
        ValueListenableBuilder<String?>(
          valueListenable: Notifications.instance.error,
          builder:
              (c, e, _) =>
                  e == null
                      ? const SizedBox.shrink()
                      : Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(
                          e,
                          style: const TextStyle(color: Colors.deepOrange),
                        ),
                      ),
        ),
        const ListTile(
          title: Text('Phiên bản V1'),
          subtitle: Text(
            'Phân tích hình học và chuyển động • không truyền video từ xa',
          ),
        ),
        const SizedBox(height: 24),
        OutlinedButton.icon(
          onPressed:
              busy
                  ? null
                  : () => run(() async {
                    await Notifications.instance.signOut();
                    if (context.mounted) {
                      Navigator.of(context).popUntil((route) => route.isFirst);
                    }
                  }),
          icon: const Icon(Icons.logout),
          label: Text(busy ? 'Đang xử lý…' : 'Đăng xuất'),
        ),
      ],
    ),
  );
}
