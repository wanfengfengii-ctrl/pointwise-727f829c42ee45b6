from dataclasses import dataclass

from boundaries.order import prior_boundaries
from boundaries.tickets import BoundaryTicket
from capture.segments import Segment, read_boundary_segment
from capture.store import StationError


@dataclass(frozen=True)
class IssueEligibility:
    ticket: BoundaryTicket
    segment: Segment


def check_eligibility(db, ticket):
    if ticket.state != 'pending':
        raise StationError(ticket.state, ticket.ticket)
    segment = read_boundary_segment(db, ticket.operation)
    if segment is None:
        raise StationError('cut_pending', ticket.ticket)
    if segment.recorder != ticket.recorder:
        raise StationError('invalid_segment', ticket.ticket)
    for predecessor in prior_boundaries(db, ticket.order):
        if predecessor.state == 'pending':
            raise StationError('predecessor_pending', predecessor.ticket)
    return IssueEligibility(ticket, segment)
