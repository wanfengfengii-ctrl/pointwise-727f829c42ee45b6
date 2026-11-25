from dataclasses import dataclass


@dataclass(frozen=True)
class PriorBoundary:
    ticket: str
    operation: str
    state: str


def next_boundary_order(db):
    row = db.execute('SELECT COALESCE(MAX(boundary_order), 0) + 1 FROM boundary_tickets').fetchone()
    return row[0]


def prior_boundaries(db, order):
    rows = db.execute('''
        SELECT ticket, operation, state FROM boundary_tickets
         WHERE boundary_order < ? ORDER BY boundary_order
    ''', (order,))
    return tuple(PriorBoundary(*row) for row in rows)
