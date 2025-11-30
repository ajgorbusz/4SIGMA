import numpy as np
import time
import sys
import zmq
from scipy.signal import butter, sosfilt, welch
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import matplotlib
from collections import deque

# --- IMPORTY BRAINACCESS ---
from brainaccess.utils import acquisition
from brainaccess.core.eeg_manager import EEGManager

# --- 0. CONFIGURATION ---
matplotlib.use("QtAgg", force=True)

DEVICE_NAME = "BA HALO 057"
SFREQ = 250
ANALYSIS_CHANNELS = ['Fp1', 'Fp2'] 

# --- ZMQ CONFIGURATION (PUBLISHING) ---
ZMQ_PORT_DATA = 6000      # Port for broadcasting raw data (Relay)
ZMQ_PORT_DECISION = 5556  # Port for sending decisions to Core Unit

# Relay Config
ALL_CHANNELS_OUT = ["Fp1", "Fp2", "O1", "O2"]
HALO_CHANNELS_MAP = {0: "Fp1", 1: "Fp2", 2: "O1", 3: "O2"}

# Time Windows
PLOT_WINDOW_TIME = 4.0      
FFT_WINDOW_TIME = 0.5       # Short window for fast reaction

# Detection Config
CALIBRATION_TIME = 3.0      # Time to gather background noise

# THRESHOLDS (Multipliers relative to background noise)
JAW_LOWER_MULTIPLIER = 1.5    # Minimum power to detect jaw clench (1.5x background)
HEAD_UPPER_MULTIPLIER = 100.0 # If power > 100x background -> Head movement (ignore as jaw)

# Frequency Bands
JAW_BAND = (55, 90)   # High freq for EMG
HEAD_BAND = (1, 5)    # Low freq for EOG/Movement

# --- GLOBAL VARIABLES ---
eeg = acquisition.EEG()
buffer_samples = int(SFREQ * PLOT_WINDOW_TIME)
# Buffers
data_buffer = deque([0]*buffer_samples, maxlen=buffer_samples) # Signal
power_buffer = deque([0]*buffer_samples, maxlen=buffer_samples) # Power history
times_buffer = np.linspace(-PLOT_WINDOW_TIME, 0, buffer_samples)

# Calibration State
background_power_jaw = 1.0
background_power_head = 1.0
is_calibrated = False
calibration_start_time = 0

# --- 1. SIGNAL PROCESSING TOOLS ---
def create_filters(sfreq):
    # Notch filter (50Hz)
    sos_notch = butter(4, [48, 52], btype='bandstop', fs=sfreq, output='sos')
    # Bandpass (1-100Hz)
    sos_band = butter(4, [1, 100], btype='bandpass', fs=sfreq, output='sos')
    return sos_notch, sos_band

sos_notch, sos_band = create_filters(SFREQ)

def get_band_power(data, band, sfreq):
    """Calculates mean power in a specific frequency band using Welch method."""
    nperseg = min(len(data), int(FFT_WINDOW_TIME * sfreq))
    freqs, psd = welch(data, fs=sfreq, nperseg=nperseg)
    
    idx_min = np.searchsorted(freqs, band[0])
    idx_max = np.searchsorted(freqs, band[1])
    
    if idx_max <= idx_min: return 0.0
    return np.mean(psd[idx_min:idx_max])

