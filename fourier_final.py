import numpy as np
import time
import sys
import zmq
from scipy.signal import welch
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import matplotlib

# --- BRAINACCESS IMPORTS ---
from brainaccess.utils import acquisition
from brainaccess.core.eeg_manager import EEGManager

# --- 0. CONFIGURATION ---
matplotlib.use("QtAgg", force=True)

DEVICE_NAME = "BA HALO 057"
SAMPLING_FREQ = 250
CHANNELS_TO_ANALYZE = ['Fp1', 'Fp2'] 

# --- ZMQ CONFIGURATION (PUBLISHING) ---
ZMQ_PORT_DATA_RELAY = 6000      # Raw data relay
ZMQ_PORT_DECISION = 5556        # Decisions to Core Unit

# Relay Config
ALL_CHANNELS_OUT = ["Fp1", "Fp2", "O1", "O2"]
HALO_CHANNELS_MAP = {0: "Fp1", 1: "Fp2", 2: "O1", 3: "O2"}

# Time Windows
ANALYSIS_WINDOW_TIME = 4.0      
FFT_WINDOW = 0.5              

# Thresholds (Teeth vs Head)
HEAD_THRESHOLD_MULTIPLIER = 20.0 
TEETH_THRESHOLD_MULTIPLIER = 3.0 

# Global objects
eeg_manager = EEGManager()
socket_relay = None
socket_decision = None

def run_move_detector():
    """
    Main function setting up hardware, ZMQ, and animation loop.
    """
    global socket_relay, socket_decision, eeg_manager

    # --- ZMQ SETUP ---
    context = zmq.Context()
    socket_relay = context.socket(zmq.PUB)
    socket_relay.bind(f"tcp://*:{ZMQ_PORT_DATA_RELAY}")
    
    socket_decision = context.socket(zmq.PUB)
    socket_decision.bind(f"tcp://*:{ZMQ_PORT_DECISION}")

    # --- HARDWARE CONNECTION ---
    print(f"Connecting to system {DEVICE_NAME}...")
    try:
        eeg_manager.setup(acquisition, device_name=DEVICE_NAME, cap=HALO_CHANNELS_MAP, sfreq=SAMPLING_FREQ)
        eeg_manager.start_acquisition()
        time.sleep(1.0)
        print("Acquisition started.")
    except Exception as e:
        print(f"Hardware Connection Error: {e}")
        return

    # --- PLOT SETUP ---
    fig, ax = plt.subplots(2, 1, figsize=(10, 8))
    
    # Plot 1: Time Series
    line_time, = ax[0].plot([], [], lw=1)
    ax[0].set_title("Raw EEG Signal (Fp1)")
    ax[0].set_xlim(0, ANALYSIS_WINDOW_TIME)
    ax[0].set_ylim(-100, 100)

    # Plot 2: Power/Decision Metric
    line_power, = ax[1].plot([], [], lw=2, color='orange')
    ax[1].set_title("Decision Metric (Power)")
    ax[1].set_xlim(0, ANALYSIS_WINDOW_TIME)
    ax[1].set_ylim(0, 100)

    # Buffers
    buffer_len = int(ANALYSIS_WINDOW_TIME * SAMPLING_FREQ)
    times_buffer = np.linspace(0, ANALYSIS_WINDOW_TIME, buffer_len)
    
    signal_buffer = np.zeros(buffer_len)
    power_buffer = np.zeros(buffer_len)

    def update_plot(frame):
        nonlocal signal_buffer, power_buffer
        
        # 1. Get Data chunk
        data = eeg_manager.get_data()
        if data is None or data.shape[1] == 0:
            return [line_time, line_power]

        # 2. RELAY RAW DATA (To Blink Detector)
        try:
            msg = {"data": data.tolist()}
            socket_relay.send_json(msg)
        except Exception:
            pass

        # 3. ANALYSIS (Fp1 only)
        new_samples = data.shape[1]
        fp1_data = data[0, :] 

        # Update Signal Buffer
        signal_buffer = np.roll(signal_buffer, -new_samples)
        signal_buffer[-new_samples:] = fp1_data

        # 4. FFT / WELCH
        # Analyze last 0.5s
        n_analyze = int(0.5 * SAMPLING_FREQ)
        segment = signal_buffer[-n_analyze:]
        
        freqs, psd = welch(segment, fs=SAMPLING_FREQ, nperseg=n_analyze//2)
        
        # Bands
        idx_low = np.logical_and(freqs >= 1, freqs <= 4)   # Movement
        idx_high = np.logical_and(freqs >= 20, freqs <= 80) # Muscle (EMG)
        
        power_low = np.mean(psd[idx_low]) if np.any(idx_low) else 0
        power_high = np.mean(psd[idx_high]) if np.any(idx_high) else 0
        
        move_signal = 0
        score = power_high
        
        power_buffer = np.roll(power_buffer, -new_samples)
        power_buffer[-new_samples:] = score

        # THRESHOLDS
        # Simple logic: High power = clench, unless low power is also huge (head movement)
        if power_high > 50.0: 
             if power_low < power_high: 
                 print(f"Command: NEXT SLIDE (Clench) | Power: {power_high:.1f}")
                 move_signal = 1
        
        # SEND DECISION
        if move_signal != 0:
            socket_decision.send_json({"move": move_signal})

        # GRAPHICS UPDATE
        line_time.set_ydata(signal_buffer)
        line_time.set_xdata(times_buffer)
        ax[0].set_ylim(np.min(signal_buffer), np.max(signal_buffer) + 10)
        
        line_power.set_ydata(power_buffer)
        line_power.set_xdata(times_buffer)
        ax[1].set_ylim(0, np.max(power_buffer) + 10)

        return [line_time, line_power]

    ani = FuncAnimation(fig, update_plot, interval=50, blit=True)
    plt.show()

    # Cleanup
    eeg_manager.stop_acquisition()
    eeg_manager.close()
    context.term()

if __name__ == "__main__":
    run_move_detector()
