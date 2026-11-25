from boundaries.tickets import read_ticket
from capture.evidence import read_evidence
from capture.segments import read_segment
from ledger.application import open_station
from source.outcomes import find_outcome
from tests.fixtures import StationCase, fail_evidence_write


class CaptureTests(StationCase):
    def test_input_and_cut(self):
        with open_station(self.root) as station:
            self.assertEqual(station.record(self.recorder, 3).liters, 3)
            self.assertEqual(station.record(self.recorder, 4).liters, 7)
            result = station.cut(*self.args('A'))
            self.assertEqual(result.status, 'confirmed')
            segment = result.segment
            self.assertEqual((segment.sequence, segment.recorder, segment.operation, segment.point, segment.liters),
                             (1, self.recorder, 'cut/A', 2, 7))
            self.assertEqual(read_evidence(station.business, 'cut/A', 2).liters, 7)
            self.assertEqual(find_outcome(station.source, 'cut/A').sequence, 1)
            self.assertEqual(station.reading(self.recorder).liters, 0)

    def test_invalid_liters(self):
        with open_station(self.root) as station:
            before = station.record(self.recorder, 7)
            for invalid in (None, -1, True, False, '7', 1.0, [7]):
                with self.subTest(invalid=invalid):
                    self.assert_code('invalid_liters', station.record, self.recorder, invalid)
                    self.assertEqual(station.reading(self.recorder), before)
            self.assert_code('invalid_liters', station.record, self.recorder)
            self.assert_code('unknown_recorder', station.record, 'other', 1)
            self.assertEqual(station.reading(self.recorder), before)
            self.assertEqual(station.record(self.recorder, 0).liters, 7)

    def test_evidence_write_failure(self):
        with open_station(self.root) as station:
            station.record(self.recorder, 3)
            before = station.record(self.recorder, 4)
            fail_evidence_write(station.business)
            self.assert_code('evidence_write_failed', station.cut, *self.args('A'))
            self.assertEqual(station.reading(self.recorder), before)
            self.assertIsNone(find_outcome(station.source, 'cut/A'))
            self.assertIsNone(read_evidence(station.business, 'cut/A', before.point))
            self.assertIsNone(read_segment(station.business, 'cut/A'))
        with open_station(self.root) as station:
            self.assert_code('request_conflict', station.resume, self.recorder, 'A', 'different')
            result = station.resume(*self.args('A'))
            self.assertEqual((result.segment.sequence, result.segment.liters), (1, 7))
            self.assertEqual(station.reading(self.recorder).sequence, 1)

    def test_reinitialize_preserves_data(self):
        with open_station(self.root) as station:
            before = station.record(self.recorder, 7)
            config = station.configure(self.recorder, self.setting)
            self.assertEqual(station.reading(self.recorder), before)
            self.assert_code('configuration_conflict', station.configure, self.recorder, 'other-setting')
            self.assert_code('configuration_conflict', station.configure, 'other-recorder', self.setting)
            self.assertEqual(station.configure(self.recorder, self.setting), config)
            self.assertEqual(station.reading(self.recorder), before)

    def test_reopen_existing_data(self):
        with open_station(self.root) as station:
            self.add_cut(station, 'A', 7)
            issued = station.issue(*self.args('A'))
            self.add_cut(station, 'B', 11)
            before = station.record(self.recorder, 5)
            pending = read_ticket(station.business, 'B')
        with open_station(self.root) as station:
            station.configure(self.recorder, self.setting)
            self.assertEqual(station.reading(self.recorder), before)
            self.assertEqual((before.liters, before.sequence), (5, 2))
            self.assertEqual(read_ticket(station.business, 'B'), pending)
            self.assert_code('not_issued', station.receive, 'B')
            self.assertEqual(station.receive('A'), issued)
            self.assertEqual(station.issue(*self.args('A')), issued)

    def test_cut_reply_lost(self):
        with open_station(self.root) as station:
            result = self.add_cut(station, 'A', 7, lose_reply=True)
            self.assertEqual((result.status, result.operation, result.segment), ('pending', 'cut/A', None))
            self.assertEqual(station.reading(self.recorder).sequence, 1)
            self.assertEqual(station.reading(self.recorder).liters, 0)
            self.assertIsNone(read_segment(station.business, 'cut/A'))
            station.record(self.recorder, 11)
        with open_station(self.root) as station:
            resumed = station.resume(*self.args('A'))
            self.assertEqual(resumed.status, 'confirmed')
            self.assertEqual((resumed.segment.sequence, resumed.segment.point, resumed.segment.liters), (1, 1, 7))
            self.assertEqual(station.cut(*self.args('A')), resumed)
            self.assert_code('request_conflict', station.cut, self.recorder, 'A', 'different')
            self.assert_code('request_conflict', station.resume, self.recorder, 'A', 'different')
            self.assertEqual(station.reading(self.recorder).sequence, 1)
            self.assertEqual(station.reading(self.recorder).liters, 11)

    def test_unavailable_outcome(self):
        with open_station(self.root) as station:
            result = self.add_cut(station, 'A', 7, lose_reply=True)
            self.assertEqual(result.status, 'pending')
        with open_station(self.root, offline=True) as station:
            self.assertIsNone(station.source)
            self.assertEqual(station.resume(*self.args('A')), result)
            self.assertIsNone(read_segment(station.business, 'cut/A'))
            self.assert_code('cut_pending', station.issue, *self.args('A'))
        with open_station(self.root) as station:
            confirmed = station.resume(*self.args('A'))
            self.assertEqual((confirmed.segment.operation, confirmed.segment.sequence), ('cut/A', 1))
            self.assertEqual(station.resume(*self.args('A')), confirmed)
            self.assertEqual(station.reading(self.recorder).sequence, 1)

    def test_unexecuted_predecessor_preserves_physical_order(self):
        with open_station(self.root) as station:
            station.record(self.recorder, 7)
            fail_evidence_write(station.business)
            self.assert_code('evidence_write_failed', station.cut, *self.args('A'))
            station.business.execute('DROP TRIGGER reject_evidence')
            self.assert_code('predecessor_uncut', station.cut, *self.args('B'))
            self.assertEqual(station.reading(self.recorder).sequence, 0)
            first = station.resume(*self.args('A'))
            station.record(self.recorder, 11)
            second = station.resume(*self.args('B'))
            self.assertEqual((first.segment.sequence, first.segment.liters), (1, 7))
            self.assertEqual((second.segment.sequence, second.segment.liters), (2, 11))
