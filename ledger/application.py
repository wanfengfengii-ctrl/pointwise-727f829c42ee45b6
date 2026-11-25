import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.handover import read_handover
from audit.reconcile import reconcile
from boundaries.tickets import install_tickets
from boundaries.withdrawals import withdraw
from capture.evidence import install_evidence
from capture.intake import cut
from capture.recovery import resume
from capture.segments import install_segments
from capture.store import StationError as StationError, open_business
from ledger.issue import issue
from ledger.postings import install_postings
from ledger.receipts import install_reports, receive
from source.counter import record, snapshot_reading
from source.register import configure
from source.store import open_source


class Station:
    def __init__(self, business, source):
        self.business = business
        self.source = source

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close_source()
        finally:
            self.business.close()

    def close_source(self):
        if self.source is not None:
            self.source.close()
            self.source = None

    def _connected_source(self):
        if self.source is None:
            raise StationError('source_unavailable')
        return self.source

    def configure(self, recorder, setting):
        return configure(self._connected_source(), recorder, setting)

    def record(self, recorder, liters=None):
        return record(self._connected_source(), recorder, liters)

    def reading(self, recorder):
        return snapshot_reading(self._connected_source(), recorder)

    def cut(self, recorder, ticket, request, *, lose_reply=False):
        return cut(self.business, self.source, recorder, ticket, request, lose_reply=lose_reply)

    def resume(self, recorder, ticket, request):
        return resume(self.business, self.source, recorder, ticket, request)

    def withdraw(self, ticket):
        return withdraw(self.business, ticket)

    def issue(self, recorder, ticket, request):
        return issue(self.business, recorder, ticket, request)

    def receive(self, ticket):
        return receive(self.business, ticket)

    def reconcile(self, ticket):
        return reconcile(self.business, ticket)

    def handover(self, ticket):
        return read_handover(self.business, ticket)


def open_station(root, *, offline=False):
    root = Path(root)
    if not offline:
        root.mkdir(parents=True, exist_ok=True)
    business = open_business(root / 'business.sqlite3', must_exist=offline)
    try:
        if offline:
            return Station(business, None)
        for install in (install_tickets, install_evidence, install_segments, install_reports, install_postings):
            install(business)
        return Station(business, open_source(root / 'source.sqlite3'))
    except BaseException:
        business.close()
        raise


def _refusal(action, *args):
    try:
        action(*args)
    except StationError as error:
        return error.code
    return 'accepted'


def _line_values(line):
    return [line.sequence, line.recorder, line.operation, line.point, line.liters]


def run_workday(root, sample, *, settlement='withdraw'):
    if settlement not in ('withdraw', 'sign'):
        raise ValueError('settlement must be withdraw or sign')
    recorder = sample['recorder']
    first, second = sample['first'], sample['second']
    first_args = (recorder, first['ticket'], first['request'])
    second_args = (recorder, second['ticket'], second['request'])
    with open_station(root) as station:
        station.configure(recorder, sample['setting'])
        for liters in first['increments']:
            station.record(recorder, liters)
        initial = station.cut(*first_args, lose_reply=True)
        for liters in second['increments']:
            station.record(recorder, liters)
        later = station.cut(*second_args)
        blocked = _refusal(station.issue, *second_args)
        early_receive = _refusal(station.receive, second['ticket'])
        recovered = station.resume(*first_args)
        if recovered.segment is None or later.segment is None:
            raise StationError('workday_cut_pending', recorder)
        if settlement == 'withdraw':
            disposition = station.withdraw(first['ticket']).state
            first_issued = None
        else:
            first_issued = station.issue(*first_args)
            disposition = _refusal(station.withdraw, first['ticket'])
        physical_sequences = [recovered.segment.sequence, later.segment.sequence]
    with open_station(root, offline=True) as station:
        issued = station.issue(*second_args)
        handover = station.handover(second['ticket'])
        if first_issued is None:
            historical = _refusal(station.receive, first['ticket'])
        else:
            historical = 'same' if station.receive(first['ticket']) == first_issued else 'changed'
    return {
        'actual': {
            'initial_capture': initial.status,
            'physical_sequences': physical_sequences,
            'early_issue': blocked,
            'early_receive': early_receive,
            'first_disposition': disposition,
            'first_liters': None if first_issued is None else first_issued.report.liters,
            'after': issued.report.after,
            'through': issued.report.through,
            'liters': issued.report.liters,
            'lines': [_line_values(line) for line in issued.report.segments],
        },
        'downstream_actual': {
            'first': historical,
            'liters': handover.reconciliation.liters,
            'lines': [_line_values(line) for line in handover.reconciliation.lines],
            'receipt': handover.issued.receipt.receipt_id,
            'same_issued': handover.issued == issued,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='澄浜回用水站流量交班')
    parser.add_argument('command', choices=('demo',))
    parser.add_argument('--settlement', choices=('withdraw', 'sign'), default='withdraw')
    args = parser.parse_args(argv)
    sample_path = Path(__file__).resolve().parents[1] / 'examples' / 'workday.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    oracle = sample['oracles'][args.settlement]
    case_id = oracle['case_id']
    try:
        with TemporaryDirectory(prefix='chengbang-') as root:
            observed = run_workday(root, sample, settlement=args.settlement)
    except StationError as error:
        raise SystemExit(f'{case_id}: {error}') from error
    if observed['actual'] != oracle['expected'] or observed['downstream_actual'] != oracle['downstream_expected']:
        raise SystemExit(f'{case_id}: {json.dumps(observed, ensure_ascii=False, sort_keys=True)}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        **oracle,
        **observed,
        'input': {key: sample[key] for key in ('recorder', 'setting', 'first', 'second')},
        'code_paths': [
            'source/cut.py', 'capture/recovery.py', 'boundaries/withdrawals.py',
            'ledger/issue.py', 'ledger/coverage.py', 'audit/reconcile.py',
        ],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
