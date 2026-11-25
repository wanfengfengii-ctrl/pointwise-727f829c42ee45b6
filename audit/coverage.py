from audit.consistency import AuditMismatch
from boundaries.tickets import read_ticket
from capture.segments import read_boundary_segment
from ledger.postings import read_postings, segment_owners
from ledger.receipts import report_before


def verify_coverage(db, report, lines):
    previous = report_before(db, report.through)
    expected_after = 0 if previous is None else previous.through
    if report.after != expected_after:
        raise AuditMismatch('coverage', f'{report.ticket}: start')
    if report.through <= report.after or len(lines) != report.through - report.after:
        raise AuditMismatch('coverage', f'{report.ticket}: length')
    ticket = read_ticket(db, report.ticket)
    if ticket.recorder != report.recorder:
        raise AuditMismatch('coverage', f'{report.ticket}: end')
    boundary = read_boundary_segment(db, ticket.operation)
    if boundary is None or (boundary.sequence, boundary.recorder, boundary.operation, boundary.point, boundary.liters) \
            != (lines[-1].sequence, lines[-1].recorder, lines[-1].operation, lines[-1].point, lines[-1].liters):
        raise AuditMismatch('coverage', f'{report.ticket}: end')
    for expected, line in enumerate(lines, report.after + 1):
        if line.sequence != expected or line.recorder != report.recorder:
            raise AuditMismatch('coverage', f'{report.ticket}: sequence {expected}')
    expected_sequences = tuple(line.sequence for line in lines)
    if read_postings(db, report.ticket) != expected_sequences:
        raise AuditMismatch('coverage', f'{report.ticket}: postings')
    owners = segment_owners(db, report.after, report.through)
    if owners != dict.fromkeys(expected_sequences, report.ticket):
        raise AuditMismatch('coverage', f'{report.ticket}: owners')
