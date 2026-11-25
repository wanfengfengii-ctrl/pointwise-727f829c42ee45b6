from boundaries.tickets import mark_withdrawn, read_ticket
from capture.store import StationError, business_write


def withdraw(db, ticket):
    with business_write(db):
        current = read_ticket(db, ticket)
        if current.state == 'signed':
            raise StationError('already_signed', ticket)
        if current.state == 'withdrawn':
            return current
        if current.full_scale:
            raise StationError('full_scale_no_withdraw', ticket)
        return mark_withdrawn(db, ticket)
