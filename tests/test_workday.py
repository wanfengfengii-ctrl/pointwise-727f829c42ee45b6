import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.application import run_workday


class WorkdayTests(unittest.TestCase):
    def test_workday_settlement_routes(self):
        sample = json.loads((Path(__file__).resolve().parents[1] / 'examples' / 'workday.json').read_text(encoding='utf-8'))
        for route, total, after, operations in (
            ('withdraw', 18, 0, ['cut/A', 'cut/B']),
            ('sign', 11, 1, ['cut/B']),
        ):
            with self.subTest(route=route), TemporaryDirectory(prefix='chengbang-workday-') as root:
                observed = run_workday(root, sample, settlement=route)
                actual, downstream = observed['actual'], observed['downstream_actual']
                self.assertEqual(actual['initial_capture'], 'pending')
                self.assertEqual(actual['physical_sequences'], [1, 2])
                self.assertEqual(actual['early_issue'], 'predecessor_pending')
                self.assertEqual(actual['early_receive'], 'not_issued')
                self.assertEqual((actual['liters'], actual['after']), (total, after))
                self.assertEqual(downstream['liters'], total)
                self.assertEqual([line[2] for line in downstream['lines']], operations)
                self.assertTrue(downstream['same_issued'])
                oracle = sample['oracles'][route]
                self.assertEqual(actual, oracle['expected'])
                self.assertEqual(downstream, oracle['downstream_expected'])
