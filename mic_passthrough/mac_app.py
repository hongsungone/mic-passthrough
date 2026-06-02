"""
Mac menu bar app — click the mic icon to connect/disconnect.
Requires: pip install rumps psutil
"""

import socket
import threading
import rumps
import numpy as np
import sounddevice as sd
from mic_passthrough.discovery import PCDiscovery

PORT = 9876
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK = 480


def get_local_ips():
    import psutil
    ips = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ips.append((name, addr.address))
    return ips



class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.pc_ip = None
        self.streaming = False
        self.stream = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.discovered = {}
        self.local_ips = get_local_ips()
        print("Local IPs found:", self.local_ips)
        # prefer en0 (WiFi) as default
        self.selected_local_ip = next(
            (ip for iface, ip in self.local_ips if iface == 'en0'),
            self.local_ips[0][1] if self.local_ips else None
        )

        ip_items = []
        for iface, ip in self.local_ips:
            title = f"{iface} - {ip}"
            item = rumps.MenuItem(title, callback=self._make_local_selector(iface, ip))
            item.state = 1 if ip == self.selected_local_ip else 0
            ip_items.append(item)

        self.menu = (
            [rumps.MenuItem("Not connected", callback=None), None,
             rumps.MenuItem("Broadcast from:", callback=None)]
            + ip_items
            + [None,
               rumps.MenuItem("Discovered:", callback=None),
               rumps.MenuItem("  Scanning…", callback=None),
               None,
               rumps.MenuItem("Connect", callback=self.connect),
               rumps.MenuItem("Disconnect", callback=self.disconnect),
               rumps.MenuItem("Quit", callback=self.quit_app)]
        )

        self._start_discovery()

    def _make_local_selector(self, iface, ip):
        def select(_):
            self.selected_local_ip = ip
            for n, a in self.local_ips:
                title = f"{n} - {a}"
                if title in self.menu:
                    self.menu[title].state = 1 if a == ip else 0
            # reset pc_ip so it picks up the PC on the new subnet
            self.pc_ip = None
            self.menu["Not connected"].title = "Not connected"
            self.discovered = {}
            self._rebuild_discovered_menu()
            self.discovery.stop()
            self._start_discovery()
        return select

    def _start_discovery(self):
        self.discovery = PCDiscovery(self._on_discovery_update, self.selected_local_ip)
        self.discovery.start()

    def _on_discovery_update(self, peers):
        self.discovered = {ip: name for ip, (name, _) in peers.items()}
        self._rebuild_discovered_menu()
        # auto-select first discovered PC if none selected
        if self.discovered and not self.pc_ip:
            self._on_discovery_update_set_ip(next(iter(self.discovered)))

    def _rebuild_discovered_menu(self):
        for key in list(self.menu.keys()):
            if key.startswith("  ") and key != "  Scanning…":
                del self.menu[key]

        if not self.discovered:
            if "  Scanning…" not in self.menu:
                self.menu.insert_after("Discovered:", rumps.MenuItem("  Scanning…", callback=None))
        else:
            if "  Scanning…" in self.menu:
                del self.menu["  Scanning…"]
            for ip, name in self.discovered.items():
                title = f"  {name} ({ip})"
                item = rumps.MenuItem(title, callback=None)  # not clickable
                self.menu.insert_after("Discovered:", item)

    def _on_discovery_update_set_ip(self, ip):
        if not self.pc_ip:
            self.pc_ip = ip
            self.menu["Not connected"].title = f"PC: {ip}"

    @rumps.clicked("Connect")
    def connect(self, _):
        if self.pc_ip:
            self._start()

    @rumps.clicked("Disconnect")
    def disconnect(self, _):
        self._stop()

    def _start(self):
        def do_start():
            self.menu["Not connected"].title = "Connecting…"

            def callback(indata, frames, t, status):
                if self.streaming and self.pc_ip:
                    pcm = (indata[:, 0] * 32767).astype(np.int16)
                    self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                blocksize=CHUNK, device=None, callback=callback
            )
            self.stream.start()
            self.streaming = True
            self.title = "🎙●"
            self.menu["Not connected"].title = f"Streaming → {self.pc_ip}"

        threading.Thread(target=do_start, daemon=True).start()

    def _stop(self):
        self.streaming = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.title = "🎙"
        self.menu["Not connected"].title = "Not connected"

    def quit_app(self, _):
        self._stop()
        self.discovery.stop()
        rumps.quit_application()


def main():
    MicPassthroughApp().run()


if __name__ == "__main__":
    main()
