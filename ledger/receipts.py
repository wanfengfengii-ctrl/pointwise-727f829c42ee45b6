from dataclasses import dataclass

from boundaries.tickets import read_ticket
from capture.segments import Segment
from capture.store import StationError, business_read


@dataclass(frozen=True)
class OfficialReport:
    ticket: str
    recorder: str
    after: int
    through: int
    liters: int
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class FirstReceipt:
    receipt_id: str
    ticket: str
    through: int


@dataclass(frozen=True)
class Issued:
    report: OfficialReport
    receipt: FirstReceipt


def install_reports(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS official_reports (
            ticket TEXT PRIMARY KEY REFERENCES boundary_tickets(ticket),
            recorder TEXT NOT NULL,
            after_sequence INTEGER NOT NULL CHECK (after_sequence >= 0),
            through_sequence INTEGER NOT NULL UNIQUE CHECK (through_sequence > after_sequence),
            liters TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_lines (
            ticket TEXT NOT NULL REFERENCES official_reports(ticket),
            position INTEGER NOT NULL CHECK (position > 0),
            sequence INTEGER NOT NULL,
            recorder TEXT NOT NULL,
            operation TEXT NOT NULL,
            point INTEGER NOT NULL,
            liters TEXT NOT NULL,
            PRIMARY KEY (ticket, position),
            UNIQUE (ticket, sequence)
        );
        CREATE TABLE IF NOT EXISTS first_receipts (
            ticket TEXT PRIMARY KEY REFERENCES official_reports(ticket),
            receipt_id TEXT NOT NULL UNIQUE,
            through_sequence INTEGER NOT NULL
        );
    ''')


def save_issued(db, report):
    db.execute(
        'INSERT INTO official_reports VALUES (?, ?, ?, ?, ?)',
        (report.ticket, report.recorder, report.after, report.through, format(report.liters, 'x')),
    )
    db.executemany('INSERT INTO report_lines VALUES (?, ?, ?, ?, ?, ?, ?)', (
        (report.ticket, position, line.sequence, line.recorder, line.operation, line.point, format(line.liters, 'x'))
        for position, line in enumerate(report.segments, 1)
    ))
    receipt = FirstReceipt(f'receipt/{report.ticket}', report.ticket, report.through)
    db.execute(
        'INSERT INTO first_receipts VALUES (?, ?, ?)',
        (receipt.ticket, receipt.receipt_id, receipt.through),
    )
    return Issued(report, receipt)


def _read_report(db, header):
    if header is None:
        return None
    lines = db.execute('''
        SELECT sequence, recorder, operation, point, liters FROM report_lines
         WHERE ticket = ? ORDER BY position
    ''', (header['ticket'],))
    try:
        segments = tuple(Segment(*line[:4], int(line['liters'], 16)) for line in lines)
        liters = int(header['liters'], 16)
    except ValueError as error:
        raise StationError('issued_invalid', header['ticket']) from error
    return OfficialReport(
        header['ticket'], header['recorder'], header['after_sequence'], header['through_sequence'], liters, segments,
    )


def latest_report(db):
    header = db.execute('SELECT * FROM official_reports ORDER BY through_sequence DESC LIMIT 1').fetchone()
    return _read_report(db, header)


def report_before(db, through):
    header = db.execute('''
        SELECT * FROM official_reports WHERE through_sequence < ?
         ORDER BY through_sequence DESC LIMIT 1
    ''', (through,)).fetchone()
    return _read_report(db, header)


def read_issued(db, ticket):
    current = read_ticket(db, ticket)
    if current.state != 'signed':
        code = 'withdrawn' if current.state == 'withdrawn' else 'not_issued'
        raise StationError(code, ticket)
    header = db.execute('SELECT * FROM official_reports WHERE ticket = ?', (ticket,)).fetchone()
    receipt = db.execute(
        'SELECT receipt_id, ticket, through_sequence FROM first_receipts WHERE ticket = ?', (ticket,)
    ).fetchone()
    if header is None or receipt is None:
        raise StationError('issued_incomplete', ticket)
    return Issued(_read_report(db, header), FirstReceipt(*receipt))


def receive(db, ticket):
    with business_read(db):
        return read_issued(db, ticket)
