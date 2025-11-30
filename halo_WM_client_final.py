import numpy as np
import time
import sys
import zmq
from scipy.signal import butter, sosfilt

# --- 0. CONFIGURATION ---
ANALYSIS_CHANNELS = ['O1', 'O2']  # Channels used for blink detection
WINDOW_TIME = 5.0                 # Buffer duration in seconds
SFREQ = 250                       # Sampling frequency

# Derivative threshold (Volts/s) for blink detection
DERIVATIVE_THRESHOLD = 20000.0  

# --- GLOBAL VARIABLES ---
N_CH_INPUT = len(ANALYSIS_CHANNELS) 
BUFFER_SIZE = int(SFREQ * WINDOW_TIME)

# Data buffer (Volts)
eeg_buffer = np.zeros((N_CH_INPUT, BUFFER_SIZE)) 

# Signal Filters
sos_high = butter(2, 0.3, btype='highpass', fs=SFREQ, output='sos')
sos_low = butter(2, 20.0, btype='lowpass', fs=SFREQ, output='sos')

def run_blink_detector():
    """
    Reads raw EEG data from ZMQ Relay, filters it, calculates the derivative,
    and detects blinks based on a threshold. Sends result to Core Unit.
    """
    global eeg_buffer

    # --- 1. ZMQ SETUP ---
    context = zmq.Context()

    # SUBSCRIBER: Receive raw data from Relay (Port 6000)
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect("tcp://localhost:6000") 
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "") 
    # Note: No CONFLATE here, we need continuous data for filtering

    # PUBLISHER: Send detection result to Core Unit (Port 5555)
    pub_socket = context.socket(zmq.PUB)
    pub_socket.bind("tcp://*:5555")

    print(f"--- BLINK DETECTOR STARTED ---")
    print(f"Listening on port 6000 (Relay)...")
    print(f"Sending to port 5555 (Core Unit)...")
    print(f"Threshold: {DERIVATIVE_THRESHOLD}")

    while True:
        try:
            # --- 2. RECEIVE DATA ---
            # Receive raw chunk: dictionary {'Fp1': [val], 'O1': [val]...}
            data_chunk = sub_socket.recv_json()
            
            # Extract only required channels (O1, O2)
            new_samples = []
            for ch_name in ANALYSIS_CHANNELS:
                val = data_chunk.get(ch_name)
                # Ensure it's a list (BrainAccess usually sends single sample per packet here)
                if isinstance(val, (float, int)):
                    val = [val]
                new_samples.append(val)
            
            new_samples = np.array(new_samples) # Shape: (n_channels, n_samples)
            chunk_len = new_samples.shape[1]

            # --- 3. UPDATE RING BUFFER ---
            # Shift buffer left
            eeg_buffer[:, :-chunk_len] = eeg_buffer[:, chunk_len:]
            # Insert new data at the end
            eeg_buffer[:, -chunk_len:] = new_samples
            
            # --- 4. SIGNAL PROCESSING ---
            # Remove DC offset (baseline correction)
            dc_offset_local = np.mean(eeg_buffer, axis=1, keepdims=True)
            data_centered = eeg_buffer - dc_offset_local
            
            # Apply Bandpass Filter (0.3 - 20 Hz)
            # Processing Channel 0 (O1) primarily
            clean_signal = sosfilt(sos_low, sosfilt(sos_high, data_centered[0]))
            
            # Calculate Derivative (Rate of change)
            derivative_trace = np.diff(clean_signal, prepend=clean_signal[0]) * SFREQ
            
            # Analyze only the newest segment to avoid re-detecting old blinks
            check_len = max(chunk_len, int(SFREQ * 0.1))
            last_deriv_segment = derivative_trace[-check_len:]
            
            max_deriv = np.max(np.abs(last_deriv_segment))
            
            status_to_send = 0

            # --- 5. DECISION LOGIC ---
            if max_deriv > DERIVATIVE_THRESHOLD:
                print(f">>> BLINK DETECTED! (d/dt: {max_deriv:.2f})")
                status_to_send = 1
            
            # Live logging (overwrite line)
            sys.stdout.write(f"\rMax d/dt: {max_deriv:.2f} | Status: {status_to_send}   ")
            sys.stdout.flush()

            # --- 6. SEND RESULT TO CORE UNIT ---
            msg = {"blink": status_to_send}
            pub_socket.send_json(msg)

        except KeyboardInterrupt:
            print("\nBlink Detector stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(0.01)

if __name__ == '__main__':
    run_blink_detector()