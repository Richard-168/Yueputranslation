"""Cancellation shared by local and optional cloud inference."""


class InferenceCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise InferenceCancelled()
