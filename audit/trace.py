from dataclasses import dataclass

from audit.consistency import AuditMismatch
from capture.segments import segment_at


@dataclass(frozen=True)
class TraceLine:
    sequence: int
    recorder: str
    operation: str
    point: int
    liters: int


def trace_segments(db, report):
    lines = []
    for frozen in report.segments:
        try:
            original = segment_at(db, frozen.sequence)
        except ValueError as error:
            raise AuditMismatch('trace', f'{report.ticket}/{frozen.sequence}') from error
        if original is None or original != frozen or original.liters < 0:
            raise AuditMismatch('trace', f'{report.ticket}/{frozen.sequence}')
        lines.append(TraceLine(original.sequence, original.recorder, original.operation, original.point, original.liters))
    return tuple(lines)
