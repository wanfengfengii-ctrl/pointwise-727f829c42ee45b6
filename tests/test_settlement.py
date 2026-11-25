from boundaries.tickets import read_ticket
from capture.segments import segment_at
from ledger.application import open_station
from ledger.postings import read_postings, segment_owners
from ledger.receipts import latest_report
from tests.fixtures import StationCase, fail_receipt_write


class SettlementTests(StationCase):
    def test_pending_predecessor(self):
        with open_station(self.root) as station:
            first = self.add_cut(station, 'A', 7, lose_reply=True)
            second = self.add_cut(station, 'B', 11)
            self.assertEqual(first.status, 'pending')
            self.assertEqual((second.segment.sequence, second.segment.liters), (2, 11))
            self.assertEqual(station.reading(self.recorder).sequence, 2)
            error = self.assert_code('predecessor_pending', station.issue, *self.args('B'))
            self.assertEqual(error.detail, 'A')
            self.assert_code('not_issued', station.receive, 'B')
            self.assertEqual(segment_owners(station.business, 0, 2), {})

    def test_withdrawn_boundary_rolls_into_next(self):
        with open_station(self.root) as station:
            first = self.add_cut(station, 'A', 7).segment
            second = self.add_cut(station, 'B', 11).segment
            self.assertEqual(station.withdraw('A').state, 'withdrawn')
            self.assertEqual(station.withdraw('A').state, 'withdrawn')
            self.assertEqual(segment_at(station.business, 1), first)
            self.assert_code('withdrawn', station.receive, 'A')
            self.assert_code('withdrawn', station.issue, *self.args('A'))
            issued = station.issue(*self.args('B'))
            self.assertEqual((issued.report.after, issued.report.through, issued.report.liters), (0, 2, 18))
            self.assertEqual(issued.report.segments, (first, second))
            self.assertEqual(read_postings(station.business, 'B'), (1, 2))
            self.assertEqual(station.receive('B'), issued)

    def test_recovered_withdrawal(self):
        with open_station(self.root) as station:
            self.assertEqual(self.add_cut(station, 'A', 7, lose_reply=True).status, 'pending')
            second = self.add_cut(station, 'B', 11).segment
            self.assertEqual(second.sequence, 2)
            self.assert_code('predecessor_pending', station.issue, *self.args('B'))
            self.assert_code('not_issued', station.receive, 'B')
            first = station.resume(*self.args('A')).segment
            station.withdraw('A')
            station.close_source()
        with open_station(self.root, offline=True) as station:
            self.assert_code('withdrawn', station.receive, 'A')
            self.assertEqual(station.resume(*self.args('A')).segment, first)
            issued = station.issue(*self.args('B'))
            self.assertEqual(issued.report.liters, 18, 'c5.recovered_withdrawal: liters')
            self.assertEqual(issued.report.segments, (first, second))
            check = station.handover('B')
            self.assertEqual([line.operation for line in check.reconciliation.lines], ['cut/A', 'cut/B'])
            self.assertEqual([line.point for line in check.reconciliation.lines], [1, 3])
            self.assertEqual(check.issued, issued)

    def test_withdrawal_before_confirmation(self):
        with open_station(self.root) as station:
            lost = self.add_cut(station, 'A', 7, lose_reply=True)
            station.withdraw('A')
            self.add_cut(station, 'B', 11)
            self.assert_code('missing_segment', station.issue, *self.args('B'))
            self.assertEqual(station.resume(*self.args('A')).segment.operation, lost.operation)
            self.assertEqual(station.issue(*self.args('B')).report.liters, 18)

    def test_exact_integer_total(self):
        first_liters = (1 << 70) + 7
        with open_station(self.root) as station:
            self.add_cut(station, 'A', first_liters)
            station.withdraw('A')
            self.add_cut(station, 'B', 11)
        with open_station(self.root, offline=True) as station:
            result = station.issue(*self.args('B'))
            self.assertEqual(result.report.liters, 1180591620717411303442)
            self.assertEqual([s.liters for s in result.report.segments], [first_liters, 11])
            self.assertEqual(station.reconcile('B').liters, 1180591620717411303442)

    def _prepare_rollback(self, station):
        self.add_cut(station, 'A', 7, lose_reply=True)
        self.add_cut(station, 'B', 11)
        station.resume(*self.args('A'))
        station.withdraw('A')
        fail_receipt_write(station.business)
        failure = self.assert_code('issue_write_failed', station.issue, *self.args('B'))
        self.assertIn('controlled receipt write failure', str(failure.__cause__))
        self.assert_code('not_issued', station.receive, 'B')

    def test_issue_rollback_then_resume(self):
        with open_station(self.root) as station:
            self._prepare_rollback(station)
        with open_station(self.root) as station:
            self.assert_code('request_conflict', station.issue, self.recorder, 'B', 'different')
            issued = station.issue(*self.args('B'))
            self.assertEqual((issued.report.liters, issued.receipt.receipt_id), (18, 'receipt/B'))
            self.assertEqual([line.sequence for line in issued.report.segments], [1, 2])
            self.assertEqual(station.issue(*self.args('B')), issued)
            self.assertEqual(station.reading(self.recorder).sequence, 2)
            self.assertEqual(read_postings(station.business, 'B'), (1, 2))
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.receive('B'), issued)

    def test_rollback_visibility(self):
        with open_station(self.root) as station:
            self._prepare_rollback(station)
        with open_station(self.root, offline=True) as station:
            db = station.business
            self.assertIsNone(latest_report(db))
            self.assertEqual(segment_owners(db, 0, 2), {})
            self.assertEqual(read_ticket(db, 'B').state, 'pending')
            self.assertEqual(db.execute('SELECT count(*) FROM official_reports').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM report_lines').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM first_receipts').fetchone()[0], 0)
            self.assert_code('not_issued', station.handover, 'B')

    def test_signed_boundary_cannot_withdraw(self):
        with open_station(self.root) as station:
            self.add_cut(station, 'A', 7, lose_reply=True)
            self.add_cut(station, 'B', 11)
            station.resume(*self.args('A'))
            first = station.issue(*self.args('A'))
            self.assert_code('already_signed', station.withdraw, 'A')
            second = station.issue(*self.args('B'))
            self.assertEqual((first.report.liters, second.report.liters), (7, 11))
            self.assertEqual((first.report.after, first.report.through), (0, 1))
            self.assertEqual((second.report.after, second.report.through), (1, 2))
            self.assertEqual(segment_owners(station.business, 0, 2), {1: 'A', 2: 'B'})
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.receive('A'), first)
            self.assertEqual(station.receive('B'), second)
