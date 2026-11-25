import io
import os
import unittest
from unittest.mock import Mock, patch

import numpy as np

from src.dataset import wanted
from src.inference import Engine, FALL_WARNING, NO_PERSON, SCHEMA
from src.keypoints import get_keypoints, observe_video
from src.pose import CONFIG, Observation, Pose, video_frames
from src.posture import posture_features
from src.review import annotation, inspect
from src.server import create_app
from src.storage import safe, sha
from src.telegram import TelegramError, api as telegram_api, pair
from src.train import assign_splits, assert_split, load_model, load_split, replay, score_events, window_label


def standing(t, shift=0, confidence=1):
    points = np.tile([125, 175 + shift, float(confidence)], (17, 1))
    points[[5, 6], :2] = [[112, 105 + shift], [138, 105 + shift]]
    points[[11, 12], :2] = [[115, 185 + shift], [135, 185 + shift]]
    return Observation(t, 280, 400, points)


class CausalityTests(unittest.TestCase):
    def test_future_pose_does_not_change_previous_features(self):
        earlier = [standing(i / 10) for i in range(26)]
        short = replay(earlier, CONFIG)
        long = replay(earlier + [standing(2.6, 60)], CONFIG)
        self.assertTrue(any(frame["features"] is not None for frame in short))
        for first, second in zip(short, long):
            if first["features"] is None:
                self.assertIsNone(second["features"])
            else:
                np.testing.assert_array_equal(first["features"], second["features"])

    def test_tracking_loss_clears_window_before_pose_jumps(self):
        class JumpClassifier:
            def predict_proba(self, features):
                score = float(abs(features[0, 0]) > 0.3)
                return np.array([[1 - score, score]])

        engine = Engine(CONFIG, JumpClassifier(), 0.5)
        for i in range(26):
            engine.step(standing(i / 10))
        engine.step(standing(2.6, confidence=0))
        for i in range(27, 45):
            frame = engine.step(standing(i / 10, 120))
            self.assertFalse(frame["alarm"])
            self.assertIsNone(frame["features"])
        self.assertEqual(len(engine.history), 18)

    def test_gone_subject_and_duplicate_timestamp(self):
        engine = Engine(CONFIG)
        engine.step(standing(0))
        for i in range(1, 9):
            frame = engine.step(standing(i / 10, confidence=0))
        self.assertEqual(frame["state"], NO_PERSON)
        self.assertEqual(len(engine.history), 0)
        with self.assertRaises(ValueError):
            engine.step(standing(0.8))

    def test_windows_use_confirmed_times(self):
        clip = dict(label="Fall", onset_s=3, impact_s=6, negative=[[0, 2.9]])
        self.assertIsNone(window_label(clip, 1, CONFIG))
        self.assertEqual(window_label(clip, 2.5, CONFIG), 0)
        self.assertIsNone(window_label(clip, 3.1, CONFIG))
        self.assertEqual(window_label(clip, 6.25, CONFIG), 1)
        self.assertIsNone(window_label(clip, 7, CONFIG))

    def test_event_match_counts_once_and_keeps_negative_delay(self):
        clip = dict(video_id="fall", label="Fall", onset_s=2, impact_s=2.5, negative=[],
                    duration_s=4, relative_path="fall.mp4", subject_id="p1")
        trace = [{"t": t, "alarm": True, "state": NO_PERSON} for t in (2.1, 2.8)]
        result = score_events([clip], {"fall": trace}, CONFIG)
        self.assertEqual((result["events"], result["detected"], result["other_unmatched"]), (1, 1, 1))
        self.assertAlmostEqual(result["latency_s"][0], -0.4)


