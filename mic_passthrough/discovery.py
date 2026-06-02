"""
Simple UDP broadcast discovery — no external libraries needed.
PC broadcasts its IP every 2 seconds on port 9877.
Mac listens and shows discovered PCs in the menu.
"""

import socket
import threading
import time

DISCOVERY_PORT = 9877
BROADCAST_INTERVAL = 2
DISCOVERY_TIMEOUT = 6  # remove PC if not seen for this many seconds


class PCBroadcaster:
    """PC side — broadcasts selected IP so Mac can find it."""

    def __init__(self, get_ip_fn):
        self.get_ip_fn = get_ip_fn
        self.running = False
        self.thread = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        hostname = socket.gethostname()
        while self.running:
            ip = self.get_ip_fn()
            msg = f"MIC-PASSTHROUGH|{hostname}|{ip}".encode()
            try:
                self.sock.sendto(msg, ('<broadcast>', DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(BROADCAST_INTERVAL)


class PCDiscovery:
    """Mac side — listens for PC broadcasts and calls callback with (name, ip)."""

    def __init__(self, on_update):
        self.on_update = on_update
        self.peers = {}  # ip -> (name, last_seen)
        self.running = False
        self.sock = None

    def start(self):
        self.running = True
        threading.Thread(target=self._listen, daemon=True).start()
        threading.Thread(target=self._expire, daemon=True).start()

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()

    def _listen(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.bind(('', DISCOVERY_PORT))
        self.sock.settimeout(1)
        while self.running:
            try:
                data, addr = self.sock.recvfrom(256)
                msg = data.decode()
                if msg.startswith("MIC-PASSTHROUGH|"):
                    _, name, ip = msg.split('|')
                    updated = ip not in self.peers
                    self.peers[ip] = (name, time.time())
                    if updated:
                        self.on_update(dict(self.peers))
            except socket.timeout:
                pass
            except Exception:
                break

    def _expire(self):
        while self.running:
            now = time.time()
            expired = [ip for ip, (_, ts) in self.peers.items()
                       if now - ts > DISCOVERY_TIMEOUT]
            if expired:
                for ip in expired:
                    del self.peers[ip]
                self.on_update(dict(self.peers))
            time.sleep(1)
