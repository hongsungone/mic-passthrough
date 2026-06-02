import socket
import numpy as np
import sounddevice as sd

PORT = 9876
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 480


def run(pc_ip: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def callback(indata, frames, time, status):
        if status:
            print(status)
        pcm = (indata[:, 0] * 32767).astype(np.int16)
        sock.sendto(pcm.tobytes(), (pc_ip, PORT))

    print(f"Streaming mic → {pc_ip}:{PORT}  (Ctrl+C to stop)")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                        blocksize=CHUNK, callback=callback):
        try:
            while True:
                sd.sleep(1000)
        except KeyboardInterrupt:
            print("\nStopped.")
