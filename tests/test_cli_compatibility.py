"""Offline regressions for CLI drift and the subscription/isolation boundary."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from researcher_cli import (CodexRunner, ModelError, REQUIRED_EXEC_FLAGS,
                            check_cli_compatibility, check_cli_identity)


CONFIG = {'cli_version_verified': '0.159.2', 'model': 'gpt-6-astra',
          'reasoning_effort': 'high', 'service_tier': 'default'}


class CliCompatibilityTests(unittest.TestCase):
    def test_new_version_is_not_accepted_by_merely_editing_config(self):
        config = {**CONFIG, 'cli_version_verified': '0.160.0'}
        with patch('researcher_cli._cli_read', return_value='codex-cli 0.160.0\n'):
            with self.assertRaisesRegex(ValueError, '未核实'):
                check_cli_identity('codex', config)

    def test_approved_task_cannot_silently_use_another_verified_cli(self):
        config = {**CONFIG, 'cli_version_verified': '0.158.0-alpha.2.1'}
        with tempfile.TemporaryDirectory() as folder, \
                patch('researcher_cli._cli_read', return_value='codex-cli 0.159.2\n'), \
                patch('researcher_cli.subprocess.Popen') as model_process:
            with self.assertRaises(ModelError) as raised:
                CodexRunner('codex').run(input_data={}, config=config, prompt='fixed',
                    schema={}, directory=folder, stop_event=threading.Event())
            self.assertEqual(raised.exception.status, 'cli_incompatible')
            model_process.assert_not_called()
            self.assertFalse((Path(folder) / 'invocation.json').exists())

    def test_api_auth_is_not_subscription_auth(self):
        with patch('researcher_cli._cli_read', side_effect=[
                'codex-cli 0.159.2\n', 'Logged in using an API key\n']):
            with self.assertRaisesRegex(ValueError, 'ChatGPT'):
                check_cli_identity('codex', CONFIG)

    def test_missing_cli_feature_or_isolation_failure_blocks_without_model(self):
        identity = {'cli_version': '0.159.2', 'login_status': 'Logged in using ChatGPT',
                    'compatibility_profile': 'test'}
        catalog = json.dumps({'models': [{'slug': 'gpt-6-astra',
                                         'supported_reasoning_levels': [{'effort': 'high'}]}]})
        with patch('researcher_cli.check_cli_identity', return_value=identity), \
                patch('researcher_cli._cli_read', return_value='--json'), \
                patch('researcher_cli.check_isolation') as isolation, \
                patch('researcher_cli.subprocess.Popen') as model_process:
            missing = check_cli_compatibility('codex', CONFIG)
            self.assertFalse(missing['ready'])
            self.assertIn('非交互参数', missing['reason'])
            isolation.assert_not_called()
            model_process.assert_not_called()
        with patch('researcher_cli.check_cli_identity', return_value=identity), \
                patch('researcher_cli._cli_read', side_effect=[
                    ' '.join(REQUIRED_EXEC_FLAGS), '--permission-profile --cd', catalog]), \
                patch('researcher_cli.check_isolation', return_value={'passed': False}), \
                patch('researcher_cli.subprocess.Popen') as model_process:
            denied = check_cli_compatibility('codex', CONFIG)
            self.assertFalse(denied['ready'])
            self.assertEqual(denied['runtime_snapshot']['model_calls'], 0)
            self.assertIn('沙盒检查未通过', denied['reason'])
            model_process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
