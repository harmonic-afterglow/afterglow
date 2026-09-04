"""Talking to the remote's own shell.

The Harmony 900 runs QNX with a telnet server, and keeps a system log of what it was
asked to do. That log is the difference between reading a failure and inferring it: a
configuration that froze the remote and rebooted it was diagnosed here by diffing bytes,
and the remote would have said so directly.

`telnetlib` went out of the standard library in 3.13, so the protocol is ours now. It
cannot be tested against a remote in CI, but the part that actually goes wrong - option
negotiation, and finding the end of a command's output in a stream that contains prompts
and 0xFF bytes of its own - is testable against a server that behaves like one.
"""
import socket
import threading

import pytest

from afterglow import remote_shell as rs

IAC, DO, WILL, WONT, DONT, SB, SE = (bytes([b]) for b in (255, 253, 251, 252, 254, 250, 240))


# negotiation
def test_options_are_refused_so_the_stream_becomes_plain_text():
    data = IAC + DO + b"\x01" + b"hello" + IAC + WILL + b"\x03" + b" there"
    payload, reply = rs._refuse(data)
    assert payload == b"hello there"
    assert reply == IAC + WONT + b"\x01" + IAC + DONT + b"\x03"


def test_an_escaped_ff_is_data_not_a_command():
    payload, reply = rs._refuse(b"a" + IAC + IAC + b"b")
    assert payload == b"a\xffb" and reply == b""


def test_subnegotiation_is_skipped_whole():
    data = b"x" + IAC + SB + b"\x18\x01rubbish" + IAC + SE + b"y"
    payload, _reply = rs._refuse(data)
    assert payload == b"xy"


def test_a_command_split_across_reads_does_not_corrupt_the_output():
    """A three-byte option can arrive one byte at a time; the tail is dropped rather
    than being mistaken for text."""
    payload, _reply = rs._refuse(b"text" + IAC + DO)
    assert payload == b"text"


# a server that behaves like the remote
class FakeRemote:
    """Enough of the remote to exercise login and one command."""

    def __init__(self, log_text, *, password="ethanol", greet_with_options=True):
        self.log_text, self.password = log_text, password
        self.greet_with_options = greet_with_options
        self.seen = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @staticmethod
    def _recv_line(conn):
        """A whole line, with telnet commands stripped - the client answers our option
        offers before it answers the login prompt, and treating that reply as the
        username is what a naive double gets wrong."""
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = conn.recv(256)
            if not chunk:
                break
            payload, _reply = rs._refuse(chunk)
            buffer += payload
        return bytes(buffer).strip()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            if self.greet_with_options:
                conn.sendall(IAC + DO + b"\x18" + IAC + WILL + b"\x03")
            conn.sendall(b"\r\nlogin: ")
            user = self._recv_line(conn)
            self.seen.append(user)
            conn.sendall(b"Password: ")
            given = self._recv_line(conn)
            self.seen.append(given)
            if given != self.password.encode():
                conn.sendall(b"\r\nLogin incorrect\r\nlogin: ")
                return
            conn.sendall(b'\r\nNo home directory.\r\nLogging in with home = "/".\r\n# ')
            line = self._recv_line(conn).decode()
            self.seen.append(line.strip())
            conn.sendall(line.encode() + b"\r\n")         # servers echo the command
            conn.sendall(b"\r\n" + self.log_text.encode() + b"\r\n")
            marker = line.split("echo ")[-1].strip()
            conn.sendall(marker.encode() + b"\r\n# ")


LOG = ("Time             Sev Major Minor Args\r\n"
       "HAO: Send Command: \r\n"
       "Device ID: 92577825\r\n"
       "Code: 0400F4010300010000FEC03F00\r\n"
       "source/irqueue.c : 600 : sendCommand():start command")


def test_it_logs_in_and_returns_what_the_command_printed():
    server = FakeRemote(LOG)
    out = rs.run("sloginfo", host="127.0.0.1", timeout=5, port=server.port)
    assert "Code: 0400F4010300010000FEC03F00" in out
    assert "sendCommand()" in out
    assert server.seen[0] == b"root" and server.seen[1] == b"ethanol"


def test_the_echoed_command_is_not_returned_as_output():
    server = FakeRemote(LOG)
    out = rs.run("sloginfo", host="127.0.0.1", timeout=5, port=server.port)
    assert not out.startswith("sloginfo")


def test_the_marker_is_not_left_in_the_output():
    server = FakeRemote(LOG)
    assert "__afterglow_done__" not in rs.run(
        "sloginfo", host="127.0.0.1", timeout=5, port=server.port)


def test_output_containing_a_prompt_is_not_truncated():
    """The log prints "# " itself, so ending on the prompt would cut it short. That is
    why a marker is used instead."""
    tricky = "line one\r\n# not really a prompt\r\nline three"
    server = FakeRemote(tricky)
    out = rs.run("sloginfo", host="127.0.0.1", timeout=5, port=server.port)
    assert "line three" in out


def test_a_wrong_password_is_reported_rather_than_hanging():
    server = FakeRemote(LOG, password="something-else")
    with pytest.raises(rs.NotReachable, match="refused"):
        rs.run("sloginfo", host="127.0.0.1", timeout=5, port=server.port)


def test_a_server_that_never_negotiates_still_works():
    server = FakeRemote(LOG, greet_with_options=False)
    assert "sendCommand()" in rs.run(
        "sloginfo", host="127.0.0.1", timeout=5, port=server.port)


def test_nothing_listening_says_what_to_do_about_it():
    """Points at the thing that can fix it, not at a script to type.

    Afterglow sets the USB link up itself now, so naming `harmony_net.sh` here would send
    someone to run by hand what the application already ran - which is how a solved
    problem keeps looking unsolved.
    """
    with pytest.raises(rs.NotReachable, match="not finished connecting"):
        rs.run("sloginfo", host="127.0.0.1", timeout=1)


def test_reachable_is_false_when_nothing_answers():
    assert rs.reachable("127.0.0.1", timeout=0.5) is False


def test_the_defaults_are_the_documented_ones():
    assert rs.REMOTE_IP == "169.254.1.2" and rs.TELNET_PORT == 23
    assert rs.DEFAULT_USER == "root" and rs.DEFAULT_PASSWORD == "ethanol"
