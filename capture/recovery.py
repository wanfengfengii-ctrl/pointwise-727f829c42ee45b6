import sqlite3
from dataclasses import dataclass

from boundaries.order import prior_boundaries
from boundaries.tickets import read_ticket, register_ticket, require_same_request
from capture.evidence import ReadingEvidence, read_evidence, save_evidence
from capture.segments import (
    Segment, confirm_boundary, mark_pending, read_boundary_segment, ensure_segment,
)
from capture.store import StationError, business_read, business_write
from source.counter import snapshot_reading
from source.cut import execute_cut
from source.full_scale import (
    FullScaleBinding, adoption_candidate, find_binding, find_full_scale_outcome,
    full_scale_outcomes, save_binding,
)
from source.outcomes import find_outcome
from source.register import read_capacity, read_registration
from source.store import require_text, source_write


@dataclass(frozen=True)
class CaptureResult:
    status: str
    operation: str
    segment: Segment | None = None


def _device_final(source, boundary_operation):
    if source is None:
        return None
    outcome = find_outcome(source, boundary_operation)
    if outcome is not None:
        return 'cut', outcome
    binding = find_binding(source, boundary_operation)
    if binding is not None:
        return 'adopt', binding
    return None


def _sync_full_scale(business, source, recorder):
    if source is None:
        return
    for outcome in full_scale_outcomes(source, recorder):
        ensure_segment(
            business,
            Segment(outcome.sequence, outcome.recorder, outcome.operation, outcome.point, outcome.liters),
        )


def confirm_outcome(business, source, boundary_operation, recorder):
    if source is None:
        segment = read_boundary_segment(business, boundary_operation)
        if segment is None:
            return CaptureResult('pending', boundary_operation)
        return CaptureResult('confirmed', boundary_operation, segment)
    final = _device_final(source, boundary_operation)
    if final is None:
        return CaptureResult('pending', boundary_operation)
    kind, value = final
    with business_write(business):
        if kind == 'cut':
            evidence = read_evidence(business, value.operation, value.point)
            if evidence is None or evidence.recorder != value.recorder:
                return CaptureResult('pending', boundary_operation)
            segment = Segment(value.sequence, value.recorder, value.operation, value.point, evidence.liters)
        else:
            original = find_full_scale_outcome(source, value.original_operation)
            if original is None:
                return CaptureResult('pending', boundary_operation)
            segment = Segment(
                value.sequence, value.recorder, original.operation, original.point, original.liters,
            )
        _sync_full_scale(business, source, recorder)
        confirm_boundary(business, boundary_operation, segment.recorder, segment)
        return CaptureResult('confirmed', boundary_operation, read_boundary_segment(business, boundary_operation))


def _predecessors_settled(business, source, ticket):
    for predecessor in prior_boundaries(business, ticket.order):
        if predecessor.state == 'pending' and _device_final(source, predecessor.operation) is None:
            raise StationError('predecessor_uncut', predecessor.ticket)


def _prepare_ordinary(business, source, ticket_name):
    with business_write(business):
        ticket = read_ticket(business, ticket_name)
        if ticket.state == 'withdrawn':
            return None
        _predecessors_settled(business, source, ticket)
        reading = snapshot_reading(source, ticket.recorder)
        save_evidence(
            business, ReadingEvidence(ticket.operation, reading.recorder, reading.point, reading.liters),
        )
        mark_pending(business, ticket.operation, reading.recorder)
        return reading


def _ordinary_apply(business, source, recorder, ticket, ticket_name, request):
    if ticket is None:
        with business_write(business):
            ticket = register_ticket(business, recorder, ticket_name, request, full_scale=False)
    outcome = find_outcome(source, ticket.operation)
    executed = outcome is None
    if executed:
        try:
            reading = _prepare_ordinary(business, source, ticket_name)
        except sqlite3.Error as error:
            raise StationError('evidence_write_failed', ticket_name) from error
        if reading is None:
            return ticket.operation, False, 'withdrawn'
        execute_cut(source, ticket.operation, reading)
    return ticket.operation, executed, None


def _full_scale_apply(business, source, recorder, ticket, ticket_name, request):
    if ticket is not None and ticket.state == 'withdrawn':
        return ticket.operation, False, 'withdrawn'
    if ticket is not None and _device_final(source, ticket.operation) is not None:
        return ticket.operation, False, None
    snapshot = snapshot_reading(source, recorder)
    if snapshot.liters > 0:
        kind = 'cut'
    else:
        candidate = adoption_candidate(source, recorder)
        if candidate is None:
            operation = '' if ticket is None else ticket.operation
            return operation, False, 'no_new_boundary'
        kind = 'adopt'
    if ticket is None:
        with business_write(business):
            ticket = register_ticket(business, recorder, ticket_name, request, full_scale=True)
    _predecessors_settled(business, source, ticket)
    if kind == 'cut':
        with business_write(business):
            save_evidence(
                business,
                ReadingEvidence(ticket.operation, snapshot.recorder, snapshot.point, snapshot.liters),
            )
            mark_pending(business, ticket.operation, snapshot.recorder)
        execute_cut(source, ticket.operation, snapshot)
    else:
        save_binding(
            source,
            FullScaleBinding(ticket.operation, recorder, candidate.operation, candidate.point, candidate.sequence),
        )
    return ticket.operation, True, None


def collect_request(business, source, recorder, ticket_name, request, *, allow_registration, lose_reply=False):
    require_text(recorder, 'recorder')
    require_text(ticket_name, 'ticket')
    require_text(request, 'request')
    with business_read(business):
        ticket = read_ticket(business, ticket_name, required=False)
        if ticket is not None:
            require_same_request(ticket, recorder, request)
            segment = read_boundary_segment(business, ticket.operation)
            if segment is not None:
                return CaptureResult('confirmed', ticket.operation, segment)
        elif not allow_registration:
            raise StationError('unknown_ticket', ticket_name)
    if source is None:
        if ticket is None:
            raise StationError('source_unavailable', recorder)
        return CaptureResult('pending', ticket.operation)

    try:
        with source_write(source):
            read_registration(source, recorder)
            if read_capacity(source, recorder) > 0:
                operation, executed, early = _full_scale_apply(
                    business, source, recorder, ticket, ticket_name, request,
                )
            else:
                operation, executed, early = _ordinary_apply(
                    business, source, recorder, ticket, ticket_name, request,
                )
    except sqlite3.Error as error:
        raise StationError('cut_write_failed', ticket_name) from error

    if early is not None:
        return CaptureResult(early, operation)
    if executed and lose_reply:
        return CaptureResult('pending', operation)
    try:
        return confirm_outcome(business, source, operation, recorder)
    except sqlite3.Error as error:
        raise StationError('confirmation_write_failed', ticket_name) from error


def resume(business, source, recorder, ticket, request):
    return collect_request(business, source, recorder, ticket, request, allow_registration=False)
