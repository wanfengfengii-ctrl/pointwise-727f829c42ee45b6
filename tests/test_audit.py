from pathlib import Path

from ledger.application import open_station
from tests.fixtures import StationCase


class AuditTests(StationCase):
    def _same_value_report(self, station):
        for ticket, liters in (('A', 0), ('B', 7), ('C', 7)):
            self.add_cut(station, ticket, liters)
        station.withdraw('A')
        station.withdraw('B')
        return station.issue(*self.args('C'))

    def test_offline_same_value_segments(self):
        with open_station(self.root) as station:
            issued = self._same_value_report(station)
        Path(self.root, 'source.sqlite3').rename(Path(self.root, 'source.parked'))
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.receive('C'), issued)
            handover = station.handover('C')
            self.assert_code('withdrawn', station.receive, 'A')
            self.assert_code('withdrawn', station.reconcile, 'B')
        self.assertFalse(Path(self.root, 'source.sqlite3').exists())
        self.assertEqual(handover.issued.receipt, issued.receipt)
        self.assertEqual((handover.reconciliation.after, handover.reconciliation.through), (0, 3))
        self.assertEqual(handover.reconciliation.liters, 14)
        self.assertEqual(
            [(line.sequence, line.recorder, line.operation, line.point, line.liters) for line in handover.reconciliation.lines],
            [(1, self.recorder, 'cut/A', 1, 0), (2, self.recorder, 'cut/B', 3, 7), (3, self.recorder, 'cut/C', 5, 7)],
        )

    def test_old_report_after_new_issue(self):
        with open_station(self.root) as station:
            old = self._same_value_report(station)
            self.add_cut(station, 'D', 23)
            new = station.issue(*self.args('D'))
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.receive('C'), old)
            self.assertEqual(station.receive('D'), new)
            audit = station.reconcile('C')
            self.assertEqual([line.operation for line in audit.lines], ['cut/A', 'cut/B', 'cut/C'])
            self.assertEqual(audit.liters, 14)
            self.assertEqual(station.reconcile('D').after, 3)
            self.assertEqual(station.handover('D').reconciliation.liters, 23)

    def test_trace_mismatch(self):
        with open_station(self.root) as station:
            self._same_value_report(station)
            station.business.execute('UPDATE report_lines SET point = ? WHERE ticket = ? AND position = ?', (3, 'C', 3))
        with open_station(self.root, offline=True) as station:
            self.assertEqual(station.receive('C').report.liters, 14)
            self.assert_code('audit_trace', station.reconcile, 'C')
            self.assert_code('audit_trace', station.handover, 'C')

    def test_total_mismatch(self):
        with open_station(self.root) as station:
            self._same_value_report(station)
            station.business.execute('UPDATE official_reports SET liters = ? WHERE ticket = ?', ('f', 'C'))
        with open_station(self.root, offline=True) as station:
            self.assert_code('audit_total', station.reconcile, 'C')

    def test_coverage_and_receipt_mismatches(self):
        with open_station(self.root) as station:
            self._same_value_report(station)
            db = station.business
            db.execute('DELETE FROM segment_postings WHERE sequence = 2')
            self.assert_code('audit_coverage', station.handover, 'C')
            db.execute('INSERT INTO segment_postings VALUES (?, ?)', (2, 'C'))
            db.execute('UPDATE first_receipts SET through_sequence = 2 WHERE ticket = ?', ('C',))
            self.assert_code('audit_receipt', station.handover, 'C')
