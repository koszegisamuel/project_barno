import time
import rtmidi
import os
import sys
import ctypes


def load_fluidsynth():
    global current_dir
    # --- PORTABLE DLL LOADING ---
    # Get the absolute path to your 'bin/fluidsynth' folder
    current_dir = os.path.dirname(os.path.abspath(__file__))
    fluidsynth_bin_path = os.path.join(current_dir, 'bin', 'fluidsynth')

    if sys.platform == 'win32':
        if os.path.exists(fluidsynth_bin_path):
            # A. For Python 3.8+ (New way)
            os.add_dll_directory(fluidsynth_bin_path)

            # B. For the find_library function (The "Old" but necessary way)
            # This adds your bin folder to the front of the PATH just for this session
            os.environ['PATH'] = fluidsynth_bin_path + os.path.pathsep + os.environ['PATH']

            # C. Verify the DLL name
            # Some pyfluidsynth versions look for 'libfluidsynth-3', some for 'fluidsynth'
            # If your file is named libfluidsynth-3.dll, we can help pyfluidsynth find it:
            try:
                ctypes.CDLL(os.path.join(fluidsynth_bin_path, 'libfluidsynth-3.dll'))
                print("Verified: libfluidsynth-3.dll is loadable.")
            except Exception as e:
                print(f"Manual check failed: {e}")
        else:
            print(f"Error: Folder not found at {fluidsynth_bin_path}")

    # 2. Now import - pyfluidsynth should now find it via the modified PATH
    try:
        import fluidsynth

        print("Success: fluidsynth imported!")
    except ImportError as e:
        print("\n--- IMPORT ERROR ---")
        print(e)
        print("\nTroubleshooting hint: Check if your 'bin/fluidsynth' folder")
        print("contains 'libfluidsynth-3.dll'. If it's named 'libfluidsynth.dll',")
        print("rename it or create a copy named 'libfluidsynth-3.dll'.")
        sys.exit(1)
    return fluidsynth





def main():
    midiin = rtmidi.RtMidiIn()

    # Check for available ports
    ports = range(midiin.getPortCount())
    if ports:
        for i in ports:
            print(f"\nAvailable port: {midiin.getPortName(i)}")
    else:
        print('NO MIDI INPUT PORTS!')

    port_index = 0
    midiin.openPort(port_index)
    print(f"\nListening for MIDI input on: {port_index}")
    print("Press Ctrl+C to stop.\n")

    fluidsynth = load_fluidsynth()

    # --- INITIALIZE SYNTH ---
    fs = fluidsynth.Synth()
    fs.setting('midi.driver', 'none')
    fs.setting('audio.period-size', 128)
    fs.setting('audio.periods', 2)
    fs.setting('synth.sample-rate', 44100.0)
    fs.start(driver='wasapi')

    # Update this path to your portable soundfont location
    sf_path = os.path.join(current_dir, 'soundfonts', 'FluidR3_GM.sf2')
    sf_id = fs.sfload(sf_path)
    fs.program_select(0, sf_id, 0, 0)

    try:
        while True:
            midi = midiin.getMessage()
            if midi:
                note_num = midi.getNoteNumber()
                velocity = midi.getVelocity()

                if midi.isNoteOn():
                    fs.noteon(0, note_num, velocity)
                    print(f'ON: {midi.getMidiNoteName(note_num)}')

                elif midi.isNoteOff():
                    fs.noteoff(0, note_num)

                elif midi.isController() and midi.getControllerNumber() == 64:
                    fs.cc(0, 64, midi.getControllerValue())

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        midiin.closePort()
        del midiin
        fs.delete()


if __name__ == "__main__":
    main()