"""
Mac menu bar app — click the mic icon to connect/disconnect.
Requires: pip install rumps
"""

import threading
import socket
import rumps
import numpy as np
import sounddevice as sd

PORT = 9876
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK = 480


class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.menu = [
            rumps.MenuItem("Not connected", callback=None),
            None,  # separator
            rumps.MenuItem("Set PC IP Address…", callback=self.set_ip),
            rumps.MenuItem("Connect", callback=self.toggle_connect),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]
        self.pc_ip = None
        self.streaming = False
        self.stream = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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

    def _start(self):
        def callback(indata, frames, time, status):
            pcm = (indata[:, 0] * 32767).astype(np.int16)
            self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
            blocksize=CHUNK, callback=callback
        )
        self.stream.start()
        self.streaming = True
        self.title = "🎙●"
        self.menu["Connect"].title = "Disconnect"
        self.menu["Not connected"].title = f"Streaming → {self.pc_ip}"

    def _stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.streaming = False
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
