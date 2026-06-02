import platform

def main():
    os = platform.system()

    if os == 'Darwin':
        from mic_passthrough.mac_app import main as run
        run()
    elif os == 'Windows':
        from mic_passthrough.pc_app import main as run
        run()
    else:
        print(f"Unsupported platform: {os}")

if __name__ == '__main__':
    main()
