"""Optional B7 process-wide network guard, activated only by ASAR_OFFLINE=1."""
import os
import socket

if os.environ.get("ASAR_OFFLINE") == "1":
    def denied(*args, **kwargs):
        raise OSError("ASAR offline verification forbids network socket connections")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
