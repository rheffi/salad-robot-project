"""Offline web state-machine tests. No ROS, camera or robot is imported."""
import asyncio
import threading
import unittest

import httpx

from web_ui.app import create_app
from web_ui.real_core import RealCore
from web_ui.schemas import RunRequest
from web_ui.hardware_backend import OperationStopped, ConfigurationChanged, RobotSteps
from web_ui.mock_core import InvalidStateError
from web_ui.command_queue import CommandBusyError


class FakeBackend:
    def __init__(self):
        self.threads = []
        self.calls = []
        self.fail_init = False
        self.changed = False
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.physical = []

    def record(self, name):
        self.threads.append(threading.get_ident())
        self.calls.append(name)

    def initialize(self):
        self.record('initialize')
        if self.fail_init: raise RuntimeError('test connection failure')
        return dict(tcp='', gripper_connected=True, camera_profile={'width':640,'height':480})

    def capture(self, rotate, stop):
        self.record('capture')
        return {'detections': {name: dict(confidence=.95,pixel_u=100.,pixel_v=100.,
            robot_x_mm=450.,robot_y_mm=0.) for name in ('tomato','cheese','berry','bowl')}}, b'jpeg', 'version1'

    def preflight(self, kind, payload, scene, fingerprint):
        self.record('preflight')
        if self.changed: raise ConfigurationChanged('configuration changed')
        return {}

    def execute(self, kind, payload, scene, poses, stop, report):
        self.record(kind)
        if self.block:
            self.entered.set()
            if not self.release.wait(3): raise RuntimeError('test barrier timeout')
        if stop.is_set(): raise OperationStopped('stop')
        if not payload.dry_run: self.physical.append(kind)
        report('commanded ' + kind)

    def close(self): self.record('close')


class RealTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = FakeBackend()
        self.core = RealCore(self.backend)

    async def asyncTearDown(self):
        self.backend.release.set()
        await self.core.shutdown()

    async def idle(self):
        await self.core.queue.wait_for_idle()

    async def prepare(self):
        await self.core.initialize()
        await self.idle()
        await self.core.detect_scene()
        await self.idle()

    def request(self, **options):
        return RunRequest(scene_id=self.core.scene_id, **options)

    async def test_05_to_09_dry_and_single_thread_lifetime(self):
        await self.prepare()
        for kind in ('home','bowl-hover','pick-hover','pick','pick-place','salad'):
            await self.core.execute_command(kind,self.request())
            await self.idle()
            self.assertNotEqual(self.core.state.value,'ERROR')
        self.assertEqual(self.core.state.value,'FINISHED')
        self.assertTrue(self.core.scene_valid)
        self.assertFalse(self.backend.physical)
        with self.assertRaises(InvalidStateError): await self.core.initialize()
        await self.core.shutdown()
        self.assertEqual(self.backend.calls.count('initialize'),1)
        self.assertEqual(self.backend.calls.count('close'),1)
        self.assertEqual(len(set(self.backend.threads)),1)
        self.assertNotEqual(self.backend.threads[0],threading.get_ident())

    async def test_confirmation_stale_scene_rotation_and_duplicate_rejected(self):
        await self.prepare()
        for payload in (self.request(dry_run=False), RunRequest(scene_id='old'), self.request(rotate=True)):
            with self.assertRaises(InvalidStateError): await self.core.execute_command('pick',payload)
        await self.core.execute_command('pick-hover',self.request())
        with self.assertRaises(CommandBusyError): await self.core.execute_command('home',self.request())
        await self.idle()
        self.assertFalse(self.backend.physical)

    async def test_holding_only_return_and_moved_scene_invalidated(self):
        await self.prepare()
        await self.core.execute_command('pick',self.request(dry_run=False,confirmation='PICK TOMATO'))
        await self.idle()
        self.assertEqual(self.core.state.value,'HOLDING')
        self.assertFalse(self.core.scene_valid)
        for kind in ('home','salad','pick'):
            with self.assertRaises(InvalidStateError): await self.core.execute_command(kind,self.request())
        with self.assertRaises(InvalidStateError): await self.core.detect_scene()
        await self.core.execute_command('return',self.request())
        await self.idle()
        self.assertEqual(self.core.state.value,'HOLDING')
        await self.core.execute_command('return',self.request(dry_run=False,confirmation='RETURN'))
        await self.idle()
        self.assertEqual(self.core.state.value,'READY')
        self.assertFalse(self.core.scene_valid)
        self.assertEqual(self.backend.physical,['pick','return'])

    async def test_stop_blocks_followup_and_requires_manual_recovery(self):
        await self.prepare()
        self.backend.block = True
        await self.core.execute_command('salad',self.request(dry_run=False,confirmation='RUN SALAD'))
        for _ in range(100):
            if self.backend.entered.is_set(): break
            await asyncio.sleep(.01)
        self.assertTrue(self.backend.entered.is_set())
        await self.core.request_stop()
        self.assertTrue(self.core.queue.busy)
        self.backend.release.set()
        await self.idle()
        self.assertTrue(self.core.recovery_required)
        self.assertFalse(self.core.scene_valid)
        self.assertFalse(self.backend.physical)
        with self.assertRaises(InvalidStateError): await self.core.execute_command('home',self.request())
        self.assertNotIn('home', self.backend.calls)

    async def test_config_change_prevents_execute(self):
        await self.prepare()
        self.backend.changed = True
        await self.core.execute_command('salad',self.request(dry_run=False,confirmation='RUN SALAD'))
        await self.idle()
        self.assertEqual(self.core.state.value,'ERROR')
        self.assertNotIn('salad',self.backend.calls)
        self.assertFalse(self.core.recovery_required)
        self.assertTrue(self.core.restart_required)
        self.assertFalse(self.core.scene_valid)

    async def test_failed_init_requires_restart(self):
        self.backend.fail_init = True
        await self.core.initialize()
        await self.idle()
        self.assertTrue(self.core.restart_required)
        with self.assertRaises(InvalidStateError): await self.core.initialize()

    async def test_api_real_routes_image_validation_and_cross_origin(self):
        app = create_app(core=self.core)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://testserver') as client:
            self.assertEqual((await client.post('/api/initialize')).status_code,202)
            await self.idle()
            self.assertEqual((await client.post('/api/detect',json={'rotate':False})).status_code,202)
            await self.idle()
            self.assertEqual((await client.get('/api/scene-image')).content,b'jpeg')
            items = (await client.get('/api/detections')).json()
            self.assertEqual(len(items),4)
            self.assertIsNone(items[0]['depth_m'])
            self.assertEqual(len(items[0]['base_mm']),2)
            for kind in ('bowl-hover','pick-hover','pick','pick-place'):
                response = await client.post('/api/test/'+kind,json=self.request().model_dump())
                self.assertEqual(response.status_code,202,response.text)
                await self.idle()
            self.assertEqual((await client.post('/api/run',json=self.request().model_dump())).status_code,202)
            await self.idle()
            self.assertEqual((await client.post('/api/home',json={})).status_code,202)
            await self.idle()
            self.assertEqual((await client.post('/api/home',json={'dry_run':False})).status_code,409)
            self.assertEqual((await client.post('/api/home',json={'vel':999})).status_code,422)
            self.assertEqual((await client.post('/api/home',headers={'Origin':'http://external.invalid'})).status_code,403)
            self.assertEqual((await client.get('/api/status')).json()['mode'],'REAL / DRY_RUN')


class RobotStepsTests(unittest.TestCase):
    def test_dry_run_never_calls_robot_or_gripper(self):
        class FailRobot:
            def __getattr__(self, name): raise AssertionError('physical call: '+name)
        stop = threading.Event()
        wrapper = RobotSteps(FailRobot(),{'safe_wait':{'posx':[0,0,500,0,0,0]}},stop,lambda _:None,True)
        wrapper.movej([0]*6,10,10,'home')
        wrapper.movel([450,0,350,0,0,0],10,10,'hover')
        wrapper.grip(430,200,'close')
        wrapper.wait(2)
        self.assertEqual(wrapper.state()[1][2],350)
        stop.set()
        with self.assertRaises(OperationStopped): wrapper.grip(750,200,'open')

    def test_stop_after_blocking_call_prevents_next_call(self):
        stop = threading.Event()
        class Robot:
            def movel(self,*args): stop.set()
            def grip(self,*args): raise AssertionError('next call must not run')
        wrapper = RobotSteps(Robot(),{'safe_wait':{'posx':[0]*6}},stop,lambda _:None,False)
        with self.assertRaises(OperationStopped): wrapper.movel([0]*6,10,10,'move')
        with self.assertRaises(OperationStopped): wrapper.grip(750,200,'open')


if __name__ == '__main__': unittest.main()
