from dataclasses import dataclass

from source.outcomes import find_outcome
from source.register import read_registration
from source.store import StationError, source_write

FULL_SCALE_PREFIX = 'full/'


@dataclass(frozen=True)
class FullScaleConfig:
    recorder: str
    capacity: int


@dataclass(frozen=True)
class FullScaleOutcome:
    operation: str
    recorder: str
    point: int
    sequence: int
    liters: int


@dataclass(frozen=True)
class FullScaleBinding:
    boundary_operation: str
    recorder: str
    original_operation: str
    point: int
    sequence: int


def full_scale_operation(sequence):
    return f'{FULL_SCALE_PREFIX}{sequence}'


def enable_full_scale(db, recorder, capacity):
    if type(capacity) is not int or capacity <= 0:
        raise StationError('invalid_capacity', 'expected a positive integer')
    with source_write(db):
        read_registration(db, recorder)
        row = db.execute(
            'SELECT capacity, point, cut_sequence, liters FROM recorder WHERE recorder = ?', (recorder,)
        ).fetchone()
        existing = row['capacity']
        if existing > 0:
            if existing != capacity:
                raise StationError('configuration_conflict', recorder)
            return FullScaleConfig(recorder, existing)
        if row['point'] != 0 or row['cut_sequence'] != 0 or int(row['liters'], 16) != 0:
            raise StationError('configuration_conflict', recorder)
        db.execute('UPDATE recorder SET capacity = ? WHERE recorder = ?', (capacity, recorder))
        return FullScaleConfig(recorder, capacity)


def find_full_scale_outcome(db, operation):
    row = db.execute(
        'SELECT operation, recorder, point, sequence, liters FROM full_scale_outcomes WHERE operation = ?',
        (operation,),
    ).fetchone()
    return FullScaleOutcome(*row[:4], int(row['liters'], 16)) if row is not None else None


def save_full_scale_outcome(db, outcome):
    db.execute(
        'INSERT INTO full_scale_outcomes (operation, recorder, point, sequence, liters) VALUES (?, ?, ?, ?, ?)',
        (outcome.operation, outcome.recorder, outcome.point, outcome.sequence, format(outcome.liters, 'x')),
    )


def full_scale_outcomes(db, recorder):
    rows = db.execute(
        'SELECT operation, recorder, point, sequence, liters FROM full_scale_outcomes '
        'WHERE recorder = ? ORDER BY sequence',
        (recorder,),
    )
    return tuple(FullScaleOutcome(*row[:4], int(row['liters'], 16)) for row in rows)


def full_scale_outcomes_upto(db, recorder, through):
    rows = db.execute(
        'SELECT operation, recorder, point, sequence, liters FROM full_scale_outcomes '
        'WHERE recorder = ? AND sequence <= ? ORDER BY sequence',
        (recorder, through),
    )
    return tuple(FullScaleOutcome(*row[:4], int(row['liters'], 16)) for row in rows)


def find_binding(db, boundary_operation):
    row = db.execute(
        'SELECT boundary_operation, recorder, original_operation, point, sequence '
        'FROM full_scale_bindings WHERE boundary_operation = ?',
        (boundary_operation,),
    ).fetchone()
    return FullScaleBinding(*row) if row is not None else None


def save_binding(db, binding):
    db.execute(
        'INSERT INTO full_scale_bindings '
        '(boundary_operation, recorder, original_operation, point, sequence) VALUES (?, ?, ?, ?, ?)',
        (binding.boundary_operation, binding.recorder, binding.original_operation,
         binding.point, binding.sequence),
    )
    return binding


def has_finality(db, boundary_operation):
    '''True when the device already holds a durable terminal result for this boundary.'''
    return find_outcome(db, boundary_operation) is not None or \
        find_binding(db, boundary_operation) is not None


def adoption_candidate(db, recorder):
    '''Return the latest physical clear when it is an unclaimed full-scale original segment.'''
    latest = db.execute(
        'SELECT COALESCE(MAX(sequence), 0) FROM cut_outcomes WHERE recorder = ?', (recorder,)
    ).fetchone()[0]
    fs_rows = full_scale_outcomes(db, recorder)
    if not fs_rows:
        return None
    outcome = fs_rows[-1]
    if outcome.sequence <= latest:
        return None
    claimed = db.execute(
        'SELECT 1 FROM full_scale_bindings WHERE original_operation = ?', (outcome.operation,)
    ).fetchone()
    if claimed is not None:
        return None
    return outcome
