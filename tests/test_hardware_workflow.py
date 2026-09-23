"""Run with yolo-venv; tests real adapter logic with fake camera/robot only."""
import copy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools/measurement'))
from test_box_orientation import FakeRobot, POSES, SNAPSHOT
from web_ui.hardware_backend import HardwareBackend
import scene_common as scene
import salad_workflow as flow


def request(**overrides):
    return SimpleNamespace(**(dict(dry_run=False,rotate=True,reference_yaw_deg=5.,
        hover_height_mm=100.,vel=10.,acc=10.,class_name='tomato') | overrides))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.backend = HardwareBackend()
        self.backend.robot = FakeRobot()

    def execute(self,kind,**overrides):
        self.backend.execute(kind,request(**overrides),copy.deepcopy(SNAPSHOT),copy.deepcopy(POSES),
                             threading.Event(),lambda _:None)

    def test_09_real_adapter_sequence_has_three_picks_and_places(self):
        self.execute('salad')
        calls = self.backend.robot.calls
        closes = [arg[0] for kind,arg in calls if kind=='grip' and arg[0]==430]
        self.assertEqual(len(closes),3)
        place_actions = [arg for kind,arg in calls if kind=='movel' and arg[2] in (290,330,370) and arg[3]==90]
        self.assertEqual([arg[2] for arg in place_actions],[290,330,370])
        self.assertTrue(all(arg[3]==115 for kind,arg in calls if kind=='movel' and arg[2]==250))
        self.assertTrue(all(arg[3]==90 for kind,arg in calls if kind=='movel' and arg[2]==290))
        self.assertEqual(calls[-1][0],'movej')

    def test_stack_offsets_require_safe_hover_clearance(self):
        flow.validate_place_offsets(POSES,100)
        unsafe = copy.deepcopy(POSES)
        unsafe['safe_wait']['posx'][2] = 470
        with self.assertRaisesRegex(ValueError,'최고 놓기 Hover'):
            flow.validate_place_offsets(unsafe,100)

    def test_real_adapter_dry_sequence_no_robot_calls(self):
        with patch.object(self.backend.robot,'autonomous',side_effect=AssertionError('mode change')):
            self.execute('salad',dry_run=True)
        self.assertEqual(self.backend.robot.calls,[])

    def test_hover_then_pick_return(self):
        self.execute('pick-hover')
        self.assertFalse(any(k=='grip' for k,_ in self.backend.robot.calls))
        self.assertTrue(all(p[2]>=350 for k,p in self.backend.robot.calls if k=='movel'))
        self.execute('pick')
        self.assertIsNotNone(self.backend.holding)
        self.execute('return')
        self.assertIsNone(self.backend.holding)
        grips = [args[0] for k,args in self.backend.robot.calls if k=='grip']
        self.assertEqual(grips,[750,430,750])

    def test_preflight_checks_actual_xy_and_rotation(self):
        correction = dict(matrix_3x3=np.eye(3).tolist(),pixel_convex_hull=[[0,0],[639,0],[639,479],[0,479]],
                          robot_xy_bounds_mm=dict(x_min=200,x_max=600,y_min=-100,y_max=200))
        snapshot = copy.deepcopy(SNAPSHOT)
        for item in snapshot['detections'].values(): item.update(pixel_u=400.,pixel_v=0.)
        self.backend.initial_fingerprint = 'one'
        with patch.object(self.backend,'settings',return_value=(correction,POSES,'')), \
             patch.object(self.backend,'fingerprint',return_value='one'):
            self.backend.preflight('salad',request(dry_run=True),snapshot,'one')
            snapshot['detections']['tomato']['robot_x_mm'] += 10
            with self.assertRaisesRegex(ValueError,'XY'):
                self.backend.preflight('salad',request(dry_run=True),snapshot,'one')


class Tensor:
    def __init__(self,values): self.values = np.asarray(values)
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return self.values


class CaptureTests(unittest.TestCase):
    def test_headless_capture_has_no_gui_and_releases_camera(self):
        class Camera:
            released = False
            def isOpened(self): return True
            def set(self,*args): pass
            def get(self,prop): return 640 if prop==scene.cv2.CAP_PROP_FRAME_WIDTH else 480
            def read(self): return True,np.zeros((480,640,3),np.uint8)
            def release(self): self.released=True
        class Boxes:
            xyxy = Tensor([[390,190,410,210]]*4)
            cls = Tensor([0,1,2,3])
            conf = Tensor([.95]*4)
            def __len__(self): return 4
        result = SimpleNamespace(boxes=Boxes(),plot=lambda **_:np.zeros((480,640,3),np.uint8))
        model = SimpleNamespace(names=dict(enumerate(scene.SCENE_CLASSES)),predict=lambda *_,**__: [result])
        correction = dict(method='pixel_to_robot_xy_homography',fit_error_mm={'max':0},camera={'width':640,'height':480},
            matrix_3x3=np.eye(3).tolist(),pixel_convex_hull=[[0,0],[639,0],[639,479],[0,479]],
            robot_xy_bounds_mm=dict(x_min=200,x_max=600,y_min=-300,y_max=300))
        camera = Camera()
        with patch.object(scene.cv2,'VideoCapture',return_value=camera), \
             patch.object(scene.cv2,'namedWindow',side_effect=AssertionError('GUI called')), \
             patch.object(scene.cv2,'imshow',side_effect=AssertionError('GUI called')), \
             patch.object(scene.cv2,'waitKey',side_effect=AssertionError('GUI called')):
            # This file stands in for an existing model; the supplied fake model handles inference.
            snapshot,image = scene.capture_scene(Path(__file__),correction,'6',.5,3,
                display=False,loaded_model=model)
        self.assertTrue(camera.released)
        self.assertEqual(set(snapshot['detections']),set(scene.SCENE_CLASSES))
        self.assertEqual(image.shape,(480,640,3))
        self.assertEqual(snapshot['detections']['tomato']['robot_x_mm'],400.)


if __name__ == '__main__': unittest.main()
