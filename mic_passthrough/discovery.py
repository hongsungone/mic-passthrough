"""
Discovery: Mac broadcasts a ping, PC responds directly back.
No Windows firewall rules needed — PC only receives and replies.
"""

import socket
import threading
import time

DISCOVERY_PORT = 9877
BROADCAST_INTERVAL = 2
DISCOVERY_TIMEOUT = 6

PING_MSG = b"MIC-PASSTHROUGH-PING"
PONG_PREFIX = "MIC-PASSTHROUGH-PONG|"


class PCResponder:
    """PC side — listens for Mac pings and responds with hostname + matching subnet IP."""

    def __init__(self, get_ip_fn, on_ip_change=None):
        self.get_ip_fn = get_ip_fn
        self.on_ip_change = on_ip_change  # called when best IP changes
        self.running = False
        self.last_best_ip = None

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _best_ip_for(self, requester_ip):
        """Pick the local IP on the same subnet as the requester."""
        import psutil
        requester_prefix = '.'.join(requester_ip.split('.')[:3])
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    prefix = '.'.join(addr.address.split('.')[:3])
                    if prefix == requester_prefix:
                        return addr.address
        return self.get_ip_fn()  # fallback to selected IP

    def _loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', DISCOVERY_PORT))
        sock.settimeout(1)
        hostname = socket.gethostname()
        while self.running:
            try:
                data, addr = sock.recvfrom(256)
                if data == PING_MSG:
                    requester_ip = addr[0]
                    ip = self._best_ip_for(requester_ip)
                    msg = f"{PONG_PREFIX}{hostname}|{ip}".encode()
                    sock.sendto(msg, addr)
                    # notify tray to switch listening IP if changed
                    if ip != self.last_best_ip:
                        self.last_best_ip = ip
                        if self.on_ip_change:
                            self.on_ip_change(ip)
            except socket.timeout:
                pass
            except Exception:
                break
        sock.close()


class PCDiscovery:
    """Mac side — broadcasts pings from selected IP and collects PC responses."""

    def __init__(self, on_update, source_ip=None):
        self.on_update = on_update
        self.source_ip = source_ip  # broadcast from this IP
        self.peers = {}  # ip -> (name, last_seen)
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._ping_loop, daemon=True).start()
        threading.Thread(target=self._expire_loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _ping_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_ip = self.source_ip or ''
        sock.bind((bind_ip, DISCOVERY_PORT))
        sock.settimeout(1)

        while self.running:
            # send ping to broadcast
            try:
                sock.sendto(PING_MSG, ('<broadcast>', DISCOVERY_PORT))
            except Exception:
                pass

            # collect responses for 1.5 seconds
            deadline = time.time() + 1.5
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(256)
                    msg = data.decode()
                    if msg.startswith(PONG_PREFIX):
                        _, name, ip = msg.split('|')
                        updated = ip not in self.peers
                        self.peers[ip] = (name, time.time())
                        if updated:
                            self.on_update(dict(self.peers))
                except socket.timeout:
                    break
                except Exception:
                    pass

            time.sleep(BROADCAST_INTERVAL)

        sock.close()

    def _expire_loop(self):
        while self.running:
            now = time.time()
            expired = [ip for ip, (_, ts) in self.peers.items()
                       if now - ts > DISCOVERY_TIMEOUT]
            if expired:
                for ip in expired:
                    del self.peers[ip]
                self.on_update(dict(self.peers))
            time.sleep(1)
