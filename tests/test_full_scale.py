from contextlib import closing

from capture.segments import read_boundary_segment, segment_at
from ledger.application import open_station
from source import counter
from source.full_scale import find_binding, find_full_scale_outcome
from source.store import open_source
from tests.fixtures import StationCase


class FullScaleTests(StationCase):
    def enable(self, capacity=10):
        with open_station(self.root) as station:
            return station.enable_full_scale(self.recorder, capacity)

    def feed(self, count):
        with closing(open_source(f'{self.root}/source.sqlite3')) as device:
            reading = None
            for _ in range(count):
                reading = counter.pulse(device, self.recorder)
            return reading

    def test_enable_validation(self):
        with open_station(self.root) as station:
            self.assert_code('unknown_recorder', station.enable_full_scale, 'other', 10)
            self.assert_code('full_scale_disabled', station.pulse, self.recorder)
            for invalid in (True, False, 0, -1, 2.5, '10', None):
                with self.subTest(invalid=invalid):
                    self.assert_code('invalid_capacity', station.enable_full_scale, self.recorder, invalid)
            config = station.enable_full_scale(self.recorder, 10)
            self.assertEqual((config.recorder, config.capacity), (self.recorder, 10))
            self.assertEqual(station.enable_full_scale(self.recorder, 10), config)
            self.assert_code('configuration_conflict', station.enable_full_scale, self.recorder, 12)

    def test_enable_after_ordinary_activity_rejected(self):
        with open_station(self.root) as station:
            station.record(self.recorder, 3)
            self.assert_code('configuration_conflict', station.enable_full_scale, self.recorder, 10)
        with open_station(self.root) as station:
            self.add_cut(station, 'A', 5)
            self.assert_code('configuration_conflict', station.enable_full_scale, self.recorder, 10)

    def test_pulse_and_record_interlock(self):
        self.assertEqual(self.enable().capacity, 10)
        with open_station(self.root) as station:
            self.assert_code('full_scale_enabled', station.record, self.recorder, 1)
            for expected in range(1, 10):
                reading = station.pulse(self.recorder)
                self.assertEqual((reading.liters, reading.sequence), (expected, 0))
            full = station.pulse(self.recorder)
            self.assertEqual((full.liters, full.sequence, full.point), (0, 1, 11))
            self.assertEqual(station.reading(self.recorder), full)
        with open_station(self.root) as station:
            self.assertEqual(station.reading(self.recorder), full)
            self.assertIsNotNone(find_full_scale_outcome(station.source, 'full/1'))

    def test_adoption_of_empty_meter(self):
        self.enable()
        self.feed(10)
        with open_station(self.root) as station:
            before = station.reading(self.recorder)
            result = station.cut(*self.args('A'))
            self.assertEqual(result.status, 'confirmed')
            self.assertEqual((result.segment.sequence, result.segment.operation, result.segment.liters),
                             (1, 'full/1', 10))
            self.assertEqual(station.reading(self.recorder), before, 'adoption must not advance the read point')
            self.assertIsNotNone(find_binding(station.source, 'cut/A'))
            issued = station.issue(*self.args('A'))
            self.assertEqual((issued.report.after, issued.report.through, issued.report.liters), (0, 1, 10))
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.handover('A').reconciliation.liters, 10)

    def test_no_new_boundary_does_not_consume_order(self):
        self.enable()
        self.feed(10)
        with open_station(self.root) as station:
            self.assertEqual(station.cut(*self.args('A')).status, 'confirmed')
            empty = station.cut(*self.args('B'))
            self.assertEqual((empty.status, empty.segment), ('no_new_boundary', None))
            self.assert_code('unknown_ticket', station.resume, *self.args('B'))
        self.feed(4)
        with open_station(self.root) as station:
            later = station.cut(*self.args('B'))
            self.assertEqual((later.segment.sequence, later.segment.liters), (2, 4))
            self.assertEqual(station.issue(*self.args('A')).report.through, 1)
            second = station.issue(*self.args('B'))
            self.assertEqual((second.report.after, second.report.through, second.report.liters), (1, 2, 4))

    def test_water_before_binding_clears_remainder(self):
        self.enable()
        self.feed(10)
        self.feed(4)
        with open_station(self.root) as station:
            captured = station.cut(*self.args('A'))
            self.assertEqual((captured.segment.sequence, captured.segment.liters), (2, 4))
            issued = station.issue(*self.args('A'))
            self.assertEqual([line.liters for line in issued.report.segments], [10, 4])
            self.assertEqual(issued.report.liters, 14)
        with open_station(self.root, offline=True) as station:
            audit = station.reconcile('A')
            self.assertEqual([(line.sequence, line.liters) for line in audit.lines], [(1, 10), (2, 4)])

    def test_lost_adoption_and_out_of_order_sign(self):
        self.enable()
        self.feed(10)
        with open_station(self.root) as station:
            lost = station.cut(*self.args('A'), lose_reply=True)
            self.assertEqual((lost.status, lost.segment), ('pending', None))
        self.feed(4)
        with open_station(self.root) as station:
            later = station.cut(*self.args('B'))
            self.assertEqual((later.segment.sequence, later.segment.liters), (2, 4))
            self.assert_code('predecessor_pending', station.issue, *self.args('B'))
            recovered = station.resume(*self.args('A'))
            self.assertEqual(recovered.operation, lost.operation)
            self.assertEqual((recovered.segment.sequence, recovered.segment.liters), (1, 10))
            first = station.issue(*self.args('A'))
            second = station.issue(*self.args('B'))
            self.assertEqual((first.report.liters, second.report.liters), (10, 4))

    def test_full_scale_ticket_cannot_withdraw(self):
        self.enable()
        self.feed(10)
        with open_station(self.root) as station:
            station.cut(*self.args('A'))
            self.assert_code('full_scale_no_withdraw', station.withdraw, 'A')
        with open_station(self.root, offline=True) as station:
            self.assert_code('full_scale_no_withdraw', station.withdraw, 'A')

    def test_same_physical_end_only_one_ticket(self):
        self.enable()
        self.feed(10)
        with open_station(self.root) as station:
            station.cut(*self.args('A'))
            self.assertEqual(station.cut(*self.args('B')).status, 'no_new_boundary')
            self.assertEqual(segment_at(station.business, 1).operation, 'full/1')
            self.assertEqual(read_boundary_segment(station.business, 'cut/A').sequence, 1)
            self.assertIsNone(read_boundary_segment(station.business, 'cut/B'))
