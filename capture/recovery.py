import sqlite3
from dataclasses import dataclass

from boundaries.order import prior_boundaries
from boundaries.tickets import read_ticket, register_ticket, require_same_request
from capture.evidence import ReadingEvidence, read_evidence, save_evidence
from capture.segments import Segment, confirm_segment, mark_pending, read_segment, segment_at
from capture.store import StationError, business_read, business_write
from source.counter import snapshot_reading
from source.cut import execute_cut
from source.outcomes import find_outcome
from source.register import read_registration
from source.store import require_text, source_write


@dataclass(frozen=True)
class CaptureResult:
    status: str
    operation: str
    segment: Segment | None = None


def confirm_outcome(business, outcome):
    with business_write(business):
        evidence = read_evidence(business, outcome.operation, outcome.point)
        if evidence is None or evidence.recorder != outcome.recorder:
            return CaptureResult('pending', outcome.operation)
        if outcome.sequence <= 0:
            return CaptureResult('pending', outcome.operation)
        expected = Segment(outcome.sequence, outcome.recorder, outcome.operation, outcome.point, evidence.liters)
        prior = read_segment(business, outcome.operation)
        at_sequence = segment_at(business, outcome.sequence)
        if (prior is not None and prior != expected) or (at_sequence is not None and at_sequence != expected):
            return CaptureResult('pending', outcome.operation)
        segment = confirm_segment(business, outcome.sequence, evidence)
        return CaptureResult('confirmed', outcome.operation, segment)


def _prepare(business, source, ticket_name):
    with business_write(business):
        ticket = read_ticket(business, ticket_name)
        if ticket.state == 'withdrawn':
            return None
        for predecessor in prior_boundaries(business, ticket.order):
            if predecessor.state == 'pending' and find_outcome(source, predecessor.operation) is None:
                raise StationError('predecessor_uncut', predecessor.ticket)
        reading = snapshot_reading(source, ticket.recorder)
        save_evidence(business, ReadingEvidence(ticket.operation, reading.recorder, reading.point, reading.liters))
        mark_pending(business, ticket.operation)
        return reading


def collect_request(business, source, recorder, ticket_name, request, *, allow_registration, lose_reply=False):
    require_text(recorder, 'recorder')
    require_text(ticket_name, 'ticket')
    require_text(request, 'request')
    with business_read(business):
        ticket = read_ticket(business, ticket_name, required=False)
        if ticket is not None:
            require_same_request(ticket, recorder, request)
            segment = read_segment(business, ticket.operation)
            if segment is not None:
                return CaptureResult('confirmed', ticket.operation, segment)
        elif not allow_registration:
            raise StationError('unknown_ticket', ticket_name)
    if source is None:
        if ticket is None:
            raise StationError('source_unavailable', recorder)
        return CaptureResult('pending', ticket.operation)

    # All physical submissions take the source lock before a business write.
    # The evidence transaction commits while the source read point is pinned.
    try:
        with source_write(source):
            read_registration(source, recorder)
            if ticket is None:
                with business_write(business):
                    ticket = register_ticket(business, recorder, ticket_name, request)
            outcome = find_outcome(source, ticket.operation)
            executed = outcome is None
            if executed:
                try:
                    reading = _prepare(business, source, ticket_name)
                except sqlite3.Error as error:
                    raise StationError('evidence_write_failed', ticket_name) from error
                if reading is None:
                    return CaptureResult('withdrawn', ticket.operation)
                outcome = execute_cut(source, ticket.operation, reading)
    except sqlite3.Error as error:
        raise StationError('cut_write_failed', ticket_name) from error

    if executed and lose_reply:
        return CaptureResult('pending', ticket.operation)
    try:
        return confirm_outcome(business, outcome)
    except sqlite3.Error as error:
        raise StationError('confirmation_write_failed', ticket_name) from error


def resume(business, source, recorder, ticket, request):
    return collect_request(business, source, recorder, ticket, request, allow_registration=False)