# --- 2. MAIN LOGIC & ANIMATION ---
def run_fourier_analysis():
    global is_calibrated, calibration_start_time
    global background_power_jaw, background_power_head

    # --- ZMQ SETUP ---
    context = zmq.Context()
    
    # PUB Socket: Raw Data Relay (for blink detector)
    pub_data = context.socket(zmq.PUB)
    pub_data.bind(f"tcp://*:{ZMQ_PORT_DATA}")
    
    # PUB Socket: Decisions (for Core Unit)
    pub_decision = context.socket(zmq.PUB)
    pub_decision.bind(f"tcp://*:{ZMQ_PORT_DECISION}")

    # BrainAccess Acquisition Setup
    mgr = setup_acquisition()
    if not mgr: return

    # --- PLOT SETUP ---
    fig, ax = plt.subplots(2, 1, figsize=(10, 8))
    plt.subplots_adjust(hspace=0.4)
    
    # Plot 1: Filtered Signal
    lines = []
    line1, = ax[0].plot(times_buffer, np.zeros(buffer_samples), color='black', lw=1)
    lines.append(line1)
    ax[0].set_title("Filtered Signal (Fp1/Fp2 Avg)")
    ax[0].set_ylim(-100, 100)

    # Plot 2: Power Ratio (Jaw)
    line2, = ax[1].plot(times_buffer, np.zeros(buffer_samples), color='purple', lw=2)
    lines.append(line2)
    ax[1].set_title("Jaw Band Power Ratio (Normalized)")
    ax[1].set_ylim(0, 10)
    
    # Threshold lines
    line_thresh_low = ax[1].axhline(JAW_LOWER_MULTIPLIER, color='green', linestyle='--', label='Jaw Threshold')
    line_thresh_high = ax[1].axhline(HEAD_UPPER_MULTIPLIER, color='red', linestyle='--', label='Head Movement Limit')
    ax[1].legend()

    calibration_start_time = time.time()
    print("Collecting calibration data (3s)... Please sit still.")

    def update(frame):
        nonlocal pub_data, pub_decision
        global is_calibrated, background_power_jaw, background_power_head
        
        try:
            # A. Fetch Data
            new_data = eeg.get_data()
            if new_data is None: return lines

            # B. ZMQ RELAY: Send raw data for other scripts (Blink Detector)
            # Create dict {'Fp1': val, 'Fp2': val...}
            relay_msg = {}
            for ch_idx, ch_name in HALO_CHANNELS_MAP.items():
                if ch_idx < len(new_data):
                    # Take the last sample
                    relay_msg[ch_name] = new_data[ch_idx][-1]
            pub_data.send_json(relay_msg)

            # C. Processing for Fourier
            # Extract Fp1, Fp2
            chunk_fp1 = new_data[0]
            chunk_fp2 = new_data[1]
            
            # Average channels (Fp1+Fp2)/2
            chunk_avg = (chunk_fp1 + chunk_fp2) / 2
            
            # Add to buffer
            data_buffer.extend(chunk_avg)
            
            # Not enough data yet
            if len(data_buffer) < buffer_samples: return lines

            # Convert to numpy
            sig_raw = np.array(data_buffer) * 1e6 # uV
            
            # Filter
            filtered_signal = sosfilt(sos_band, sosfilt(sos_notch, sig_raw))

            # --- D. CALIBRATION PHASE ---
            if not is_calibrated:
                if time.time() - calibration_start_time < CALIBRATION_TIME:
                    return lines
                else:
                    # Calculate baseline noise levels
                    background_power_jaw = get_band_power(filtered_signal, JAW_BAND, SFREQ)
                    background_power_head = get_band_power(filtered_signal, HEAD_BAND, SFREQ)
                    
                    # Safety check to avoid division by zero
                    background_power_jaw = max(background_power_jaw, 0.1)
                    background_power_head = max(background_power_head, 0.1)
                    
                    is_calibrated = True
                    print(f"CALIBRATION DONE.")
                    print(f"Base Jaw Power: {background_power_jaw:.2f}")
                    print(f"Base Head Power: {background_power_head:.2f}")

            # --- E. LIVE ANALYSIS ---
            if is_calibrated:
                # Analyze recent window
                fft_window_samples = int(FFT_WINDOW_TIME * SFREQ)
                recent_signal = filtered_signal[-fft_window_samples:]
                
                # Current powers
                current_jaw_pwr = get_band_power(recent_signal, JAW_BAND, SFREQ)
                current_head_pwr = get_band_power(recent_signal, HEAD_BAND, SFREQ)
                
                # Calculate Ratios (Signal-to-Noise)
                ratio_jaw = current_jaw_pwr / background_power_jaw
                ratio_head = current_head_pwr / background_power_head
                
                # --- DECISION LOGIC ---
                clench_detected = False
                head_movement_detected = False
                
                decision_signal = 0 # 0=Nothing, 1=Right(Jaw), -1=Left(Head)

                # 1. Check HEAD (High priority block)
                if ratio_head > HEAD_UPPER_MULTIPLIER:
                    # Too much movement -> HEAD GESTURE (Previous Slide)
                    head_movement_detected = True
                    decision_signal = -1
                    print(f"HEAD MOVEMENT! Ratio: {ratio_head:.1f}")
                
                # 2. Check JAW (Only if head is stable-ish)
                elif ratio_jaw > JAW_LOWER_MULTIPLIER:
                    # Jaw clench -> NEXT SLIDE
                    clench_detected = True
                    decision_signal = 1
                    print(f"JAW CLENCH! Ratio: {ratio_jaw:.1f}")

                # Send Decision via ZMQ
                if decision_signal != 0:
                    pub_decision.send_json({"move": decision_signal})

                # --- VISUALIZATION UPDATE ---
                # Update power buffer for plotting (visualize the score)
                # Determine which score to show (Jaw Ratio usually)
                normalized_score = min(ratio_jaw, 20.0)
                
                new_len = len(chunk_avg)
                # Shift and append
                for _ in range(new_len):
                    power_buffer.append(normalized_score)

            # Update Plot Lines
            lines[0].set_ydata(filtered_signal)
            lines[0].set_xdata(times_buffer)
            limit0 = max(np.max(np.abs(filtered_signal)), 10.0) * 1.1
            ax[0].set_ylim(-limit0, limit0)
            
            lines[1].set_ydata(power_buffer)
            lines[1].set_xdata(times_buffer)
            current_max = np.max(power_buffer)
            y_max = max(HEAD_UPPER_MULTIPLIER * 1.5, current_max * 1.2)
            ax[1].set_ylim(0.5, y_max) 

        except Exception as e:
            print(f"\nFATAL ERROR: {e}")
            return lines

        return lines

if __name__ == '__main__':
    def setup_acquisition():
        global eeg
        print(f"Connecting to device {DEVICE_NAME}...")
        try:
            mgr = EEGManager()
            eeg.setup(mgr, device_name=DEVICE_NAME, cap=HALO_CHANNELS_MAP, sfreq=SFREQ)
            eeg.start_acquisition()
            time.sleep(1.0)
            return mgr
        except Exception as e:
            print(f"Connection Failed: {e}")
            return None

    ani = FuncAnimation(plt.gcf(), run_fourier_analysis(), interval=50, blit=False, cache_frame_data=False)
    plt.show()