from dataclasses import dataclass

from capture.store import StationError


@dataclass(frozen=True)
class ReadingEvidence:
    operation: str
    recorder: str
    point: int
    liters: int


def install_evidence(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS reading_evidence (
            operation TEXT NOT NULL REFERENCES boundary_tickets(operation),
            point INTEGER NOT NULL CHECK (point >= 0),
            recorder TEXT NOT NULL,
            liters TEXT NOT NULL,
            PRIMARY KEY (operation, point)
        )
    ''')


def save_evidence(db, evidence):
    previous = read_evidence(db, evidence.operation, evidence.point)
    if previous is not None:
        if previous != evidence:
            raise StationError('evidence_conflict', evidence.operation)
        return previous
    db.execute(
        'INSERT INTO reading_evidence (operation, recorder, point, liters) VALUES (?, ?, ?, ?)',
        (evidence.operation, evidence.recorder, evidence.point, format(evidence.liters, 'x')),
    )
    return evidence


def read_evidence(db, operation, point):
    row = db.execute(
        'SELECT recorder, liters FROM reading_evidence WHERE operation = ? AND point = ?',
        (operation, point),
    ).fetchone()
    if row is None:
        return None
    return ReadingEvidence(operation, row['recorder'], point, int(row['liters'], 16))
