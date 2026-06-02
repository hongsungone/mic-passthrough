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
    try:
        result = subprocess.run(['blueutil', '--paired'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if 'airpods' in line.lower():
                for part in line.split(','):
                    part = part.strip()
                    if part.startswith('address:'):
                        return part.replace('address:', '').strip()
    except FileNotFoundError:
        pass
    return None


def reconnect_airpods(mac):
    subprocess.run(['blueutil', '--disconnect', mac], capture_output=True)
    time.sleep(3)  # wait longer for full BT disconnect
    subprocess.run(['blueutil', '--connect', mac], capture_output=True)
    time.sleep(3)  # wait for full BT reconnect


class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.pc_ip = None
        self.streaming = False
        self.stream = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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
        threading.Thread(target=do_reconnect, daemon=True).start()

    def _start(self):
        def do_start():
            self.menu["Not connected"].title = "Connecting…"

            # open stream (triggers profile switch + click)
            def callback(indata, frames, time, status):
                if self.streaming and self.pc_ip:
                    pcm = (indata[:, 0] * 32767).astype(np.int16)
                    self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                blocksize=CHUNK, device=None, callback=callback
            )
            self.stream.start()

            # wait for profile switch to settle then reconnect AirPods
            time.sleep(1)
            mac = get_airpods_mac()
            if mac:
                reconnect_airpods(mac)

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
        rumps.quit_application()


def main():
    MicPassthroughApp().run()


if __name__ == "__main__":
    main()
