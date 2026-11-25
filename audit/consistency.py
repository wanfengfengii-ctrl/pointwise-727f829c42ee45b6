from capture.store import StationError


class AuditMismatch(StationError):
    def __init__(self, category, detail):
        self.category = category
        super().__init__(f'audit_{category}', detail)


def verify_total(report, lines):
    actual = 0
    for line in lines:
        actual += line.liters
    if actual != report.liters:
        raise AuditMismatch('total', report.ticket)
    return actual


def verify_receipt(report, receipt):
    if (receipt.ticket, receipt.through) != (report.ticket, report.through):
        raise AuditMismatch('receipt', report.ticket)
    if receipt.receipt_id != f'receipt/{report.ticket}':
        raise AuditMismatch('receipt', report.ticket)
