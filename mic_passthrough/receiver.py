import socket
import numpy as np
import sounddevice as sd

PORT = 9876
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK = 480
BUFFER_MAX = 6


def find_vbcable():
    for i, d in enumerate(sd.query_devices()):
        if 'cable' in d['name'].lower() and d['max_output_channels'] > 0:
            return i, d['name']
    return None, None


def pick_device():
    device_index, device_name = find_vbcable()
    if device_index is not None:
        return device_index, device_name

    print("VB-Cable not found. Install from https://vb-audio.com/Cable/\n")
    print("Available output devices:")
    for i, d in enumerate(sd.query_devices()):
        if d['max_output_channels'] > 0:
            print(f"  [{i}] {d['name']}")
    device_index = int(input("\nEnter device index to use: "))
    return device_index, sd.query_devices(device_index)['name']


def run():
    device_index, device_name = pick_device()
    print(f"Output → [{device_index}] {device_name}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', PORT))
    sock.setblocking(False)

    buf = []

    def callback(outdata, frames, time, status):
        outdata[:, 0] = buf.pop(0) if buf else np.zeros(CHUNK, dtype=np.float32)

    print(f"Listening on :{PORT}  (Ctrl+C to stop)")
    with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32',
                         blocksize=CHUNK, device=device_index, callback=callback):
        try:
            while True:
                try:
                    data, _ = sock.recvfrom(CHUNK * 2)
                    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767
                    buf.append(pcm)
                    while len(buf) > BUFFER_MAX:
                        buf.pop(0)
                except BlockingIOError:
                    sd.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
