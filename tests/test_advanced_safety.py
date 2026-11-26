import math
import unittest

import numpy as np

from src.convulsion import ConvulsionDetector
from src.inference import Body, Engine, FALL_WARNING, TRACKING
from src.pose import CONFIG, Observation
from src.posture import extended_posture


def make_obs(t, kind="standing", thrash_hz=0.0, thrash_amp=0.0):
    pts = np.zeros((17, 3), dtype=float)
    pts[:, 2] = 0.9
    if kind == "standing":
        coords = {
            0: (140, 72), 1: (136, 68), 2: (144, 68), 3: (132, 72), 4: (148, 72),
            5: (120, 110), 6: (160, 110),
            7: (112, 150), 8: (168, 150), 9: (110, 188), 10: (170, 188),
            11: (125, 200), 12: (155, 200),
            13: (125, 275), 14: (155, 275), 15: (125, 350), 16: (155, 350),
        }
    elif kind == "slumped":
        # Seated/wall-slide slump: torso leaned ~32 deg, head drooped onto chest/below shoulders
        coords = {
            0: (152, 218), 1: (148, 215), 2: (156, 215), 3: (144, 218), 4: (160, 218),
            5: (145, 210), 6: (165, 212),
            7: (140, 255), 8: (172, 255), 9: (142, 290), 10: (170, 290),
            11: (100, 285), 12: (120, 285),
            13: (145, 290), 14: (165, 290), 15: (145, 350), 16: (165, 350),
        }
    else:  # lying horizontal on floor
        coords = {
            0: (58, 305), 1: (55, 300), 2: (60, 300), 3: (54, 306), 4: (62, 306),
            5: (90, 295), 6: (90, 315),
            7: (125, 290), 8: (125, 320), 9: (155, 290), 10: (155, 320),
            11: (180, 298), 12: (180, 314),
            13: (230, 298), 14: (230, 314), 15: (270, 298), 16: (270, 314),
        }
    for idx, (x, y) in coords.items():
        pts[idx, 0], pts[idx, 1] = x, y
    if thrash_hz > 0 and thrash_amp > 0:
        s = math.sin(2 * math.pi * thrash_hz * t)
        for idx in (7, 8, 9, 10, 13, 14, 15, 16):
            pts[idx, 1] += thrash_amp * s * (1 if idx % 2 else -1)
    return Observation(t, 280, 400, pts)


class ZeroModel:
    def predict_proba(self, x):
        return np.tile([1.0, 0.0], (len(x), 1))


class AdvancedSafetyTests(unittest.TestCase):
    def test_convulsion_detector_movenet_rhythmic_vs_still_and_jitter(self):
        det = ConvulsionDetector(CONFIG)
        out = None
        for i in range(60):
            t = i * 0.05
            obs = make_obs(t, "lying", thrash_hz=4.0, thrash_amp=22.0)
            body = Body.from_pose(obs, CONFIG["confidence"])
            out = det.update(obs, body, grounded=True)
        self.assertTrue(out["convulsing"])
        self.assertGreaterEqual(out["oscillating_joints"], 2)

        det_still = ConvulsionDetector(CONFIG)
        for i in range(60):
            t = i * 0.05
            obs = make_obs(t, "lying")
            body = Body.from_pose(obs, CONFIG["confidence"])
            out_s = det_still.update(obs, body, grounded=True)
        self.assertFalse(out_s["convulsing"])

        det_jit = ConvulsionDetector(CONFIG)
        for i in range(60):
            t = i * 0.05
            obs = make_obs(t, "lying", thrash_hz=4.0, thrash_amp=2.0)
            body = Body.from_pose(obs, CONFIG["confidence"])
            out_j = det_jit.update(obs, body, grounded=True)
        self.assertFalse(out_j["convulsing"])

    def test_convulsion_triggers_locked_alarm_in_engine(self):
        eng = Engine(CONFIG, ZeroModel(), 0.98)
        alarms = []
        for i in range(80):
            t = i * 0.05
            res = eng.step(make_obs(t, "lying", thrash_hz=4.0, thrash_amp=22.0))
            if res["alarm"]:
                alarms.append(res["alarm_reason"])
        self.assertIn("convulsion", alarms)
        self.assertTrue(eng.alert_locked)
        self.assertEqual(eng.state, FALL_WARNING)

    def test_stroke_slump_and_slow_collapse_trigger_alert_without_fast_drop(self):
        eng = Engine(CONFIG, ZeroModel(), 0.98)
        t = 0.0
        for _ in range(10):
            eng.step(make_obs(t, "standing"))
            t += 0.1
        reasons = []
        for _ in range(50):
            res = eng.step(make_obs(t, "slumped"))
            if res["alarm"]:
                reasons.append(res["alarm_reason"])
            t += 0.1
        self.assertIn("stroke_slump", reasons)
        self.assertTrue(eng.alert_locked)

    def test_alert_lock_survives_occlusion_and_clears_on_confirm_or_upright_hold(self):
        eng = Engine(CONFIG, ZeroModel(), 0.98)
        t = 0.0
        for _ in range(10):
            eng.step(make_obs(t, "standing"))
            t += 0.1
        for _ in range(50):
            eng.step(make_obs(t, "lying"))
            t += 0.1
        self.assertTrue(eng.alert_locked)
        # Occlusion / helper covering camera must NOT clear alert
        for _ in range(30):
            blank = Observation(t, 280, 400, np.zeros((17, 3)))
            r = eng.step(blank)
            self.assertEqual(r["state"], FALL_WARNING)
            self.assertTrue(r["alert_locked"])
            t += 0.1
        # Single upright frame (e.g. helper standing) must NOT clear alert
        r = eng.step(make_obs(t, "standing"))
        self.assertTrue(r["alert_locked"])
        t += 0.1
        # Manual caregiver confirmation clears alert immediately
        self.assertTrue(eng.confirm_safe(t))
        self.assertFalse(eng.alert_locked)
        self.assertEqual(eng.state, TRACKING)

    def test_extended_posture_detects_lying_and_slumped(self):
        self.assertEqual(extended_posture(make_obs(0.0, "lying")), "Nằm")
        self.assertEqual(extended_posture(make_obs(0.0, "slumped")), "Gục người / trượt tường")


if __name__ == "__main__":
    unittest.main()
