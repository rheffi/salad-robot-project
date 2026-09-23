"""Offline geometry and motion-order regression tests; never connect to ROS."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "tools" / "measurement"
sys.path.insert(0, str(SCRIPTS))
from box_orientation import METHOD, estimate_box, square_delta, square_mean, stable_orientation
from robot_common import approach_target, pick_reference_for_item


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def orientation(yaw=20):
    return {"method": METHOD, "yaw_base_deg": yaw, "quality": .95,
            "spread_deg": 1, "stable_frames": 10,
            "corners_px": [[100,100],[170,100],[170,170],[100,170]]}


POSES = {
    "safe_wait": {"posj": [0]*6, "posx": [400,0,500,100,-175,120]},
    "pick_reference": {"posx": [400,0,250,100,-175,120]},
    "place_reference": {"posx": [500,0,290,90,-175,100]},
    "home": {"posj": [0]*6},
}
SNAPSHOT = {"detections": {name: {"robot_x_mm": 400, "robot_y_mm": 0,
              "orientation": orientation()} for name in ("tomato","cheese","berry","bowl")}}


class FakeRobot:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.pose = list(POSES["safe_wait"]["posx"])
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def state(self): return [0]*6, list(self.pose)
    def autonomous(self): pass
    def print_route_start(self, *args): pass
    def movej(self, pose, *args):
        self.pose = list(POSES["safe_wait"]["posx"])
        self.calls.append(("movej", list(pose)))
    def movel(self, pose, *args):
        self.pose = list(pose)
        self.calls.append(("movel", list(pose)))
    def grip(self, *args): self.calls.append(("grip", args))
    def wait(self, *args): self.calls.append(("wait", args))


class GeometryTests(unittest.TestCase):
    def test_angles_and_perspective(self):
        # Robot XY -> image, including axis reflection and perspective.
        for mapping in (np.eye(3), np.array([[.2,1.1,-30],[1.05,.1,-20],[.0004,.0006,1]])):
            correction = {"matrix_3x3": np.linalg.inv(mapping).tolist(),
                          "pixel_convex_hull": [[0,0],[319,0],[319,319],[0,319]]}
            for angle in (0,15,30,45,60,89,-15):
                world = cv2.boxPoints(((160,160),(70,70),angle))
                points = cv2.perspectiveTransform(world[None], mapping)[0]
                frame = np.full((320,320,3),30,np.uint8)
                cv2.fillConvexPoly(frame,np.rint(points).astype(np.int32),(220,220,220))
                bbox = [*points.min(axis=0), *points.max(axis=0)]
                candidate, reason = estimate_box(frame,bbox,correction)
                self.assertIsNotNone(candidate, (angle, reason))
                self.assertLess(abs(square_delta(candidate["yaw_base_deg"],angle)), 2)

    def test_blank_and_wrong_size_rejected(self):
        correction = {"matrix_3x3": np.eye(3).tolist(),
                      "pixel_convex_hull": [[0,0],[319,0],[319,319],[0,319]]}
        frame = np.full((320,320,3),30,np.uint8)
        self.assertIsNone(estimate_box(frame,[100,100,200,200],correction)[0])
        cv2.rectangle(frame,(130,130),(160,160),(230,230,230),-1)
        self.assertIsNone(estimate_box(frame,[125,125,165,165],correction)[0])

    def test_low_contrast_box_with_inner_picture_is_detected(self):
        correction = {"matrix_3x3": np.eye(3).tolist(),
                      "pixel_convex_hull": [[0,0],[319,0],[319,319],[0,319]]}
        frame = np.full((320,320,3),105,np.uint8)
        points = np.rint(cv2.boxPoints(((160,160),(70,70),27))).astype(np.int32)
        cv2.fillConvexPoly(frame,points,(160,160,160))
        cv2.circle(frame,(160,160),18,(70,90,120),-1)  # pasted picture texture
        frame = cv2.GaussianBlur(frame,(5,5),0)
        candidate, reason = estimate_box(frame,[120,120,200,200],correction)
        self.assertIsNotNone(candidate,reason)
        self.assertLess(abs(square_delta(candidate["yaw_base_deg"],27)),4)

    def test_square_boundary_and_unstable_frames(self):
        self.assertAlmostEqual(abs(square_mean([44,-44])),45)
        samples = [orientation(0),orientation(20),orientation(0)]
        with self.assertRaises(ValueError): stable_orientation(samples)
        samples = [orientation(0),orientation(0),orientation(0)]
        samples[-1]["corners_px"] = [[130,130],[200,130],[200,200],[130,200]]
        with self.assertRaises(ValueError): stable_orientation(samples)


class MotionTests(unittest.TestCase):
    def test_reference_and_invalid_metadata(self):
        ref = POSES["pick_reference"]["posx"]
        rotated = pick_reference_for_item(ref,{"orientation":orientation(20)},rotate=True,reference_yaw=5)
        self.assertEqual(rotated, [400,0,250,115,-175,120])
        self.assertEqual(ref[3],100)
        self.assertEqual(pick_reference_for_item(ref,{}),ref)
        for item, baseline in (({},0), ({"orientation":orientation()},None),
                               ({"orientation":orientation(float('nan'))},0)):
            with self.assertRaises(ValueError):
                pick_reference_for_item(ref,item,rotate=True,reference_yaw=baseline)

    def test_rotation_at_safe_height_before_xy_then_descent(self):
        robot = FakeRobot()
        approach_target(robot,450,30,[400,0,250,115,-175,120],500,100,10,10,"test",separate_rotation=True)
        self.assertEqual(robot.calls[0][1][:3],[400,0,500])
        self.assertEqual(robot.calls[1][1][:3],[450,30,500])
        self.assertEqual(robot.calls[2][1][:3],[450,30,350])
        robot.pose[2] = 250
        robot.calls.clear()
        with self.assertRaises(ValueError):
            approach_target(robot,450,30,[400,0,250,115,-175,120],500,100,10,10,"test",separate_rotation=True)
        self.assertFalse(robot.calls)

    def test_hover_only_never_grips_or_descends_to_pick(self):
        module = load_script("07_single_pick_test")
        args = ["07", "--class-name", "tomato", "--rotate", "--reference-yaw-deg", "5", "--hover-only", "--live"]
        robot = FakeRobot()
        with patch.object(sys,"argv",args), patch.object(module,"load_json",return_value={}), \
             patch.object(module,"load_snapshot",return_value=SNAPSHOT), \
             patch.object(module,"load_poses",return_value=(POSES,"")), \
             patch.object(module,"Robot",return_value=robot), patch("builtins.input",return_value="HOVER TOMATO"):
            self.assertEqual(module.main(),0)
        self.assertFalse(any(call[0]=="grip" for call in robot.calls))
        self.assertTrue(all(call[1][2]>=350 for call in robot.calls if call[0]=="movel"))

    def test_sequence_uses_rotated_pick_and_original_place(self):
        module = load_script("09_salad_sequence")
        robot = FakeRobot()
        module.run_one(robot,"tomato",SNAPSHOT,POSES,100,10,10,430,200,rotate=True,reference_yaw=5)
        moves = [call[1] for call in robot.calls if call[0]=="movel"]
        self.assertTrue(any(p[2]==250 and p[3]==115 for p in moves))
        self.assertTrue(any(p[2]==290 and p[3]==90 for p in moves))


if __name__ == "__main__":
    unittest.main()
