"""Python-level outbound guard; this does not replace an OS firewall."""

import os
import sys

OUTBOUND_ATTEMPTS = []
_enabled = False


def deny_external_sockets(event, args):
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return
        OUTBOUND_ATTEMPTS.append(event)
        raise RuntimeError("Offline mode blocked a Python external socket")
    if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", "localhost"}:
        OUTBOUND_ATTEMPTS.append(event)
        raise RuntimeError("Offline mode blocked external DNS")


def enable():
    global _enabled
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not _enabled:
        sys.addaudithook(deny_external_sockets)
        _enabled = True
