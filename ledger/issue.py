import sqlite3

from boundaries.eligibility import check_eligibility
from boundaries.tickets import mark_signed, read_ticket, require_same_request
from capture.store import StationError, business_write
from ledger.coverage import build_coverage
from ledger.postings import post_segments
from ledger.receipts import OfficialReport, latest_report, read_issued, save_issued
from ledger.volume import total_liters


def issue(db, recorder, ticket_name, request):
    try:
        with business_write(db):
            ticket = require_same_request(read_ticket(db, ticket_name), recorder, request)
            if ticket.state == 'signed':
                return read_issued(db, ticket_name)
            eligible = check_eligibility(db, ticket)
            previous = latest_report(db)
            after = previous.through if previous is not None else 0
            coverage = build_coverage(db, after, eligible.segment)
            report = OfficialReport(
                ticket.ticket, recorder, coverage.after, coverage.through,
                total_liters(coverage.segments), coverage.segments,
            )
            post_segments(db, ticket.ticket, coverage.segments)
            mark_signed(db, ticket.ticket)
            return save_issued(db, report)
    except sqlite3.Error as error:
        raise StationError('issue_write_failed', ticket_name) from error
