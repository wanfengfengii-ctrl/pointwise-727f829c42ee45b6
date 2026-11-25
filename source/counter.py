from dataclasses import dataclass

from source.register import read_registration
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
        previous = snapshot_reading(db, recorder)
        current = CounterReading(recorder, previous.point + 1, previous.liters + liters, previous.sequence)
        db.execute(
            'UPDATE recorder SET liters = ?, point = ? WHERE recorder = ?',
            (format(current.liters, 'x'), current.point, recorder),
        )
        return current


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
