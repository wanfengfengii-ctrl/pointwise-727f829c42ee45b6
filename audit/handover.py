from dataclasses import dataclass

from audit.reconcile import Reconciliation, reconcile_issued
from capture.store import business_read
from ledger.receipts import Issued, read_issued


@dataclass(frozen=True)
class Handover:
    issued: Issued
    reconciliation: Reconciliation


def read_handover(db, ticket):
    with business_read(db):
        issued = read_issued(db, ticket)
        return Handover(issued, reconcile_issued(db, issued))
