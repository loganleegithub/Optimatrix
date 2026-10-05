"""Offline public-template boundaries; these choices never start research or runs."""
import unittest

from onboarding import templates
from strategies import normalize_spec


class OnboardingTests(unittest.TestCase):
    def test_exactly_three_choices_only_trend_is_executable(self):
        rows = templates()
        self.assertEqual([r['id'] for r in rows], ['trend', 'breakout', 'rebound'])
        self.assertEqual([r['implemented'] for r in rows], [True, False, False])
        for row in rows:
            self.assertTrue(row['failures'])
            self.assertTrue(row['frequency'])
            self.assertEqual(normalize_spec(row['spec']), row['spec'])
        for row in rows[1:]:
            self.assertEqual(row['spec']['kind'], 'unimplemented')
            self.assertEqual(row['spec']['rules'], {})
            self.assertEqual(row['defaults'], [])

    def test_all_actual_rules_have_reasons_and_do_not_share_mutable_state(self):
        template = templates()[0]
        self.assertEqual({d['key']: d['value'] for d in template['defaults']}, template['spec']['rules'])
        self.assertTrue(all(d['reason'] for d in template['defaults']))
        template['spec']['rules']['fast_days'] = 99
        template['defaults'][0]['reason'] = 'mutated'
        fresh = templates()[0]
        self.assertEqual(fresh['spec']['rules']['fast_days'], 20)
        self.assertNotEqual(fresh['defaults'][0]['reason'], 'mutated')


if __name__ == '__main__':
    unittest.main()