class ValidationTests(unittest.TestCase):
    def test_posture_skips_horizontal_or_obscured_pose(self):
        obs = standing(0)
        obs.points[[13, 14, 15, 16], :2] = [[115, 240], [135, 240], [115, 300], [135, 300]]
        self.assertIsNotNone(posture_features(obs))
        obs.points[[13, 14], 2] = 0.01
        self.assertIsNone(posture_features(obs))
        obs.points[[13, 14], 2] = 1
        obs.points[:, :2] = obs.points[:, [1, 0]]
        self.assertIsNone(posture_features(obs))

    def test_catalog_folder_can_differ_from_confirmed_subject(self):
        relative = "data/raw/varishta/Jogging/Person10/Person51_video.mp4"
        self.assertTrue(wanted("Jogging/Person10/Person51_video.mp4", True, []))
        self.assertTrue(wanted("Jogging/Person10/Person51_Metadata.csv", False, ["Jogging/Person10"]))
        self.assertFalse(wanted("Jogging/Person10/Person51_Accelerometer.csv", True, []))
        item = {"relative_path": relative, "source": "Kaggle", "dataset_version": "5", "sha256": "check"}
        meta = {"person_id": "Person51", "activity": "Jogging", "batch_num": "5", "sensor_file": "source.zip"}
        with (patch("src.review.rows", return_value=[meta]) as metadata,
              patch("src.review.sha", return_value="check"),
              patch("src.review.video_info", return_value={}),):
            clip = inspect(item, {("Person51", "Jogging"): meta}, {"Person51": meta}, {})
            metadata.assert_called_once_with(safe(relative).with_name("Person51_Metadata.csv"))
        self.assertEqual((clip["video_id"], clip["source_folder_id"], clip["subject_id"]),
                         ("Jogging/Person10", "Person10", "Person51"))

    def test_path_validation_rejects_unsafe_targets(self):
        for name in ("../file", "/file", "C:/file", "\\\\host\\file", "data/../file", "data/file:stream", "data/NUL",
                     "data/dir. /file", "data//file"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe(name)
        with patch("src.storage.check_link", side_effect=ValueError("reparse point")):
            with self.assertRaisesRegex(ValueError, "reparse"):
                safe("data/fake.mp4")

    def test_annotation_rejects_invalid_seconds_and_overlap(self):
        for mark in (
            dict(label="Fall", onset_s=2, impact_s=1),
            dict(label="Fall", onset_s=1, impact_s=2, negative=[[1.5, 3]]),
            dict(label="No_Fall", negative=[[0, float("inf")]]),
            dict(label="No_Fall", negative=["bad"]),
        ):
            with self.subTest(mark=mark), self.assertRaises(ValueError):
                annotation({**mark, "note": "kiểm tra"}, 3)

    def test_splits_group_recording_and_hash(self):
        clips = [{"video_id": f"{person}/{label}", "subject_id": person, "recording_id": f"{person}/{label}",
                  "sha256": f"{person}/{label}", "label": label}
                 for person in "abcd" for label in ("Fall", "No_Fall")]
        clips[0]["recording_id"] = clips[2]["recording_id"]
        by_person = assign_splits(clips, CONFIG["seed"])
        self.assertEqual(by_person["a"], by_person["b"])
        for clip in clips:
            clip["split"] = by_person[clip["subject_id"]]
        assert_split(clips)
        clips[0]["split"] = next(part for part in by_person.values() if part != by_person["a"])
        with self.assertRaises(ValueError):
            assert_split(clips)

    def test_fresh_test_excludes_known_aliases(self):
        clips = [{"video_id": f"{person}/{label}", "subject_id": person,
                  "recording_id": f"{person}/{label}", "sha256": f"{person}/{label}", "label": label}
                 for person in "abcdef" for label in ("Fall", "No_Fall")]
        alias = {"subject_id": "previous", "recording_id": "previous/raw", "sha256": "a/Fall"}
        parts = assign_splits(clips, CONFIG["seed"], ["b", "c", "d", "e", "previous"], [alias])
        self.assertEqual({person for person, part in parts.items() if part == "test"}, {"f"})


class TelegramTests(unittest.TestCase):
    def test_pair_requires_matching_private_start(self):
        config = {"bot_token": "123:unused"}
        msg = {"text": "/start camera_test", "chat": {"type": "group", "id": -1}}
        with patch("src.telegram.api", return_value=[{"message": msg}]), patch("src.telegram.write_json") as save:
            with self.assertRaises(TelegramError):
                pair(config, "camera_test")
            save.assert_not_called()
        private = {"type": "private", "id": 123}
        with (patch("src.telegram.api", side_effect=[[{"message": {**msg, "chat": private}}], private]),
              patch("src.telegram.write_json") as save):
            pair(config, "camera_test")
            save.assert_called_once_with(safe(".secrets/telegram.json"), {**config, "chat_id": 123})

    def test_hides_transport_error_details(self):
        with patch("src.telegram.http.client.HTTPSConnection") as connection:
            connection.return_value.request.side_effect = OSError("url contained 123:unused")
            with self.assertRaises(TelegramError) as caught:
                telegram_api("123:unused", "sendMessage", {})
            self.assertNotIn("123:unused", str(caught.exception))


class RealVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not safe("data/manifests/split.csv").is_file():
            raise unittest.SkipTest("Thiếu split có nhãn đã xác nhận")
        cls.info, cls.model = load_model()
        if not cls.info:
            raise unittest.SkipTest("Thiếu classifier đã huấn luyện")
        clips = load_split()
        cls.video = next(v for v in clips if v["split"] == "test" and v["label"] == "Fall")
        cls.path = safe(cls.video["relative_path"])
        cls.cfg = cls.info["config"]
        cls.alerts = Mock()
        with (patch("src.server.AccountAlerts", return_value=cls.alerts),
              patch("src.server.load_supabase"), patch("src.server.load_telegram", return_value=None)):
            cls.app = create_app(start_sweeper=False)

    def setUp(self):
        self.alerts.reset_mock()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(login_id="test-login", user={"id": "test-user"})

    def test_video_range_and_local_only(self):
        response = self.client.get("/api/video", query_string={"id": self.video["video_id"]},
                                   headers={"Range": "bytes=0-127"})
        self.assertEqual((response.status_code, len(response.data)), (206, 128))
        response.close()
        self.assertEqual(self.client.get("/api/video", query_string={"id": "../.secrets/access_token"}).status_code, 404)
        self.assertEqual(self.client.get("/api/videos", environ_overrides={"REMOTE_ADDR": "192.168.1.2"}).status_code, 403)

    def test_replay_matches_fresh_offline_video_and_preserves_source(self):
        self.assertEqual(sha(self.path), self.video["sha256"])
        with self.path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
        fresh = list(observe_video(self.video, self.cfg, Pose()))
        cached = get_keypoints(self.video, self.cfg)
        self.assertEqual(len(fresh), len(cached))
        offline, from_cache = replay(fresh, self.cfg), replay(cached, self.cfg)
        for a, b in zip(offline, from_cache):
            self.assertEqual(a["t"], b["t"])
            self.assertEqual(a["state"], b["state"])
            if a["features"] is None:
                self.assertIsNone(b["features"])
            else:
                self.assertEqual(len(a["features"]), len(SCHEMA))
                np.testing.assert_allclose(a["features"], b["features"], atol=1e-7, rtol=0, equal_nan=True)
        response = self.client.get("/api/replay", query_string={"id": self.video["video_id"]})
        self.assertEqual(response.status_code, 200)
        expected = replay(fresh, self.cfg, self.model, self.info["threshold"], web=True)
        trace = response.json["trace"]
        self.assertEqual([{k: v for k, v in frame.items() if k != "activity"} for frame in trace], expected)
        self.assertTrue(all("activity" not in frame for frame in trace if frame["state"] == FALL_WARNING))
        self.alerts.enqueue.assert_not_called()
        self.assertEqual((self.path.stat().st_size, sha(self.path)), (size, self.video["sha256"]))

    def test_upload_preserves_fall_events_and_rejects_unsupported_input(self):
        route = "/api/analyze-video"
        response = self.client.post(route, data=self.path.read_bytes(), content_type="application/octet-stream")
        self.assertEqual(response.status_code, 200)
        detected = response.json
        archived = self.client.get("/api/replay", query_string={"id": self.video["video_id"]}).json
        self.assertTrue(detected["has_predictions"])
        self.assertTrue(detected["alarms"])
        self.assertFalse(detected["matches_train"])
        self.assertEqual(detected["trace"], archived["trace"])
        self.assertEqual(detected["alarms"], [f["t"] for f in archived["trace"] if f["alarm"]])
        self.alerts.enqueue.assert_not_called()
        self.assertEqual(self.client.post(route, data=b"not a video").status_code, 415)
        self.assertEqual(self.client.post(route, data=b"\x00\x00\x00\x18ftyp").status_code, 400)
        self.assertEqual(self.client.post(route, environ_overrides={"REMOTE_ADDR": "192.168.1.2"}).status_code, 403)
        with patch("src.server.MAX_UPLOAD", 5):
            self.assertEqual(self.client.post(route, data=b"x" * 6).status_code, 413)
        with patch("src.server.MAX_VIDEO_SECONDS", 1):
            self.assertEqual(self.client.post(route, data=self.path.read_bytes()).status_code, 400)

    def test_session_stop_ends_processing(self):
        token = self.client.post("/api/session").json["token"]
        second = self.client.post("/api/session").json["token"]
        sessions = self.app.extensions["sessions"]
        first_session, second_session = sessions.find(token), sessions.find(second)
        self.assertIsNot(first_session.engine, second_session.engine)
        _, image = next(video_frames(self.path, self.cfg["sample_hz"]))
        image.thumbnail((640, 640))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        jpeg = buffer.getvalue()
        route = f"/api/frame/{token}"
        sent = self.client.post(route, data=jpeg, content_type="image/jpeg", headers={"X-Frame-Time": "0"})
        self.assertEqual(sent.status_code, 200)
        self.alerts.enqueue.assert_not_called()
        other = self.app.test_client()
        with other.session_transaction() as session:
            session.update(login_id="different-login", user={"id": "different-user"})
        self.assertEqual(other.delete(f"/api/session/{token}").status_code, 204)
        self.assertEqual(other.post(route, data=jpeg, content_type="image/jpeg",
                                    headers={"X-Frame-Time": "0.1"}).status_code, 410)
        with patch("src.server.web_result", side_effect=[
            {"state": FALL_WARNING, "alarm": True}, {"state": FALL_WARNING, "alarm": False},
        ]):
            for timestamp in ("0.1", "0.2"):
                result = self.client.post(route, data=jpeg, content_type="image/jpeg",
                                          headers={"X-Frame-Time": timestamp})
                self.assertEqual(result.status_code, 200)
        self.alerts.enqueue.assert_called_once_with("test-user")
        self.assertEqual(self.client.delete(f"/api/session/{token}").status_code, 204)
        self.assertEqual(self.client.post(route, data=jpeg, content_type="image/jpeg",
                                         headers={"X-Frame-Time": "0.3"}).status_code, 410)
        self.assertEqual(first_session.last_timestamp, 0.2)
        self.assertIsNone(second_session.engine.last)
        self.assertEqual(self.client.post("/api/account/logout").status_code, 204)
        self.assertIsNone(sessions.find(second))
        self.assertEqual(self.client.post("/api/session").status_code, 401)
