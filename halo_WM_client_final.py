import numpy as np
import time
import sys
import zmq
from scipy.signal import butter, sosfilt

# --- 0. CONFIGURATION ---
ANALYZED_CHANELS = ['O1', 'O2'] # Channels where we look for blinks
WINDOW_TIME = 5.0      
SFREQ = 250

# Detection threshold (for derivative in Volts)
DERIV_THRESH = 20000.0  

# --- GLOBAL VARIABLES ---
N_CH_INPUT = len(ANALYZED_CHANELS) 
BUFFER_SIZE = int(SFREQ * WINDOW_TIME)

# Data buffer (Volts)
eeg_buffer = np.zeros((N_CH_INPUT, BUFFER_SIZE)) 

# Filters
sos_high = butter(2, 0.3, btype='highpass', fs=SFREQ, output='sos')
sos_low = butter(2, 20.0, btype='lowpass', fs=SFREQ, output='sos')

def run_blink_detector():
    global eeg_buffer

    # --- 1. ZMQ CONFIGURATION ---
    context = zmq.Context()

    # RECEIVER (Data from Router - port 6000)
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect("tcp://localhost:6000") 
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") 
    # No CONFLATE, because we need continuity for filters!

    # TRANSMITTER (Decisions to Core Unit - port 5555)
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind("tcp://*:5555")

    print(">>> BLINKER MODULE: Start. Listening on 6000, transmitting on 5555")

    try:
        while True:
            # --- 2. DATA RECEPTION ---
            try:
                packets = []
                # Retrieve everything waiting in the queue (empty the network buffer)
                while True:
                    packet = sub_socket.recv_pyobj(flags=zmq.NOBLOCK)
                    packets.append(packet)
                    # Safety limit
                    if len(packets) > 10: break 
            except zmq.Again:
                pass # No more data at the moment

            # If there is no new data, short nap and next iteration
            if not packets:
                time.sleep(0.01)
                continue

            # --- 3. PACKET PROCESSING ---
            chunks_to_process = []
            
            for pkt in packets:
                full_data_uv = pkt["data"]      # Data in uV
                offset = pkt["dc_offset"]       # Offset
                channel_names = pkt["channels"]
                
                # Conversion to Volts (V) - according to your threshold 20000.0 for V/s
                # (If you prefer uV, remove /1e6 and adjust the threshold)
                full_data_v = full_data_uv / 1e6
                offset_v = offset / 1e6
                
                # Remove offset locally
                clean_v = full_data_v - offset_v
                
                # Select channels
                indices = [channel_names.index(ch) for ch in ANALYZED_CHANELS]
                my_chunk = clean_v[indices, :]
                chunks_to_process.append(my_chunk)

            # Concatenate new data
            new_block = np.concatenate(chunks_to_process, axis=1)
            chunk_len = new_block.shape[1]

            # Buffer update (rolling)
            eeg_buffer = np.roll(eeg_buffer, -chunk_len, axis=1)
            eeg_buffer[:, -chunk_len:] = new_block

            # --- 4. SIGNAL ANALYSIS ---
            
            # Subtract local DC (window mean)
            dc_offset_local = np.mean(eeg_buffer, axis=1, keepdims=True)
            data_centered = eeg_buffer - dc_offset_local
            
            # Filtering
            clean_o1 = sosfilt(sos_low, sosfilt(sos_high, data_centered[0]))
            
            # Derivative calculation (rate of change)
            deriv_trace_o1 = np.diff(clean_o1, prepend=clean_o1[0]) * SFREQ
            
            # Detection only on the NEW fragment (to avoid detecting the same blink repeatedly)
            # Checking e.g. the last 0.1s or the length of the new batch
            check_len = max(chunk_len, int(SFREQ * 0.1))
            last_deriv_segment = deriv_trace_o1[-check_len:]
            
            max_deriv = np.max(np.abs(last_deriv_segment))
            
            status_do_wyslania = 0

            # --- 5. DECISION LOGIC ---
            if max_deriv > DERIV_THRESH:
                print(f">>> BLINK DETECTED! (d/dt: {max_deriv:.2f})")
                status_do_wyslania = 1
            
            # Logging in one line (overwriting)
            sys.stdout.write(f"\rMax d/dt: {max_deriv:.2f} | Status: {status_do_wyslania}   ")
            sys.stdout.flush()

            # --- 6. SENDING RESULT TO CORE UNIT ---
            # Sending {"blink": 1} or {"blink": 0}
            pub_socket.send_json({"blink": status_do_wyslania})

            # Short sleep to unload CPU (while True loop without GUI is very fast)
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nBLINKER: Stop.")

if __name__ == '__main__': 
    run_blink_detector()
