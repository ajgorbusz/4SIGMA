import multiprocessing as mp
import time
import sys

# Importing modules with English names
import blink_detector as bd
import led_controller as lc
import move_detector as md
import slide_controller as sc
import core_unit as cu

def run_process_wrapper(target_func, process_name):
    """
    Wrapper to run a module process with error handling.
    """
    try:
        print(f"[{process_name}] Starting...")
        target_func()
    except KeyboardInterrupt:
        print(f"[{process_name}] Stopped (Ctrl+C).")
    except Exception as e:
        print(f"[{process_name}] CRITICAL ERROR: {e}")

if __name__ == '__main__':
    # Using multiprocessing to avoid conflicts between Qt (in move_detector) 
    # and Tkinter (in led_controller).
    # Each module gets its own isolated system process.

    processes = []

    # Process definitions
    
    # 1. CORE UNIT - System Brain (must start to allow others to connect)
    p_core = mp.Process(target=run_process_wrapper, args=(cu.run_core_unit, "CORE"))
    processes.append(p_core)

    # 2. MOVE DETECTOR (MASTER) - Handles Hardware and Relay
    # This process connects to the headset and streams data via ZMQ.
    p_move = mp.Process(target=run_process_wrapper, args=(md.run_move_detector, "MOVE_DETECT"))
    processes.append(p_move)

    # 3. BLINK DETECTOR - Analyzes signals for blinks
    p_blink = mp.Process(target=run_process_wrapper, args=(bd.run_blink_detector, "BLINK_DETECT"))
    processes.append(p_blink)

    # 4. SLIDE CONTROLLER - Simulates keyboard presses
    p_slide = mp.Process(target=run_process_wrapper, args=(sc.run_slide_controller, "SLIDE_CTRL"))
    processes.append(p_slide)

    # 5. LED CONTROLLER - Visual Feedback (GUI)
    p_led = mp.Process(target=run_process_wrapper, args=(lc.run_led_controller, "LED_GUI"))
    processes.append(p_led)

    print(">>> SYSTEM START: Initializing Interface...")

    # --- START SEQUENCE ---
    
    # Step 1: Central Logic
    p_core.start()
    time.sleep(0.5) 

    # Step 2: Hardware and Plots (Takes time to connect to headband)
    p_move.start()
    # Give it 2.5 seconds to establish connection and setup ZMQ router
    time.sleep(2.5) 

    # Step 3: Analytical and Actuator modules
    p_blink.start()
    p_slide.start()
    time.sleep(0.5)

    # Step 4: User Interface (Always on top)
    p_led.start()

    print("\n>>> ALL SYSTEMS OPERATIONAL.")
    print(">>> Press Ctrl+C in this terminal to shut down everything.\n")

    try:
        # Main loader loop - monitors process status
        while True:
            time.sleep(1)
            # If the Master process (Hardware) dies, we shut down everything
            if not p_move.is_alive():
                 print("!!! ERROR: Master Process (Move/Hardware) closed. Shutting down system...")
                 break
            
            if not p_core.is_alive():
                 print("!!! ERROR: Core Unit closed. Shutting down...")
                 break

    except KeyboardInterrupt:
        print("\n>>> SHUTDOWN SEQUENCE INITIATED...")
    
    # Graceful termination
    for p in processes:
        if p.is_alive():
            p.terminate()
            p.join()
    
    print(">>> System Halted.")