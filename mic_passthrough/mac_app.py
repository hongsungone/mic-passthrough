"""
Mac menu bar app — click the mic icon to connect/disconnect.
Requires: pip install rumps psutil
"""

import socket
import threading
import time
import ctypes
import ctypes.util
import rumps
import numpy as np
import sounddevice as sd
from mic_passthrough.discovery import PCDiscovery

PORT = 9876
HEARTBEAT_PORT = 9878
HEARTBEAT_TIMEOUT = 3
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


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [('mSelector', ctypes.c_uint32),
                 ('mScope',    ctypes.c_uint32),
                 ('mElement',  ctypes.c_uint32)]


def _ca():
    return ctypes.CDLL(ctypes.util.find_library('CoreAudio'))


def get_default_input_device_id():
    try:
        ca = _ca()
        addr = AudioObjectPropertyAddress(
            mSelector=0x64496e20,  # 'dIn ' kAudioHardwarePropertyDefaultInputDevice
            mScope=0x676c6f62,     # 'glob'
            mElement=0,
        )
        device_id = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(device_id))
        ret = ca.AudioObjectGetPropertyData(
            ctypes.c_uint32(1), ctypes.byref(addr),
            ctypes.c_uint32(0), None,
            ctypes.byref(size), ctypes.byref(device_id)
        )
        return device_id.value if ret == 0 else None
    except Exception:
        return None


def set_default_input_device_id(device_id):
    try:
        ca = _ca()
        addr = AudioObjectPropertyAddress(
            mSelector=0x64496e20,
            mScope=0x676c6f62,
            mElement=0,
        )
        val = ctypes.c_uint32(device_id)
        ca.AudioObjectSetPropertyData(
            ctypes.c_uint32(1), ctypes.byref(addr),
            ctypes.c_uint32(0), None,
            ctypes.c_uint32(ctypes.sizeof(val)), ctypes.byref(val)
        )
    except Exception:
        pass


