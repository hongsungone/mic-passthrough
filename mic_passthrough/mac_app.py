"""
Mac menu bar app — click the mic icon to connect/disconnect.
Requires: pip install rumps
"""

import socket
import subprocess
import threading
import time
import rumps
import numpy as np
import sounddevice as sd

PORT = 9876
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK = 480


def get_airpods_mac():
    """Find MAC address of connected AirPods using blueutil."""
    try:
        result = subprocess.run(
            ['blueutil', '--connected'],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if 'airpods' in line.lower() or 'AirPods' in line:
                # extract MAC address (format: address: xx-xx-xx-xx-xx-xx)
                for part in line.split():
                    if '-' in part and len(part) == 17:
                        return part
    except FileNotFoundError:
        pass
    return None


def reconnect_airpods(mac):
    """Disconnect and reconnect AirPods to avoid clicking."""
    subprocess.run(['blueutil', '--disconnect', mac], capture_output=True)
    time.sleep(1.5)
    subprocess.run(['blueutil', '--connect', mac], capture_output=True)
    time.sleep(2)


class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.pc_ip = None
        self.streaming = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # keep stream always open to avoid audio reconfiguration clicks
        def callback(indata, frames, time, status):
            if self.streaming and self.pc_ip:
                pcm = (indata[:, 0] * 32767).astype(np.int16)
                self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
            blocksize=CHUNK, device=None, callback=callback
        )
        self.stream.start()

        self.menu = [
            rumps.MenuItem("Not connected", callback=None),
            None,
            rumps.MenuItem("Set PC IP Address…", callback=self.set_ip),
            rumps.MenuItem("Connect", callback=self.toggle_connect),
            rumps.MenuItem("Reconnect AirPods", callback=self.reconnect_airpods_menu),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

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

    @rumps.clicked("Reconnect AirPods")
    def reconnect_airpods_menu(self, _):
        def do_reconnect():
            self.menu["Reconnect AirPods"].title = "Reconnecting…"
            mac = get_airpods_mac()
            if mac:
                reconnect_airpods(mac)
                self.menu["Reconnect AirPods"].title = "Reconnect AirPods"
            else:
                self.menu["Reconnect AirPods"].title = "Reconnect AirPods"
                rumps.notification("Mic Passthrough", "", "AirPods not found. Is blueutil installed?")
        threading.Thread(target=do_reconnect, daemon=True).start()

    def _start(self):
        # reconnect AirPods in background to avoid clicking
        def start_with_reconnect():
            mac = get_airpods_mac()
            if mac:
                reconnect_airpods(mac)
            self.streaming = True
            self.title = "🎙●"
            self.menu["Connect"].title = "Disconnect"
            self.menu["Not connected"].title = f"Streaming → {self.pc_ip}"
        threading.Thread(target=start_with_reconnect, daemon=True).start()
        self.menu["Not connected"].title = "Reconnecting AirPods…"

    def _stop(self):
        self.streaming = False
        self.title = "🎙"
        self.menu["Connect"].title = "Connect"
        self.menu["Not connected"].title = f"PC: {self.pc_ip}"

    def quit_app(self, _):
        self._stop()
        self.stream.stop()
        self.stream.close()
        rumps.quit_application()


def main():
    MicPassthroughApp().run()


if __name__ == "__main__":
    main()
