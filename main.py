import time
import rtmidi

def main():
    midiin = rtmidi.RtMidiIn()

    # Check for available ports
    ports = range(midiin.getPortCount())
    if ports:
        for i in ports:
            print(f"\nAvailable port:{midiin.getPortName(i)}")
    else:
        print('NO MIDI INPUT PORTS!')

    port_index = 0
    midiin.openPort(port_index)
    print(f"\nListening for MIDI input on: {port_index}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            midi = midiin.getMessage(250)

            if midi:
                if midi.isNoteOn():
                    print('ON: ', midi.getMidiNoteName(midi.getNoteNumber()), midi.getVelocity())
                elif midi.isNoteOff():
                    do_nothing = None
                    #print('OFF:', midi.getMidiNoteName(midi.getNoteNumber()))
                elif midi.isController():
                    print('CONTROLLER', midi.getControllerNumber(), midi.getControllerValue())

            # Small sleep to prevent high CPU usage
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        midiin.closePort()
        del midiin


if __name__ == "__main__":
    main()