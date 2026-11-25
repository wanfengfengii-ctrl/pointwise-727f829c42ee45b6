from source.counter import clear_reading
from source.outcomes import CutOutcome, find_outcome, save_outcome
from source.store import StationError, require_text


def execute_cut(db, operation, durable_reading):
    '''Execute inside the caller's source write transaction after evidence commit.'''
    if not db.in_transaction:
        raise RuntimeError('execute_cut requires a source transaction')
    require_text(operation, 'operation')
    previous = find_outcome(db, operation)
    if previous is not None:
        if (previous.recorder, previous.point) != (durable_reading.recorder, durable_reading.point):
            raise StationError('operation_conflict', operation)
        return previous
    sequence = clear_reading(db, durable_reading)
    outcome = CutOutcome(operation, durable_reading.recorder, durable_reading.point, sequence)
    save_outcome(db, outcome)
    return outcome
