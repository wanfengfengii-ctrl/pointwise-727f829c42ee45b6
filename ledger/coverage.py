from dataclasses import dataclass

from capture.segments import Segment, segments_between
from capture.store import StationError
from ledger.postings import segment_owners


@dataclass(frozen=True)
class ReportCoverage:
    after: int
    through: int
    segments: tuple[Segment, ...]


def build_coverage(db, after, end):
    through = end.sequence
    if through <= after:
        raise StationError('invalid_interval', end.operation)
    segments = segments_between(db, after, through)
    if len(segments) != through - after:
        raise StationError('missing_segment', f'{after + 1} through {through}')
    for sequence, segment in enumerate(segments, after + 1):
        if segment.sequence != sequence or segment.recorder != end.recorder:
            raise StationError('invalid_segment', str(sequence))
    if segments[-1] != end:
        raise StationError('invalid_segment', end.operation)
    if segment_owners(db, after, through):
        raise StationError('already_posted', end.operation)
    return ReportCoverage(after, through, segments)
