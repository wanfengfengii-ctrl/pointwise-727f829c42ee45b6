import tempfile
import unittest

from ledger.application import StationError, open_station


class StationCase(unittest.TestCase):
    recorder = 'CH-01'
    setting = 'reclaimed-water'

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='chengbang-test-')
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        with open_station(self.root) as station:
            station.configure(self.recorder, self.setting)

    def args(self, ticket):
        return self.recorder, ticket, f'shift-{ticket}'

    def add_cut(self, station, ticket, liters, *, lose_reply=False):
        station.record(self.recorder, liters)
        return station.cut(*self.args(ticket), lose_reply=lose_reply)

    def assert_code(self, code, action, *args):
        with self.assertRaises(StationError) as caught:
            action(*args)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception


def fail_evidence_write(db):
    db.executescript('''
        CREATE TEMP TRIGGER reject_evidence BEFORE INSERT ON reading_evidence
        BEGIN SELECT RAISE(ABORT, 'controlled evidence write failure'); END;
    ''')


def fail_receipt_write(db):
    db.executescript('''
        CREATE TEMP TRIGGER reject_receipt BEFORE INSERT ON first_receipts
        BEGIN SELECT RAISE(ABORT, 'controlled receipt write failure'); END;
    ''')
