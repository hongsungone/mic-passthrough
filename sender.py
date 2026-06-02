#!/usr/bin/env python3
"""
Mac side — captures mic and streams audio to PC via UDP.
Usage: python sender.py <PC_IP>
"""

import socket
import sys
import numpy as np
import sounddevice as sd

PC_IP = sys.argv[1] if len(sys.argv) > 1 else input("Enter PC IP address: ").strip()
PORT = 9876
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 480  # 10ms at 48kHz

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def callback(indata, frames, time, status):
    if status:
        print(status)
    pcm = (indata[:, 0] * 32767).astype(np.int16)
    sock.sendto(pcm.tobytes(), (PC_IP, PORT))

print(f"Streaming mic to {PC_IP}:{PORT} — press Ctrl+C to stop")
with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                    blocksize=CHUNK, callback=callback):
    try:
        while True:
            sd.sleep(1000)
    except KeyboardInterrupt:
        print("\nStopped.")
