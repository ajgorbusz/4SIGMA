import numpy as np
import time
import sys
import zmq
from scipy.signal import butter, sosfilt

# --- 0. CONFIGURATION ---
ANALYZED_CHANNELS = ['O1', 'O2'] # Channels used to detect blinks
WINDOW_TIME = 5.0      
SAMPLING_FREQ = 250

# Detection Threshold (Derivative of Voltage)
DERIVATIVE_THRESHOLD = 20000.0  

# --- GLOBAL VARIABLES ---
NUM_INPUT_CHANNELS = len(ANALYZED_CHANNELS)
BUFFER_SIZE = int(SAMPLING_FREQ * WINDOW_TIME)

# Data Buffer (Volts)
eeg_buffer = np.zeros((NUM_INPUT_CHANNELS, BUFFER_SIZE)) 

# Filters
sos_high = butter(2, 0.3, btype='highpass', fs=SAMPLING_FREQ, output='sos')
sos_low = butter(2, 20.0, btype='lowpass', fs=SAMPLING_FREQ, output='sos')

def run_blink_detector():
    global eeg_buffer

    # --- 1. ZMQ CONFIGURATION ---
    context = zmq.Context()

    # SUBSCRIBER (Data from Router - port 6000)
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect("tcp://localhost:6000") 
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") 
    # No CONFLATE, because we need continuous data for filters!

    # PUBLISHER (Events to Core Unit - port 5555)
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind("tcp://*:5555")

    print(f"--- BLINK DETECTOR STARTED ---")
    print(f"Listening on: 6000, Publishing to: 5555")

    try:
        while True:
            # --- 2. RECEIVE DATA ---
            # Packet format: {"data": [[ch1...], [ch2...]]}
            msg = sub_socket.recv_json()
            
            raw_data = np.array(msg.get("data"))
            # Expecting full packet from Halo (4 channels usually), 
            # we need to extract O1 and O2.
            # Assuming Halo sends [Fp1, Fp2, O1, O2], indices 2 and 3 are Occipital.
            
            if raw_data.shape[0] < 4:
                continue
                
            # Selecting only O1, O2
            new_chunk = raw_data[2:4, :] 
            chunk_len = new_chunk.shape[1]

            # --- 3. UPDATE BUFFER ---
            eeg_buffer = np.roll(eeg_buffer, -chunk_len, axis=1)
            eeg_buffer[:, -chunk_len:] = new_chunk

            # --- 4. SIGNAL PROCESSING ---
            # Remove DC Offset (Centering)
            dc_offset_local = np.mean(eeg_buffer, axis=1, keepdims=True)
            data_centered = eeg_buffer - dc_offset_local
            
            # Filtering (Analyzing Channel 0 of the buffer -> O1)
            clean_o1 = sosfilt(sos_low, sosfilt(sos_high, data_centered[0]))
            
            # Calculate Derivative (Rate of change)
            deriv_trace_o1 = np.diff(clean_o1, prepend=clean_o1[0]) * SAMPLING_FREQ
            
            # Detection only on NEW segment (to avoid re-triggering old blinks)
            check_len = max(chunk_len, int(SAMPLING_FREQ * 0.1))
            last_deriv_segment = deriv_trace_o1[-check_len:]
            
            max_deriv = np.max(np.abs(last_deriv_segment))
            
            status_to_send = 0

            # --- 5. DECISION LOGIC ---
            if max_deriv > DERIVATIVE_THRESHOLD:
                print(f">>> BLINK DETECTED! (d/dt: {max_deriv:.2f})")
                status_to_send = 1
            
            # Inline logging (overwriting line)
            sys.stdout.write(f"\rMax d/dt: {max_deriv:.2f} | Status: {status_to_send}   ")
            sys.stdout.flush()

            # --- 6. SEND RESULT TO CORE UNIT ---
            if status_to_send == 1:
                pub_socket.send_json({"blink": 1})

    except KeyboardInterrupt:
        print("\nBlink Detector stopped.")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        context.term()

if __name__ == "__main__":
    run_blink_detector()
