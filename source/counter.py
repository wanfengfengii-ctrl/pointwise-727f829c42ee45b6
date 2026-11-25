from dataclasses import dataclass

from source.full_scale import (
    FullScaleOutcome, full_scale_operation, save_full_scale_outcome,
)
from source.register import read_capacity, read_registration
from source.store import StationError, source_write


@dataclass(frozen=True)
class CounterReading:
    recorder: str
    point: int
    liters: int
    sequence: int


def snapshot_reading(db, recorder):
    read_registration(db, recorder)
    row = db.execute(
        'SELECT point, liters, cut_sequence FROM recorder WHERE recorder = ?', (recorder,)
    ).fetchone()
    return CounterReading(recorder, row['point'], int(row['liters'], 16), row['cut_sequence'])


def record(db, recorder, liters=None):
    if type(liters) is not int or liters < 0:
        raise StationError('invalid_liters', 'expected a nonnegative integer')
    with source_write(db):
        if read_capacity(db, recorder) > 0:
            raise StationError('full_scale_enabled', recorder)
        previous = snapshot_reading(db, recorder)
        current = CounterReading(recorder, previous.point + 1, previous.liters + liters, previous.sequence)
        db.execute(
            'UPDATE recorder SET liters = ?, point = ? WHERE recorder = ?',
            (format(current.liters, 'x'), current.point, recorder),
        )
        return current


def pulse(db, recorder):
    '''Accept exactly one litre; a capacity hit saves the original segment and clears atomically.'''
    with source_write(db):
        capacity = read_capacity(db, recorder)
        if capacity <= 0:
            raise StationError('full_scale_disabled', recorder)
        previous = snapshot_reading(db, recorder)
        point = previous.point + 1
        liters = previous.liters + 1
        if liters >= capacity:
            sequence = previous.sequence + 1
            outcome = FullScaleOutcome(
                full_scale_operation(sequence), recorder, point, sequence, liters,
            )
            save_full_scale_outcome(db, outcome)
            db.execute(
                'UPDATE recorder SET liters = ?, point = ?, cut_sequence = ? WHERE recorder = ?',
                ('0', point + 1, sequence, recorder),
            )
            return CounterReading(recorder, point + 1, 0, sequence)
        db.execute(
            'UPDATE recorder SET liters = ?, point = ? WHERE recorder = ?',
            (format(liters, 'x'), point, recorder),
        )
        return CounterReading(recorder, point, liters, previous.sequence)


def clear_reading(db, expected):
    current = snapshot_reading(db, expected.recorder)
    if current != expected:
        raise StationError('stale_reading', expected.recorder)
    sequence = current.sequence + 1
    db.execute(
        'UPDATE recorder SET liters = ?, point = ?, cut_sequence = ? WHERE recorder = ?',
        ('0', current.point + 1, sequence, current.recorder),
    )
    return sequence
