from dataclasses import dataclass


@dataclass(frozen=True)
class CutOutcome:
    operation: str
    recorder: str
    point: int
    sequence: int


def find_outcome(db, operation):
    row = db.execute(
        'SELECT operation, recorder, point, sequence FROM cut_outcomes WHERE operation = ?',
        (operation,),
    ).fetchone()
    return CutOutcome(*row) if row is not None else None


def save_outcome(db, outcome):
    db.execute(
        'INSERT INTO cut_outcomes (operation, recorder, point, sequence) VALUES (?, ?, ?, ?)',
        (outcome.operation, outcome.recorder, outcome.point, outcome.sequence),
    )
