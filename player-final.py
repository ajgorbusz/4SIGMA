import sys
import time
import zmq
import pyautogui

# Safety fail-safe: moving mouse to a corner aborts the script
pyautogui.FAILSAFE = True

# ZMQ Configuration
ZMQ_HOST = "tcp://localhost:5558"

def run_slide_controller():
    """
    Listens for commands from the Core Unit via ZMQ and controls presentation slides.
    """
    context = zmq.Context()
    socket = context.socket(zmq.SUB)

    # Set receive timeout to 1000ms (1s).
    # This ensures the loop cycles periodically to check for KeyboardInterrupt (Ctrl+C).
    socket.setsockopt(zmq.RCVTIMEO, 1000)

    print(f"--- SLIDE CONTROLLER (ZMQ) ---")
    print(f"Connecting to Core Unit at: {ZMQ_HOST}...")

    try:
        socket.connect(ZMQ_HOST)
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
    except Exception as e:
        print(f"ZMQ Connection Error: {e}")
        sys.exit(1)

    print("-" * 40)
    print("!!! INSTRUCTIONS !!!")
    print("1. Manually open your presentation (PDF/PowerPoint).")
    print("2. Ensure the presentation window is ACTIVE (focused).")
    print("3. You have 5 seconds to switch context.")
    print("-" * 40)

    try:
        for i in range(5, 0, -1):
            print(f"Starting in: {i}...")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nCountdown aborted.")
        sys.exit(0)

    print("\n>>> LISTENING ACTIVE (Ready for signals) <<<")
    print("Press Ctrl+C to stop.")

    while True:
        try:
            # Attempt to receive message with timeout
            try:
                msg = socket.recv_json()
            except zmq.Again:
                # No message received within timeout (1s); loop to check for interrupts
                continue

            move_signal = msg.get("move", 0)

            if move_signal == 1:
                print(f"[RECEIVED] Signal: {move_signal} -> NEXT SLIDE")
                pyautogui.press('right')

            elif move_signal == -1:
                print(f"[RECEIVED] Signal: {move_signal} -> PREVIOUS SLIDE")
                pyautogui.press('left')

        except KeyboardInterrupt:
            print("\nStopping controller...")
            break
        except Exception as e:
            print(f"Error: {e}")
            break

    # Resource cleanup
    socket.close()
    context.term()
    sys.exit(0)

if __name__ == "__main__":
    run_slide_controller()
