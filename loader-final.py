import multiprocessing as mp
import time
import sys

# Importing your modules
import halo_WM_client_final as bd
import led_controller as lc
# import fourier_final as md
import player2 as pc
import core_unit as cu

def run_module(target_func, name):
    """
    Wrapper for running the module with error handling.
    """
    try:
        print(f"[{name}] Starting...")
        target_func()
    except KeyboardInterrupt:
        print(f"[{name}] Stopped (Ctrl+C).")
    except Exception as e:
        print(f"[{name}] CRITICAL ERROR: {e}")

if __name__ == '__main__':
    # Using multiprocessing to avoid conflict between 
    # Qt GUI (in move_detect) and Tkinter GUI (in led_controller).
    # Each module gets its own independent system process.

    processes = []

    # Process definition (Target points to the main function in each file)
    
    # 1. CORE UNIT - System brain (must wake up so others have somewhere to connect)
    p_core = mp.Process(target=run_module, args=(cu.core_unit, "CORE"))
    processes.append(p_core)

    # 2. MOVE DETECT (MASTER) - Handles hardware and sends data (Relay)
    # This process is the most important because it holds the connection to the band.
    # p_move = mp.Process(target=run_module, args=(md.run, "MOVE_MASTER"))
    # processes.append(p_move)

    # 3. BLINK DETECT - Client analyzing blinks
    p_blink = mp.Process(target=run_module, args=(bd.run_blink_detector, "BLINK"))
    processes.append(p_blink)

    # 4. PRES CTRL - Slide controller (Executor)
    p_pres = mp.Process(target=run_module, args=(pc.run_slide_controller, "PRES_CTRL"))
    processes.append(p_pres)

    # 5. LED CONTROLLER - Visual overlay (GUI)
    p_led = mp.Process(target=run_module, args=(lc.run, "LED_GUI"))
    processes.append(p_led)

    print(">>> SYSTEM START: Jarvis Initialization...")

    # --- STARTUP SEQUENCE ---
    
    # Step 1: Central logic
    p_core.start()
    time.sleep(0.5) 

    # Step 2: Hardware and plots (This will take a moment as it connects to the band)
    # p_move.start()
    # Giving it 2 seconds to establish connection and set up the ZMQ router
    time.sleep(2.5) 

    # Step 3: The rest of analytical and executive modules
    p_blink.start()
    p_pres.start()
    time.sleep(0.5)

    # Step 4: User interface (on top)
    p_led.start()

    print("\n>>> ALL SYSTEMS OPERATIONAL.")
    print(">>> Press Ctrl+C in this console to shut down everything.\n")

    try:
        # Main loader loop - monitors process state
        while True:
            time.sleep(1)
            # If the main hardware process dies, we close everything
            # if not p_move.is_alive():
            #     print("!!! ERROR: Master Process (Move/Hardware) has been closed!")
            #     raise KeyboardInterrupt
            
    except KeyboardInterrupt:
        print("\n\n>>> SHUTTING DOWN SYSTEM...")
        # Sending shutdown signal to all processes
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join() # Waiting for the process to clean up after itself
        
        print(">>> Goodbye.")
        sys.exit(0)
