import argparse
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import check_project
from capture.store import open_business
from ledger.application import StationError, open_station
from ledger.postings import read_postings
from source import counter
from source.store import open_source
from tests.fixtures import fail_receipt_write


def refusal(action, codes):
    try:
        action()
    except StationError as error:
        assert error.code in codes, str(error)
        return
    raise AssertionError(f"expected one of {codes}")


def feed(root, recorder, count):
    with closing(open_source(root / "source.sqlite3")) as device:
        for _ in range(count):
            counter.pulse(device, recorder)


def prepare(root, sample):
    recorder, capacity = sample["recorder"], sample["capacity"]
    with open_station(root) as station:
        station.configure(recorder, sample["setting"])
        station.enable_full_scale(recorder, capacity)
    with closing(open_business(root / "business.sqlite3", must_exist=True)) as blocked:
        blocked.execute("BEGIN IMMEDIATE")
        try:
            feed(root, recorder, capacity)
        finally:
            blocked.rollback()
    with closing(open_source(root / "source.sqlite3")) as reopened:
        reading = counter.snapshot_reading(reopened, recorder)
        assert (reading.liters, reading.sequence, reading.point) == (0, 1, capacity + 1)


def raw_lines(lines):
    return [(line.sequence, line.point, line.liters) for line in lines]


def check_offline(station, args, issued, after, lines):
    recorder, ticket, request = args
    report = issued.report
    assert (report.recorder, report.ticket, report.after, report.through) == (recorder, ticket, after, lines[-1][0])
    assert raw_lines(report.segments) == lines
    assert report.liters == sum(line[-1] for line in lines)
    assert (issued.receipt.receipt_id, issued.receipt.ticket, issued.receipt.through) == (f"receipt/{ticket}", ticket, report.through)
    result = station.handover(ticket)
    assert station.receive(ticket) == result.issued == station.issue(recorder, ticket, request) == issued
    assert result.reconciliation.liters == report.liters
    assert [asdict(line) for line in result.reconciliation.lines] == [asdict(line) for line in report.segments]


def before_binding(root, sample):
    prepare(root, sample)
    recorder, capacity, extra = sample["recorder"], sample["capacity"], sample["extra"]
    args = (recorder, "A", "morning")
    with open_station(root) as station:
        assert station.reading(recorder).liters == 0
        feed(root, recorder, extra)
        captured = station.cut(*args)
        assert captured.status == "confirmed"
        assert (captured.segment.sequence, captured.segment.liters) == (2, extra)
        assert station.reading(recorder).sequence == 2
    with open_station(root, offline=True) as station:
        fail_receipt_write(station.business)
        refusal(lambda: station.issue(*args), {"issue_write_failed"})
        refusal(lambda: station.receive("A"), {"not_issued"})
        assert read_postings(station.business, "A") == ()
    with open_station(root, offline=True) as station:
        issued = station.issue(*args)
        assert issued.report.segments[-1] == captured.segment
        assert not issued.report.segments[0].operation.startswith("cut/")
    with open_station(root, offline=True) as station:
        check_offline(station, args, issued, 0, [(1, capacity, capacity), (2, capacity + 1 + extra, extra)])
    return {"case": "water-before-binding", "issued": asdict(issued)}


def after_binding(root, sample):
    prepare(root, sample)
    recorder, capacity, extra = sample["recorder"], sample["capacity"], sample["extra"]
    a, b = (recorder, "A", "morning"), (recorder, "B", "evening")
    with open_station(root) as station:
        before = station.reading(recorder)
        lost = station.cut(*a, lose_reply=True)
        assert lost.status == "pending" and lost.segment is None
        assert station.reading(recorder) == before
        refusal(lambda: station.issue(*a), {"unknown_ticket", "cut_pending", "missing_segment"})
        empty = station.cut(recorder, "B", "unused")
        assert empty.status == "no_new_boundary" and empty.segment is None
        assert station.reading(recorder) == before
        refusal(lambda: station.resume(recorder, "B", "unused"), {"unknown_ticket"})
    feed(root, recorder, extra)
    with open_station(root) as station:
        refusal(lambda: station.resume(recorder, "A", "wrong"), {"request_conflict"})
        later = station.cut(*b)
        assert later.status == "confirmed" and later.segment.sequence == 2
        refusal(lambda: station.issue(*b), {"predecessor_pending", "missing_segment"})
        recovered = station.resume(*a)
        assert recovered.status == "confirmed" and recovered.operation == lost.operation
        assert (recovered.segment.sequence, recovered.segment.liters) == (1, capacity)
        assert recovered.segment.operation != recovered.operation
        assert station.cut(*a) == recovered
        assert station.reading(recorder).sequence == 2
    with open_station(root, offline=True) as station:
        try:
            station.withdraw("A")
        except StationError:
            pass
        else:
            raise AssertionError("full-scale ticket allowed withdrawal")
        first, second = station.issue(*a), station.issue(*b)
        assert first.report.segments == (recovered.segment,)
        assert second.report.segments == (later.segment,)
    with open_station(root, offline=True) as station:
        check_offline(station, a, first, 0, [(1, capacity, capacity)])
        check_offline(station, b, second, 1, [(2, capacity + 1 + extra, extra)])
    return {"case": "water-after-binding", "first": asdict(first), "second": asdict(second)}


def probe_v1(root, sample):
    recorder, capacity, extra = sample["recorder"], sample["capacity"], sample["extra"]
    args = (recorder, "A", "ordinary")
    with open_station(root) as station:
        station.configure(recorder, sample["setting"])
        station.business.execute("PRAGMA query_only = ON")
        for _ in range(capacity):
            station.record(recorder, 1)
        reading = station.reading(recorder)
        assert (reading.liters, reading.sequence) == (capacity, 0)
        station.business.execute("PRAGMA query_only = OFF")
        for _ in range(extra):
            station.record(recorder, 1)
        station.cut(*args)
    with open_station(root, offline=True) as station:
        issued = station.issue(*args)
    with open_station(root, offline=True) as station:
        check_offline(station, args, issued, 0, [(1, capacity + extra, capacity + extra)])
    return {"case": "ordinary-v1", "at_capacity": asdict(reading), "issued": asdict(issued)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("probe-v1", "verify", "demo"))
    args = parser.parse_args()
    sample = json.loads((Path(__file__).parent / "examples" / "full_scale.json").read_text(encoding="utf-8"))
    if args.command == "verify":
        if check_project.main():
            return 1
        cases = (before_binding, after_binding)
    else:
        cases = (probe_v1,) if args.command == "probe-v1" else (before_binding,)
    for case in cases:
        with TemporaryDirectory(prefix="chengbang-scale-") as folder:
            observed = case(Path(folder), sample)
        print("POINTWISE_SCENARIO " + json.dumps(observed, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
