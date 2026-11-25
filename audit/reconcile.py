from dataclasses import dataclass

from audit.consistency import verify_receipt, verify_total
from audit.coverage import verify_coverage
from audit.trace import TraceLine, trace_segments
from capture.store import business_read
from ledger.receipts import read_issued


@dataclass(frozen=True)
class Reconciliation:
    ticket: str
    after: int
    through: int
    liters: int
    lines: tuple[TraceLine, ...]


def reconcile_issued(db, issued):
    report = issued.report
    lines = trace_segments(db, report)
    verify_coverage(db, report, lines)
    liters = verify_total(report, lines)
    verify_receipt(report, issued.receipt)
    return Reconciliation(report.ticket, report.after, report.through, liters, lines)


def reconcile(db, ticket):
    with business_read(db):
        return reconcile_issued(db, read_issued(db, ticket))
