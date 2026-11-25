from dataclasses import dataclass

from boundaries.order import next_boundary_order
from capture.store import StationError
from source.store import require_text


@dataclass(frozen=True)
class BoundaryTicket:
    ticket: str
    recorder: str
    request: str
    operation: str
    order: int
    state: str


def install_tickets(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS boundary_tickets (
            ticket TEXT PRIMARY KEY,
            recorder TEXT NOT NULL,
            request TEXT NOT NULL,
            operation TEXT NOT NULL UNIQUE,
            boundary_order INTEGER NOT NULL UNIQUE CHECK (boundary_order > 0),
            state TEXT NOT NULL CHECK (state IN ('pending', 'signed', 'withdrawn'))
        )
    ''')


def read_ticket(db, ticket, *, required=True):
    require_text(ticket, 'ticket')
    row = db.execute(
        'SELECT ticket, recorder, request, operation, boundary_order, state FROM boundary_tickets WHERE ticket = ?',
        (ticket,),
    ).fetchone()
    if row is None:
        if required:
            raise StationError('unknown_ticket', ticket)
        return None
    return BoundaryTicket(*row)


def require_same_request(ticket, recorder, request):
    require_text(recorder, 'recorder')
    require_text(request, 'request')
    if (ticket.recorder, ticket.request) != (recorder, request):
        raise StationError('request_conflict', ticket.ticket)
    return ticket


def register_ticket(db, recorder, ticket, request):
    require_text(recorder, 'recorder')
    require_text(request, 'request')
    existing = read_ticket(db, ticket, required=False)
    if existing is not None:
        return require_same_request(existing, recorder, request)
    created = BoundaryTicket(ticket, recorder, request, f'cut/{ticket}', next_boundary_order(db), 'pending')
    db.execute(
        'INSERT INTO boundary_tickets VALUES (?, ?, ?, ?, ?, ?)',
        (created.ticket, created.recorder, created.request, created.operation, created.order, created.state),
    )
    return created


def _finish(db, ticket, state):
    result = db.execute(
        'UPDATE boundary_tickets SET state = ? WHERE ticket = ? AND state = ?',
        (state, ticket, 'pending'),
    )
    if result.rowcount != 1:
        raise StationError('invalid_ticket_transition', ticket)
    return read_ticket(db, ticket)


def mark_signed(db, ticket):
    return _finish(db, ticket, 'signed')


def mark_withdrawn(db, ticket):
    return _finish(db, ticket, 'withdrawn')
