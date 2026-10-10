import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import threading

from pinuke import controls, device
from pinuke._inuke_protocol import INukeClient, osc_decode
from pinuke.server import make_handler
from test_pinuke import FakeAmp


def snapshot():
    with patch.object(device, 'require_amp', return_value={'path': 'test', 'product': 'NU6000DSP', 'serial': 'test-serial'}), patch.object(device, 'INukeClient', return_value=FakeAmp()):
        return device.readback()


def peq(gain=-2.5):
    return {'channel': 1, 'block': 'peq', 'band': 1, 'value': {'type': 'HS12', 'freq': 20.0, 'gain': gain, 'q': 1.0}}


class EditingAmp(FakeAmp):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.sets = []
        for block, spec in controls.SPECS.items():
            suffix = {'high_pass': 'xover_hp', 'low_pass': 'xover_lp', 'gain_db': 'xover_gain', 'deq_filter': 'deq_filt', 'deq_compressor': 'deq_comp', 'deq_timing': 'deq_time'}.get(block, block)
            def setter(ch, *args, block=block, spec=spec):
                band = args[0] if 'bands' in spec else None
                fields = args[1:] if band else args
                change = {'channel': ch, 'block': block, 'value': dict(zip(spec['fields'], fields))}
                if band:
                    change['band'] = band
                self.sets.append(change)
                controls.put_value(self.state, change)
            def getter(ch, *args, block=block):
                change = {'channel': ch, 'block': block}
                if args:
                    change['band'] = args[0]
                value = copy.deepcopy(controls.group_value(self.state, change))
                return value['gain_db'] if block == 'gain_db' else value
            setattr(self, 'set_' + suffix, setter)
            setattr(self, 'get_' + suffix, getter)


