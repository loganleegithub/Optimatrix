"""Offline guards for optional public observations; never read business secrets."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app import create_app
from signal_observer import (SignalStudyService, PublicStudyClient, ObservationError,
                             implementation_hash, rules_hash, HOUR)


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = Mock()
        self.strategies = Mock()

    def manifest(self):
        end = int(time.time()*1000)//(4*HOUR)*(4*HOUR)
        evaluation = end-365*24*HOUR
        return {'schema': 'public-signal-study-v1', 'enabled': True,
                'authority': 'public_observation_only', 'definition_sha256': rules_hash(),
                'implementation_sha256': implementation_hash(), 'seed_start_ms': evaluation-200*4*HOUR,
                'evaluation_start_ms': evaluation, 'catalog': [],
                'candidates': [{'key': key, 'strategy_id': key, 'version_id': key, 'rules_sha256': 'frozen'}
                               for key in ('supertrend', 'squeeze')]}

    def service(self):
        directory = self.root/'local/signal-studies'
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'manifest.json').write_text(json.dumps(self.manifest()))
        self.strategies.detail.side_effect = lambda key: {'versions': [{'version_id': key, 'status': 'frozen', 'rules_sha256': 'frozen'}]}
        return SignalStudyService(self.root, self.strategies, self.client)

    def test_stop_precedes_accountless_public_requests_and_leaves_old_success_old(self):
        service = self.service()
        self.client.reset_mock()
        (self.root/'STOP').touch()
        service.cycle()
        self.client.instrument.assert_not_called()
        self.client.candles.assert_not_called()
        self.assertEqual(service.snapshot()['status'], 'stopped')
        self.assertIsNone(service.snapshot()['last_success_at'])

    def test_wrong_binding_blocks_before_network(self):
        service = self.service()
        self.strategies.detail.return_value = {'versions': []}
        self.strategies.detail.side_effect = None
        service.cycle()
        self.assertEqual(service.snapshot()['status'], 'blocked')
        self.client.instrument.assert_not_called()

    def test_persistence_failure_latches_no_more_requests(self):
        service = self.service()
        with patch('signal_observer.save', side_effect=OSError('fixture')):
            service.cycle()
        self.assertEqual(service.snapshot()['status'], 'storage_error')
        self.client.reset_mock()
        service.cycle()
        self.client.instrument.assert_not_called()
        self.client.candles.assert_not_called()

    def test_malformed_optional_manifest_does_not_break_app(self):
        directory = self.root/'local/signal-studies'
        directory.mkdir(parents=True)
        value = self.manifest(); value['candidates'] = [None]
        (directory/'manifest.json').write_text(json.dumps(value))
        service = SignalStudyService(self.root, self.strategies, self.client)
        self.assertEqual(service.snapshot()['status'], 'blocked')
        service.start()
        self.assertIsNone(service.thread)

    def test_get_only_reads_cache_without_starting_or_fetching(self):
        service = self.service()
        service.cycle = Mock(side_effect=AssertionError('GET must not collect'))
        service.start = Mock(side_effect=AssertionError('GET must not launch'))
        app = create_app(Mock(), signal_studies=service)
        with app.test_client() as client:
            for _ in range(3):
                result = client.get('/api/signal-studies')
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json['authority'], 'public_observation_only')
        self.client.instrument.assert_not_called()

    def test_public_network_boundary_no_auth_or_environment(self):
        client = PublicStudyClient(self.root)
        self.addCleanup(client.close)
        self.assertFalse(client.session.trust_env)
        self.assertIsNone(client.session.auth)
        with patch.object(client.session, 'get') as get:
            with self.assertRaises(ObservationError):
                client._get('private/buy', {})
            get.assert_not_called()
            get.return_value = Mock(status_code=200, json=lambda: {'testnet': True, 'usOut': time.time()*1e6, 'result': {}})
            with self.assertRaises(ObservationError):
                client.instrument()
            self.assertEqual(get.call_args.args[0], 'https://www.deribit.com/api/v2/public/get_instrument')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertNotIn('Authorization', client.session.headers)
            (self.root/'STOP').touch(); get.reset_mock()
            with self.assertRaises(ObservationError):
                client.instrument()
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
