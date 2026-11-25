from audit.consistency import AuditMismatch
from boundaries.tickets import read_ticket
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
    if ticket.recorder != report.recorder or lines[-1].operation != ticket.operation:
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
