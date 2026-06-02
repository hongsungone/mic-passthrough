"""
Mac menu bar app — click the mic icon to connect/disconnect.
Requires: pip install rumps zeroconf
"""

import socket
import subprocess
import threading
import time
import rumps
import numpy as np
import sounddevice as sd
from mic_passthrough.discovery import PCDiscovery

PORT = 9876
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK = 480


def get_active_bt_audio_mac():
    try:
        default_input = sd.query_devices(kind='input')['name']
        result = subprocess.run(['blueutil', '--paired'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if 'connected' not in line:
                continue
            name_match = None
            if 'name:' in line:
                name_match = line.split('name:')[-1].strip().strip('"').split('"')[0]
            if name_match and name_match.lower() in default_input.lower():
                for part in line.split(','):
                    part = part.strip()
                    if part.startswith('address:'):
                        return part.replace('address:', '').strip(), name_match
    except Exception:
        pass
    return None, None


def reconnect_bt_device(mac):
    subprocess.run(['blueutil', '--disconnect', mac], capture_output=True)
    time.sleep(3)
    subprocess.run(['blueutil', '--connect', mac], capture_output=True)
    time.sleep(3)



class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.pc_ip = None
        self.streaming = False
        self.stream = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.discovered = {}  # ip -> name

        self.menu = [
            rumps.MenuItem("Not connected", callback=None),
            None,
            rumps.MenuItem("Discovered:", callback=None),
            rumps.MenuItem("  Scanning…", callback=None),
            None,
            rumps.MenuItem("Set PC IP Address…", callback=self.set_ip),
            rumps.MenuItem("Connect", callback=self.toggle_connect),
            rumps.MenuItem("Reconnect BT Device", callback=self.reconnect_bt_menu),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        # start UDP broadcast discovery
        self.discovery = PCDiscovery(self._on_discovery_update)
        self.discovery.start()

    def _on_discovery_update(self, peers):
        # peers: {ip -> (name, last_seen)}
        self.discovered = {ip: name for ip, (name, _) in peers.items()}
        self._rebuild_discovered_menu()

    def _rebuild_discovered_menu(self):
        # remove old discovered items
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
                item = rumps.MenuItem(title, callback=self._make_selector(ip))
                self.menu.insert_after("Discovered:", item)

    def _make_selector(self, ip):
        def select(_):
            self.pc_ip = ip
            self.menu["Not connected"].title = f"PC: {ip}"
        return select

    @rumps.clicked("Set PC IP Address…")
    def set_ip(self, _):
        response = rumps.Window(
            title="Mic Passthrough",
            message="Enter your PC's IP address:",
            default_text=self.pc_ip or "",
            ok="Save",
            cancel="Cancel",
            dimensions=(260, 24),
        ).run()
        if response.clicked and response.text.strip():
            self.pc_ip = response.text.strip()
            self.menu["Not connected"].title = f"PC: {self.pc_ip}"

    @rumps.clicked("Connect")
    def toggle_connect(self, sender):
        if self.streaming:
            self._stop()
        else:
            if not self.pc_ip:
                self.set_ip(None)
            if self.pc_ip:
                self._start()

    @rumps.clicked("Reconnect BT Device")
    def reconnect_bt_menu(self, _):
        def do_reconnect():
            self.menu["Reconnect BT Device"].title = "Reconnecting…"
            mac, name = get_active_bt_audio_mac()
            if mac:
                reconnect_bt_device(mac)
            self.menu["Reconnect BT Device"].title = "Reconnect BT Device"
        threading.Thread(target=do_reconnect, daemon=True).start()

    def _start(self):
        def do_start():
            self.menu["Not connected"].title = "Connecting…"

            def callback(indata, frames, time, status):
                if self.streaming and self.pc_ip:
                    pcm = (indata[:, 0] * 32767).astype(np.int16)
                    self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                blocksize=CHUNK, device=None, callback=callback
            )
            self.stream.start()

            # wait for BT profile switch then reconnect
            time.sleep(1)
            mac, name = get_active_bt_audio_mac()
            if mac:
                reconnect_bt_device(mac)

            self.streaming = True
            self.title = "🎙●"
            self.menu["Connect"].title = "Disconnect"
            self.menu["Not connected"].title = f"Streaming → {self.pc_ip}"

        threading.Thread(target=do_start, daemon=True).start()

    def _stop(self):
        self.streaming = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.title = "🎙"
        self.menu["Connect"].title = "Connect"
        self.menu["Not connected"].title = f"PC: {self.pc_ip}"

    def quit_app(self, _):
        self._stop()
        self.discovery.stop()
        rumps.quit_application()


def main():
    MicPassthroughApp().run()


if __name__ == "__main__":
    main()
