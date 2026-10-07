"""Test-process-only outbound guard, inherited by stdio subprocesses."""

import socket


def denied(*args, **kwargs):
    raise AssertionError("Offline tests attempted an outbound socket operation")


socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
socket.getaddrinfo = denied
