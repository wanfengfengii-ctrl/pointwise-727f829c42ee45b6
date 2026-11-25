from dataclasses import dataclass

from capture.store import StationError


@dataclass(frozen=True)
class Segment:
    sequence: int
    recorder: str
    operation: str
    point: int
    liters: int


_SEGMENT_ROWS = '''
    SELECT s.sequence, e.recorder, s.operation, s.point, e.liters
      FROM segments AS s
      JOIN reading_evidence AS e ON (e.operation, e.point) = (s.operation, s.point)
'''


def install_segments(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS capture_state (
            operation TEXT PRIMARY KEY REFERENCES boundary_tickets(operation),
            state TEXT NOT NULL CHECK (state IN ('pending', 'confirmed'))
        );
        CREATE TABLE IF NOT EXISTS segments (
            sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
            operation TEXT NOT NULL UNIQUE REFERENCES capture_state(operation),
            point INTEGER NOT NULL UNIQUE,
            FOREIGN KEY (operation, point) REFERENCES reading_evidence(operation, point)
        );
    ''')


def mark_pending(db, operation):
    db.execute(
        'INSERT INTO capture_state VALUES (?, ?) ON CONFLICT(operation) DO NOTHING',
        (operation, 'pending'),
    )


def confirm_segment(db, sequence, evidence):
    expected = Segment(sequence, evidence.recorder, evidence.operation, evidence.point, evidence.liters)
    previous = read_segment(db, evidence.operation)
    if previous is not None:
        if previous != expected:
            raise StationError('segment_conflict', evidence.operation)
        return previous
    mark_pending(db, evidence.operation)
    db.execute('INSERT INTO segments VALUES (?, ?, ?)', (sequence, evidence.operation, evidence.point))
    db.execute('UPDATE capture_state SET state = ? WHERE operation = ?', ('confirmed', evidence.operation))
    return expected


def _segment(row):
    if row is None:
        return None
    return Segment(row['sequence'], row['recorder'], row['operation'], row['point'], int(row['liters'], 16))


def read_segment(db, operation):
    return _segment(db.execute(_SEGMENT_ROWS + ' WHERE s.operation = ?', (operation,)).fetchone())


def segment_at(db, sequence):
    return _segment(db.execute(_SEGMENT_ROWS + ' WHERE s.sequence = ?', (sequence,)).fetchone())


def segments_between(db, after, through):
    rows = db.execute(
        _SEGMENT_ROWS + ' WHERE s.sequence > ? AND s.sequence <= ? ORDER BY s.sequence',
        (after, through),
    )
    return tuple(_segment(row) for row in rows)
