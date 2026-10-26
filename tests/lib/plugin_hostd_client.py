# SPDX-License-Identifier: GPL-3.0-or-later
"""The mod-host line protocol from Python, the one client every test of plugin-hostd, omx-clap-host and the controllers
imports: a command is one line ended by a NUL, a reply is one NUL-ended line. Installed by plugin-hostd-tests as
/usr/libexec/plugin-hostd/tests/lib/plugin_hostd_client.py, and in this tree as tests/lib/plugin_hostd_client.py.

    c = Client(sock)            a connected socket, or Client.connect(port)
    c.send(line)                the reply; ConnectionError when the peer closes, socket.timeout when none comes in time
    c.try_send(line, timeout)   (reply, None), or (None, 'closed' | 'timeout' | 'oserror <why>'): a test that expects a death
    c.expect(line, wanted)      the reply, AssertionError when it is not wanted
"""
import socket
import time


class Client:
    def __init__(self, sock, timeout=10.0):
        self.sock = sock
        self.timeout = timeout
        self.buf = b""

    @classmethod
    def connect(cls, port, host="127.0.0.1", timeout=10.0):
        return cls(socket.create_connection((host, port), timeout=timeout), timeout)

    def send(self, line, timeout=None):
        self.sock.sendall(line.encode() + b"\0")
        end = time.monotonic() + (self.timeout if timeout is None else timeout)
        while b"\0" not in self.buf:
            left = end - time.monotonic()
            if left <= 0:
                raise socket.timeout("no reply to %r" % line)
            self.sock.settimeout(left)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("the peer closed on " + line)
            self.buf += chunk
        reply, self.buf = self.buf.split(b"\0", 1)
        return reply.decode(errors="replace")

    def try_send(self, line, timeout=None):
        try:
            return self.send(line, timeout), None
        except socket.timeout:
            return None, "timeout"
        except ConnectionError:
            return None, "closed"
        except OSError as e:
            return None, "oserror %s" % e

    def expect(self, line, wanted):
        reply = self.send(line)
        if reply != wanted:
            raise AssertionError("%s -> %r, wanted %r" % (line, reply, wanted))
        return reply

    def close(self):
        self.sock.close()
