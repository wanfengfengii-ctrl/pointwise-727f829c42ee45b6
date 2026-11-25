from capture.recovery import collect_request


def cut(business, source, recorder, ticket, request, *, lose_reply=False):
    return collect_request(
        business, source, recorder, ticket, request,
        allow_registration=True, lose_reply=lose_reply,
    )
