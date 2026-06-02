#!/usr/bin/env python3
"""
PC side — receives mic audio from Mac and plays to VB-Cable (virtual mic).
Usage: python receiver.py
Requires VB-Cable: https://vb-audio.com/Cable/
"""

import socket
import numpy as np
import sounddevice as sd

PORT = 9876
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 480  # must match sender
BUFFER_PACKETS = 3  # small buffer to smooth jitter

def find_vbcable():
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if 'cable' in d['name'].lower() and d['max_output_channels'] > 0:
            return i, d['name']
    return None, None

device_index, device_name = find_vbcable()
if device_index is None:
    print("VB-Cable not found. Install from https://vb-audio.com/Cable/")
    print("\nAvailable output devices:")
    for i, d in enumerate(sd.query_devices()):
        if d['max_output_channels'] > 0:
            print(f"  [{i}] {d['name']}")
    device_index = int(input("\nEnter device index to use: "))
    device_name = sd.query_devices(device_index)['name']

print(f"Output device: [{device_index}] {device_name}")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', PORT))
sock.setblocking(False)

buf = []

def callback(outdata, frames, time, status):
    if buf:
        outdata[:, 0] = buf.pop(0)
    else:
        outdata.fill(0)

print(f"Listening on port {PORT} — press Ctrl+C to stop")
with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                     blocksize=CHUNK, device=device_index, callback=callback):
    try:
        while True:
            try:
                data, _ = sock.recvfrom(CHUNK * 2)
                pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767
                buf.append(pcm)
                # keep buffer bounded
                while len(buf) > BUFFER_PACKETS * 2:
                    buf.pop(0)
            except BlockingIOError:
                sd.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
