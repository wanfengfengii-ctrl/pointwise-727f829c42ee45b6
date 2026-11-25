from boundaries.tickets import mark_withdrawn, read_ticket
from capture.store import StationError, business_write


def withdraw(db, ticket):
    with business_write(db):
        current = read_ticket(db, ticket)
        if current.state == 'signed':
            raise StationError('already_signed', ticket)
        if current.state == 'withdrawn':
            return current
        return mark_withdrawn(db, ticket)
