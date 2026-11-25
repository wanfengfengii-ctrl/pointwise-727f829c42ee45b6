from dataclasses import dataclass

from capture.store import StationError


@dataclass(frozen=True)
class Segment:
    sequence: int
    recorder: str
    operation: str
    point: int
    liters: int


_SEGMENT_ROWS = 'SELECT sequence, recorder, operation, point, liters FROM segments'
_BOUNDARY_ROWS = '''
    SELECT s.sequence, s.recorder, s.operation, s.point, s.liters
      FROM boundary_captures AS b
      JOIN segments AS s ON s.sequence = b.sequence
     WHERE b.boundary_operation = ? AND b.state = 'confirmed'
'''


def install_segments(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS segments (
            sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
            recorder TEXT NOT NULL,
            operation TEXT NOT NULL UNIQUE,
            point INTEGER NOT NULL UNIQUE,
            liters TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS boundary_captures (
            boundary_operation TEXT PRIMARY KEY,
            recorder TEXT NOT NULL,
            sequence INTEGER UNIQUE,
            state TEXT NOT NULL CHECK (state IN ('pending', 'confirmed'))
        );
    ''')


def _segment(row):
    if row is None:
        return None
    return Segment(row['sequence'], row['recorder'], row['operation'], row['point'], int(row['liters'], 16))


def read_segment(db, operation):
    '''Return the physical original segment recorded under a physical operation.'''
    return _segment(db.execute(_SEGMENT_ROWS + ' WHERE operation = ?', (operation,)).fetchone())


def segment_at(db, sequence):
    return _segment(db.execute(_SEGMENT_ROWS + ' WHERE sequence = ?', (sequence,)).fetchone())


def segments_between(db, after, through):
    rows = db.execute(
        _SEGMENT_ROWS + ' WHERE sequence > ? AND sequence <= ? ORDER BY sequence',
        (after, through),
    )
    return tuple(_segment(row) for row in rows)


def ensure_segment(db, segment):
    '''Idempotently materialise a physical original segment, rejecting any conflict.'''
    previous = read_segment(db, segment.operation)
    if previous is not None:
        if previous != segment:
            raise StationError('segment_conflict', segment.operation)
        return previous
    at_sequence = segment_at(db, segment.sequence)
    if at_sequence is not None and at_sequence != segment:
        raise StationError('segment_conflict', segment.operation)
    at_point = _segment(db.execute(_SEGMENT_ROWS + ' WHERE point = ?', (segment.point,)).fetchone())
    if at_point is not None and at_point != segment:
        raise StationError('segment_conflict', segment.operation)
    db.execute(
        'INSERT INTO segments (sequence, recorder, operation, point, liters) VALUES (?, ?, ?, ?, ?)',
        (segment.sequence, segment.recorder, segment.operation, segment.point, format(segment.liters, 'x')),
    )
    return segment


def mark_pending(db, boundary_operation, recorder):
    db.execute(
        "INSERT INTO boundary_captures (boundary_operation, recorder, sequence, state) "
        "VALUES (?, ?, NULL, 'pending') ON CONFLICT(boundary_operation) DO NOTHING",
        (boundary_operation, recorder),
    )


def confirm_boundary(db, boundary_operation, recorder, segment):
    '''Durably bind a ticket (boundary operation) to its actual physical segment.'''
    previous = read_boundary_segment(db, boundary_operation)
    if previous is not None:
        if previous != segment:
            raise StationError('segment_conflict', boundary_operation)
        return previous
    ensure_segment(db, segment)
    db.execute(
        "INSERT INTO boundary_captures (boundary_operation, recorder, sequence, state) "
        "VALUES (?, ?, ?, 'confirmed') "
        "ON CONFLICT(boundary_operation) DO UPDATE SET "
        "sequence = excluded.sequence, state = 'confirmed', recorder = excluded.recorder",
        (boundary_operation, recorder, segment.sequence),
    )
    return segment


def read_boundary_segment(db, boundary_operation):
    return _segment(db.execute(_BOUNDARY_ROWS, (boundary_operation,)).fetchone())