def get_input_devices():
    """Return list of (device_index, coreaudio_id, name) for all input devices."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0:
            devices.append((i, d['name']))
    return devices


class MicPassthroughApp(rumps.App):
    def __init__(self):
        super().__init__("🎙", quit_button=None)
        self.pc_ip = None
        self.streaming = False
        self.stream = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_heartbeat = 0
        self.gain = 1.0
        self.selected_device_index = None  # None = system default
        self.discovered = {}
        self.local_ips = get_local_ips()

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

        gain_items = []
        for label, val in [("1x (normal)", 1.0), ("1.5x", 1.5), ("2x", 2.0), ("3x", 3.0)]:
            item = rumps.MenuItem(label, callback=self._make_gain_selector(val))
            item.state = 1 if val == self.gain else 0
            gain_items.append(item)

        self.input_devices = get_input_devices()
        input_items = self._build_input_items()

        self.menu = (
            [rumps.MenuItem("Not connected", callback=None), None,
             rumps.MenuItem("Broadcast from:", callback=None)]
            + ip_items
            + [None,
               rumps.MenuItem("Input device:", callback=None)]
            + input_items
            + [None,
               rumps.MenuItem("Mic gain:", callback=None)]
            + gain_items
            + [None,
               rumps.MenuItem("Discovered:", callback=None),
               rumps.MenuItem("  Scanning…", callback=None),
               None,
               rumps.MenuItem("Connect", callback=self.connect),
               rumps.MenuItem("Disconnect", callback=self.disconnect),
               rumps.MenuItem("Quit", callback=self.quit_app)]
        )

        self._start_discovery()
        self._start_heartbeat_listener()
        self._start_device_sync()

    def _build_input_items(self):
        current_id = get_default_input_device_id()
        items = []
        for idx, name in self.input_devices:
            item = rumps.MenuItem(name, callback=self._make_input_selector(idx, name))
            # mark whichever device is currently system default
            item.state = 1 if (self.selected_device_index == idx or
                               (self.selected_device_index is None and
                                self._is_default_device(idx, current_id))) else 0
            items.append(item)
        return items

    def _is_default_device(self, sd_index, current_coreaudio_id):
        """Check if a sounddevice index corresponds to the current CoreAudio default."""
        try:
            name = sd.query_devices(sd_index)['name']
            default_name = sd.query_devices(kind='input')['name']
            return name == default_name
        except Exception:
            return False

    def _make_input_selector(self, idx, name):
        def select(_):
            self.selected_device_index = idx
            # set as macOS system default input too
            # find the CoreAudio device ID by matching name
            self._set_system_input_by_sd_index(idx)
            # update checkmarks
            for i, n in self.input_devices:
                if n in self.menu:
                    self.menu[n].state = 1 if i == idx else 0
            # restart stream if active
            if self.streaming:
                self._restart_stream()
        return select

    def _set_system_input_by_sd_index(self, sd_index):
        """Set macOS system default input device to match a sounddevice index."""
        try:
            target_name = sd.query_devices(sd_index)['name']
            # find CoreAudio device ID by enumerating
            ca = _ca()
            addr = AudioObjectPropertyAddress(
                mSelector=0x64657623,  # 'dev#' kAudioHardwarePropertyDevices... use different approach
                mScope=0x676c6f62,
                mElement=0,
            )
            # Simpler: iterate CoreAudio IDs until name matches
            for ca_id in range(1, 200):
                n = self._get_device_name(ca, ca_id)
                if n and target_name in n:
                    set_default_input_device_id(ca_id)
                    break
        except Exception:
            pass

    def _get_device_name(self, ca, device_id):
        try:
            addr = AudioObjectPropertyAddress(
                mSelector=0x6c6e616d,  # 'lnam' kAudioObjectPropertyName
                mScope=0x676c6f62,
                mElement=0,
            )
            # get CFStringRef
            ref = ctypes.c_void_p(0)
            size = ctypes.c_uint32(ctypes.sizeof(ref))
            ret = ca.AudioObjectGetPropertyData(
                ctypes.c_uint32(device_id), ctypes.byref(addr),
                ctypes.c_uint32(0), None,
                ctypes.byref(size), ctypes.byref(ref)
            )
            if ret != 0 or not ref.value:
                return None
            # convert CFString to Python string
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
            buf = ctypes.create_string_buffer(256)
            cf.CFStringGetCString(ref, buf, 256, 0x08000100)  # kCFStringEncodingUTF8
            cf.CFRelease(ref)
            return buf.value.decode('utf-8', errors='ignore')
        except Exception:
            return None

    def _start_device_sync(self):
        """Watch CoreAudio default input and sync menu checkmarks."""
        def watch():
            last_id = get_default_input_device_id()
            while True:
                time.sleep(2)
                current_id = get_default_input_device_id()
                if current_id != last_id:
                    last_id = current_id
                    self.selected_device_index = None  # reset to follow system
                    # update checkmarks to match new system default
                    try:
                        sd._terminate()
                        sd._initialize()
                        default_name = sd.query_devices(kind='input')['name']
                        for i, n in self.input_devices:
                            if n in self.menu:
                                self.menu[n].state = 1 if n == default_name else 0
                    except Exception:
                        pass
                    # restart stream if active
                    if self.streaming:
                        self._restart_stream()
        threading.Thread(target=watch, daemon=True).start()

    def _restart_stream(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        try:
            sd._terminate()
            sd._initialize()
            self.stream = self._open_stream()
        except Exception:
            pass

    def _start_heartbeat_listener(self):
        hb_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        hb_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        hb_sock.bind(('', HEARTBEAT_PORT))
        hb_sock.settimeout(1)

        def listen():
            while True:
                try:
                    data, _ = hb_sock.recvfrom(64)
                    if data == b'HEARTBEAT':
                        self.last_heartbeat = time.time()
                except socket.timeout:
                    pass
                except Exception:
                    break

        def watch():
            while True:
                time.sleep(1)
                if self.streaming and time.time() - self.last_heartbeat > HEARTBEAT_TIMEOUT:
                    self._stop()
                    self.menu["Not connected"].title = "PC stopped listening"

        threading.Thread(target=listen, daemon=True).start()
        threading.Thread(target=watch, daemon=True).start()

    def _make_gain_selector(self, val):
        def select(_):
            self.gain = val
            for label, v in [("1x (normal)", 1.0), ("1.5x", 1.5), ("2x", 2.0), ("3x", 3.0)]:
                if label in self.menu:
                    self.menu[label].state = 1 if v == val else 0
        return select

    def _make_local_selector(self, iface, ip):
        def select(_):
            self.selected_local_ip = ip
            for n, a in self.local_ips:
                title = f"{n} - {a}"
                if title in self.menu:
                    self.menu[title].state = 1 if a == ip else 0
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
                item = rumps.MenuItem(title, callback=None)
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

    def _open_stream(self):
        def callback(indata, frames, t, status):
            if self.streaming and self.pc_ip:
                amplified = np.clip(indata[:, 0] * self.gain, -1.0, 1.0)
                pcm = (amplified * 32767).astype(np.int16)
                self.sock.sendto(pcm.tobytes(), (self.pc_ip, PORT))

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
            blocksize=CHUNK, device=self.selected_device_index, callback=callback
        )
        stream.start()
        return stream

    def _start(self):
        def do_start():
            self.menu["Not connected"].title = "Connecting…"
            try:
                self.stream = self._open_stream()
                self.streaming = True
                self.title = "🎙●"
                self.menu["Not connected"].title = f"Streaming → {self.pc_ip}"
            except Exception as e:
                self.menu["Not connected"].title = f"Error: {e}"

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
