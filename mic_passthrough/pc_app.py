"""
PC system tray app — right-click to start/stop and pick which IP to listen on.
Requires: pip install pystray pillow sounddevice numpy psutil
Requires: VB-Cable installed (https://vb-audio.com/Cable/)
"""

import socket
import threading
import tkinter as tk
from tkinter import messagebox
import numpy as np
import sounddevice as sd
from PIL import Image, ImageDraw
import pystray
import psutil
from mic_passthrough.discovery import PCResponder

PORT = 9876
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 480
BUFFER_MAX = 6


def get_local_ips():
    ips = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ips.append((name, addr.address))
    return ips if ips else [("Unknown", "127.0.0.1")]


def find_vbcable():
    for i, d in enumerate(sd.query_devices()):
        if 'cable input' in d['name'].lower() and d['max_output_channels'] > 0:
            return i, d['name'], int(d['default_samplerate'])
    return None, None, 44100


def make_icon(color):
    img = Image.new('RGB', (64, 64), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([22, 8, 42, 38], radius=10, fill=color)
    draw.line([32, 38, 32, 52], fill=color, width=3)
    draw.line([22, 52, 42, 52], fill=color, width=3)
    return img


class TrayApp:
    def __init__(self):
        self.receiving = False
        self.sock = None
        self.stream = None
        self.buf = []
        self.thread = None
        self.local_ips = get_local_ips()
        self.selected_ip = self.local_ips[0][1]  # default to first IP
        self.device_index, self.device_name, self.sample_rate = find_vbcable()
        self.responder = PCResponder(lambda: self.selected_ip)
        self.responder.start()  # always listening for pings
        self.icon = pystray.Icon(
            "MicPassthrough",
            make_icon("gray"),
            "Mic Passthrough",
            menu=pystray.Menu(self._build_menu)
        )

    def _build_menu(self):
        items = [pystray.MenuItem("Listen on:", None, enabled=False)]

        for name, ip in self.local_ips:
            label = f"  {'✓' if ip == self.selected_ip else '  '} {name}: {ip}"
            items.append(pystray.MenuItem(
                label,
                self._make_ip_selector(ip),
                enabled=not self.receiving,
            ))

        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: f"Input: {self.device_name or 'VB-Cable not found'}",
                None, enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Stop Listening" if self.receiving else "Start Listening",
                self.toggle
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        ]
        return items

    def _make_ip_selector(self, ip):
        def select(icon, item):
            self.selected_ip = ip
            self.icon.update_menu()
        return select

    def toggle(self, icon, item):
        if self.receiving:
            self._stop()
        else:
            self._start()

    def _start(self):
        if self.device_index is None:
            self._notify("VB-Cable not found. Install from vb-audio.com/Cable/")
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.selected_ip, PORT))
        self.sock.setblocking(False)
        self.buf = []

        out_channels = 2  # stereo

        def audio_callback(outdata, frames, time, status):
            mono = self.buf.pop(0) if self.buf else np.zeros(CHUNK, dtype=np.float32)
            for ch in range(out_channels):
                outdata[:, ch] = mono  # broadcast mono to all channels

        self.stream = sd.OutputStream(
            samplerate=self.sample_rate, channels=out_channels, dtype='float32',
            blocksize=CHUNK, device=self.device_index, callback=audio_callback
        )
        self.stream.start()
        self.receiving = True
        self.icon.icon = make_icon("lime")
        self.icon.title = f"Mic Passthrough — Listening on {self.selected_ip}"
        self.icon.update_menu()

        def recv_loop():
            while self.receiving:
                try:
                    data, _ = self.sock.recvfrom(CHUNK * 2)
                    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767
                    self.buf.append(pcm)
                    while len(self.buf) > BUFFER_MAX:
                        self.buf.pop(0)
                except BlockingIOError:
                    pass
                except Exception:
                    break

        self.thread = threading.Thread(target=recv_loop, daemon=True)
        self.thread.start()

    def _stop(self):
        self.receiving = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.sock:
            self.sock.close()
            self.sock = None
        self.icon.icon = make_icon("gray")
        self.icon.title = "Mic Passthrough — Stopped"
        self.icon.update_menu()

    def _notify(self, msg):
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("Mic Passthrough", msg)
        root.destroy()

    def quit(self, icon, item):
        self._stop()
        icon.stop()

    def run(self):
        self.icon.run()


def main():
    TrayApp().run()


if __name__ == "__main__":
    main()
