def install_postings(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS segment_postings (
            sequence INTEGER PRIMARY KEY REFERENCES segments(sequence),
            ticket TEXT NOT NULL REFERENCES official_reports(ticket) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX IF NOT EXISTS postings_by_ticket ON segment_postings(ticket, sequence);
    ''')


def post_segments(db, ticket, segments):
    db.executemany(
        'INSERT INTO segment_postings VALUES (?, ?)',
        ((segment.sequence, ticket) for segment in segments),
    )


def segment_owners(db, after, through):
    rows = db.execute(
        'SELECT sequence, ticket FROM segment_postings WHERE sequence > ? AND sequence <= ?', (after, through)
    )
    return {row['sequence']: row['ticket'] for row in rows}


def read_postings(db, ticket):
    rows = db.execute('SELECT sequence FROM segment_postings WHERE ticket = ? ORDER BY sequence', (ticket,))
    return tuple(row['sequence'] for row in rows)