class EditTests(unittest.TestCase):
    def setUp(self):
        self.before = snapshot()
        self.current = copy.deepcopy(self.before)
        self.amp = EditingAmp(self.current)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def apply(self, changes):
        with patch.object(device, 'require_amp', return_value=self.before['usb']), patch.object(device, 'INukeClient', return_value=self.amp), patch.object(device, '_read_connected', side_effect=lambda *_: copy.deepcopy(self.current)):
            return controls.apply_changes(self.before, changes, self.temp.name)

    def test_change_is_verified_and_other_channel_is_preserved(self):
        result = self.apply([peq()])
        self.assertTrue(result['complete'])
        self.assertEqual(len(self.amp.sets), 1)
        self.assertEqual(result['snapshot']['channels']['2'], self.before['channels']['2'])
        audit = json.loads(next(Path(self.temp.name).glob('*.json')).read_text())
        self.assertEqual(audit['before'], self.before)
        self.assertEqual(audit['outcome'], 'verified')
        self.assertEqual(audit['result']['snapshot'], result['snapshot'])

    def test_every_allowlisted_group_dispatches_correct_setter_and_reads_back(self):
        changes = []
        for block, spec in controls.SPECS.items():
            change = {'channel': 2, 'block': block}
            if 'bands' in spec:
                change['band'] = spec['bands']
            value = copy.deepcopy(controls.group_value(self.before, change))
            field = next(key for key, rule in spec['fields'].items() if 'choices' not in rule)
            value[field] += -.5 if value[field] >= spec["fields"][field]["max"] else .5
            change['value'] = value
            changes.append(change)
        result = self.apply(changes)
        self.assertTrue(result['complete'], result['error'])
        self.assertEqual(len(self.amp.sets), len(controls.SPECS))
        for change in changes:
            self.assertEqual(controls.group_value(result['snapshot'], change), change['value'])

    def test_stale_state_and_different_serial_send_no_setter(self):
        for drift in ('settings', 'serial'):
            with self.subTest(drift=drift):
                self.current = copy.deepcopy(self.before)
                if drift == 'settings':
                    self.current['channels']['2']['delay']['time_ms'] = 12
                else:
                    self.current['usb']['serial'] = 'different'
                result = self.apply([peq()])
                self.assertFalse(result['complete'])
                self.assertEqual(result['attempted'], [])
                self.assertEqual(self.amp.sets, [])

    def test_invalid_data_is_rejected_before_device_open(self):
        bad = [peq(float('nan')), peq(25), {**peq(), 'channel': True}, {**peq(), 'band': 9}, {**peq(), 'block': '/preset/load'}, {**peq(), 'extra': 3}]
        for change in bad:
            with self.subTest(change=change), patch.object(device, 'require_amp') as select:
                with self.assertRaises(controls.EditValidationError):
                    controls.apply_changes(self.before, [change], self.temp.name)
                select.assert_not_called()
        with self.assertRaises(controls.EditValidationError):
            controls.validate_changes([peq(), peq()])

    def test_prechange_audit_failure_prevents_writes(self):
        with patch.object(controls, '_save_audit', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.apply([peq()])
        self.assertEqual(self.amp.sets, [])

    def test_mismatch_stops_later_changes_without_retry_or_restore(self):
        self.amp.get_peq = lambda *_: {**peq()['value'], 'gain': -1.0}
        result = self.apply([peq(), {'channel': 2, 'block': 'delay', 'value': {'time_ms': 10.0, 'phase_deg': 0}}])
        self.assertFalse(result['complete'])
        self.assertEqual(len(self.amp.sets), 1)
        self.assertEqual(len(result['attempted']), 1)
        self.assertEqual(result['verified'], [])
        self.assertEqual(result['snapshot']['channels']['1']['peq'][0]['gain'], -2.5)
        self.assertEqual(result['snapshot']['channels']['2']['delay']['time_ms'], 0.0)
        self.assertEqual(json.loads(next(Path(self.temp.name).glob('*.json')).read_text())['outcome'], 'incomplete')

    def test_f32_roundoff_is_accepted_but_real_clamping_is_not(self):
        self.assertTrue(controls.equivalent({'freq': 120.0}, {'freq': 120.0000076}))
        self.assertFalse(controls.equivalent({'gain': -2.5}, {'gain': -2.0}))

    def test_setter_uses_expected_hid_osc_framing(self):
        class Transport:
            def __init__(self): self.writes = []
            def write(self, data): self.writes.append(data)
            def close(self): pass
        transport = Transport()
        client = INukeClient(transport=transport, min_send_interval_s=0)
        client.set_peq(2, 8, 'HS12', 20, -2.5, 1)
        packet = transport.writes[0]
        self.assertEqual(len(packet), 64)
        self.assertEqual(packet[0], 0)
        message = osc_decode(packet[2:2 + packet[1]])
        self.assertEqual(message['addr'], '/channel/2/peq/8')
        self.assertEqual(message['args'], ['HS12', 20., -2.5, 1.])


class EditServerTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot()
        self.writes = []
        self.success = True
        def writer(before, changes, audit_dir=None):
            self.writes.append(changes)
            after = copy.deepcopy(before)
            for change in changes: controls.put_value(after, change)
            return {'complete': self.success, 'snapshot': after, 'error': None if self.success else 'verification failed'}
        self.handler = make_handler(reader=lambda: copy.deepcopy(self.data), scanner=lambda: [], public_origin='https://amp.example', enable_edits=True, writer=writer)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
    def request(self, path, payload=None, origin='https://amp.example', post=True):
        headers = {'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        data = json.dumps(payload).encode() if payload is not None else None
        with urlopen(Request(self.url + path, data=data, headers=headers, method='POST' if post else 'GET'), timeout=3) as response:
            return json.load(response)
    def test_read_edit_apply_updates_revision_and_exportable_snapshot(self):
        before = self.request('/api/readback')
        after = self.request('/api/apply', {'revision': before['revision'], 'changes': [peq()]})
        self.assertTrue(after['complete'])
        self.assertNotEqual(before['revision'], after['revision'])
        state = self.request('/api/state', post=False)
        self.assertEqual(state['snapshot'], after['snapshot'])
    def test_stale_revision_invalid_payload_and_origin_are_rejected_without_writes(self):
        before = self.request('/api/readback')
        for rev, change, origin, code in [('stale', peq(), 'https://amp.example', 409), (before['revision'], peq(200), 'https://amp.example', 400), (before['revision'], peq(), 'https://foreign.test', 403), (before['revision'], peq(), None, 403)]:
            with self.subTest(code=code), self.assertRaises(HTTPError) as caught:
                self.request('/api/apply', {'revision': rev, 'changes': [change]}, origin=origin)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.writes, [])
    def test_partial_failure_requires_new_read_before_next_apply(self):
        before = self.request('/api/readback')
        self.success = False
        payload = {'revision': before['revision'], 'changes': [peq()]}
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/apply', payload)
        self.assertEqual(caught.exception.code, 502)
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/apply', payload)
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(len(self.writes), 1)
    def test_default_readonly_service_has_no_enabled_writer(self):
        handler = make_handler(reader=lambda: self.data, scanner=lambda: [])
        self.assertFalse(controls.SPECS.get('mode'))
        # A second, default service must reject apply even with a valid origin.
        with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                origin = f'http://127.0.0.1:{server.server_port}'
                request = Request(origin + '/api/apply', data=b'{}', headers={'Origin': origin, 'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(HTTPError) as caught: urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, 403)
            finally: server.shutdown(); thread.join(timeout=2)


if __name__ == '__main__': unittest.main()
