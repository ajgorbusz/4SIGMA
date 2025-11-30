import zmq
import time

# --- CONFIGURATION CONSTANTS ---
READY_TIME = 3.0
REST_TIME = 2.0

# Protocol Flags
FLAGS = {"BLI": 0, "RDY": 1, "RST": 2}
# System States
STATES = {"BLINK_WAIT": 0, "WAIT": 1, "MOVE_WAIT": 2, "REST": 3}

def core_unit():
    """
    Main state machine managing the flow between blink detection,
    waiting periods, and movement command execution.
    """
    # Initialize ZMQ Context
    context = zmq.Context()
    print("Core unit initializing...")

    # --- SOCKET SETUP ---
    
    # Subscriber: Receives blink signals
    blinker_sub = context.socket(zmq.SUB)
    blinker_sub.connect("tcp://localhost:5555")
    blinker_sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # Subscriber: Receives movement signals (jaw/head)
    mover_sub = context.socket(zmq.SUB)
    mover_sub.connect("tcp://localhost:5556")
    mover_sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # Publisher: Sends status flags to visual feedback (lamp)
    lamp_pub = context.socket(zmq.PUB)
    lamp_pub.bind("tcp://*:5557")

    # Publisher: Sends final commands to the presentation player
    presentation_pub = context.socket(zmq.PUB)
    presentation_pub.bind("tcp://*:5558")

    # Conflate: Keep only the latest message to avoid lag
    blinker_sub.setsockopt(zmq.CONFLATE, 1)
    mover_sub.setsockopt(zmq.CONFLATE, 1)

    print("Waiting for signals...")

    current_wait_time = 0.0
    wait_begin_time = 0.0

    # Initial state
    current_state = STATES["BLINK_WAIT"]
    lamp_flag = FLAGS["BLI"]

    while True:
        try:
            match current_state:
                # STATE 0: Waiting for a blink trigger
                case 0:
                    msg_blink = blinker_sub.recv_json()
                    blink_status = msg_blink.get("blink", 0)

                    if blink_status == 1:
                        # Blink detected -> Transition to WAIT state
                        lamp_flag = FLAGS["BLI"]
                        msg = {"flag": lamp_flag}
                        lamp_pub.send_json(msg)
                        
                        current_state = STATES["WAIT"]
                        wait_begin_time = time.time()
                        print("BLINK DETECTED")

                # STATE 1: Cooldown/Preparation period after blink
                case 1:
                    current_wait_time = time.time() - wait_begin_time
                    # print("WAITING...") # Debug
                    
                    if current_wait_time >= READY_TIME:
                        # Ready time elapsed -> Enable movement detection
                        lamp_flag = FLAGS["RDY"]
                        msg = {"flag": lamp_flag}
                        lamp_pub.send_json(msg)
                        
                        current_state = STATES["MOVE_WAIT"]

                # STATE 2: Waiting for movement (Jaw/Head) command
                case 2:
                    msg_move = mover_sub.recv_json()
                    move_signal = msg_move.get("move", 0)

                    # 1 = Next Slide, -1 = Previous Slide
                    if move_signal == 1 or move_signal == -1:
                        # Command received -> Forward to player and REST
                        msg = {"move": move_signal}
                        presentation_pub.send_json(msg)
                        
                        current_state = STATES["REST"]
                        wait_begin_time = time.time()
                        print(f"COMMAND EXECUTED: {move_signal}")

                # STATE 3: Rest period after command execution
                case 3:
                    current_wait_time = time.time() - wait_begin_time
                    # print("RESTING...") # Debug
                    
                    if current_wait_time >= REST_TIME:
                        # Rest time elapsed -> Reset to Blink Wait
                        lamp_flag = FLAGS["RST"]
                        msg = {"flag": lamp_flag}
                        lamp_pub.send_json(msg)
                        
                        current_state = STATES["BLINK_WAIT"]

        except KeyboardInterrupt:
            print("Core unit stopping...")
            break

if __name__ == '__main__':
    core_unit()