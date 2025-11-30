import zmq
import time

# --- CONFIGURATION ---
READY_TIME = 3.0
REST_TIME = 2.0

# Communication Flags
FLAGS = {
    "BLINK_WAIT": 0, 
    "READY": 1, 
    "REST": 2
}

# State Machine States
STATES = {
    "WAIT_FOR_BLINK": 0, 
    "PREPARE_TO_LISTEN": 1, 
    "WAIT_FOR_MOVE": 2, 
    "RESTING": 3
}

def run_core_unit():
    # Defining sockets
    context = zmq.Context()
    print("Core Unit: Initializing...")

    # --- 1. SIGNAL RECEPTION (Subscribers) ---
    blink_sub = context.socket(zmq.SUB)
    blink_sub.connect("tcp://localhost:5555")
    blink_sub.setsockopt_string(zmq.SUBSCRIBE, "")

    move_sub = context.socket(zmq.SUB)
    move_sub.connect("tcp://localhost:5556")
    move_sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # --- 2. STATE BROADCASTING (Publishers) ---
    led_pub = context.socket(zmq.PUB)
    led_pub.bind("tcp://*:5557")

    slide_pub = context.socket(zmq.PUB)
    slide_pub.bind("tcp://*:5558")

    # Keep only the last message to avoid processing history
    blink_sub.setsockopt(zmq.CONFLATE, 1)
    move_sub.setsockopt(zmq.CONFLATE, 1)

    print("Core Unit: Waiting for signals...")

    wait_start_time = 0.0
    state = STATES["WAIT_FOR_BLINK"]
    led_flag = FLAGS["BLINK_WAIT"]

    # Initial LED update
    time.sleep(0.5)
    led_pub.send_json({"flag": led_flag})
    
    # Logic variables
    move_armed = False 
    
    try:
        while True:
            time.sleep(0.01) # CPU Saver

            # State Machine
            match state:
                # --- STATE 0: WAIT FOR BLINK (Trigger) ---
                case 0: # WAIT_FOR_BLINK
                    try:
                        # Non-blocking receive
                        msg = blink_sub.recv_json(flags=zmq.NOBLOCK)
                        if msg.get("blink") == 1:
                            print(">>> TRIGGER: Blink Detected!")
                            state = STATES["PREPARE_TO_LISTEN"]
                            wait_start_time = time.time()
                            
                            # Original code logic: transition to PREPARE, LED update happens there
                    except zmq.Again:
                        pass

                # --- STATE 1: PREPARATION (Debounce/Ready) ---
                case 1: # PREPARE_TO_LISTEN
                    current_wait_time = time.time() - wait_start_time
                    if current_wait_time >= READY_TIME:
                        print(">>> SYSTEM READY: Listening for moves.")
                        state = STATES["WAIT_FOR_MOVE"]
                        
                        # Set LED to Green
                        led_flag = FLAGS["READY"]
                        led_pub.send_json({"flag": led_flag})
                        
                        # Enable move detection logic
                        move_armed = True

                # --- STATE 2: LISTEN FOR MOVE (Action) ---
                case 2: # WAIT_FOR_MOVE
                    try:
                        msg = move_sub.recv_json(flags=zmq.NOBLOCK)
                        move_signal = msg.get("move", 0)

                        if not move_armed:
                            # Flush old messages if not armed (safety)
                            pass
                        else:
                            # React only if system is "armed"
                            if move_signal == 1 or move_signal == -1:
                                slide_msg = {"move": move_signal}
                                slide_pub.send_json(slide_msg)
                                
                                state = STATES["RESTING"]
                                wait_start_time = time.time()
                                print(f">>> MOVE EXECUTED: {move_signal}")
                                
                                # Reset for future
                                move_armed = False
                                
                                # Set LED to Orange (Rest)
                                led_flag = FLAGS["REST"]
                                led_pub.send_json({"flag": led_flag})

                    except zmq.Again:
                        pass

                # --- STATE 3: REST (Cooldown) ---
                case 3: # RESTING
                    current_wait_time = time.time() - wait_start_time
                    if current_wait_time >= REST_TIME:
                        # Back to Red LED
                        led_flag = FLAGS["BLINK_WAIT"]
                        led_pub.send_json({"flag": led_flag})
                        
                        state = STATES["WAIT_FOR_BLINK"]
                        print(">>> BACK TO BLINK WATCH")

    except KeyboardInterrupt:
        print("Core Unit shutting down.")
    finally:
        context.term()

if __name__ == '__main__':
    run_core_unit()
