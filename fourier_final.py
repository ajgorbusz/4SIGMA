import numpy as np
import time
import sys
import zmq
from scipy.signal import butter, sosfilt, iirnotch, lfilter, welch
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import matplotlib
from collections import deque

# --- BRAINACCESS IMPORTS ---
from brainaccess.utils import acquisition
from brainaccess.core.eeg_manager import EEGManager

# --- 0. CONFIGURATION ---
matplotlib.use("QtAgg", force=True)

DEVICE_NAME = "BA HALO 057"
SFREQ = 250
KANALY_DO_ANALIZY = ['Fp1', 'Fp2'] 

# --- ZMQ CONFIGURATION (BROADCASTING) ---
ZMQ_PORT_DATA = 6000      # Here we broadcast raw data (Relay)
ZMQ_PORT_DECISION = 5556  # Here we broadcast decisions (Core Unit)

# Relay Config
ALL_CHANNELS_OUT = ["Fp1", "Fp2", "O1", "O2"]
HALO_CHANNELS_MAP = {0: "Fp1", 1: "Fp2", 2: "O1", 3: "O2"}

# Time windows
CZAS_OKNA_ANALIZY = 4.0      
OKNO_FFT = 0.5              

# Detection (Teeth vs Head)
CZAS_KALIBRACJI = 3.0        
MNOZNIK_DOLNY_Zeby = 1.5     
MNOZNIK_GORNY_Glowa = 100.0 
FREQ_MIN = 35.0  
FREQ_MAX = 110.0 
COOLDOWN_PO_WYKRYCIU = 1.0
MIN_LICZBA_KLATEK = 2

# --- GLOBAL VARIABLES ---
N_CH_INPUT = len(KANALY_DO_ANALIZY)
N_PLOTS = 2
BUFFER_SIZE = int(SFREQ * CZAS_OKNA_ANALIZY)
FFT_WINDOW_SIZE = int(SFREQ * OKNO_FFT)

# Hardware initialization
eeg = acquisition.EEG()

# Buffers
eeg_buffer = np.zeros((N_CH_INPUT, BUFFER_SIZE))
power_buffer = np.zeros(BUFFER_SIZE)
times_buffer = np.linspace(-CZAS_OKNA_ANALIZY, 0, BUFFER_SIZE)

processed_samples = 0
ch_indices = [k for k, v in HALO_CHANNELS_MAP.items() if v in KANALY_DO_ANALIZY]

# State
counter_zacisk = 0
block_until = 0.0
is_calibrated = False
calibration_buffer = [] 
baseline_power = 1.0    

# Filters
b_notch, a_notch = iirnotch(50.0, 30.0, fs=SFREQ) 
sos_high = butter(2, 2.0, btype='highpass', fs=SFREQ, output='sos')

# --- ZMQ SETUP ---
context = zmq.Context()

# Socket 1: RELAY (Data)
socket_data = context.socket(zmq.PUB)
socket_data.bind(f"tcp://*:{ZMQ_PORT_DATA}")

# Socket 2: DECISIONS (Core)
socket_decision = context.socket(zmq.PUB)
socket_decision.bind(f"tcp://*:{ZMQ_PORT_DECISION}")

print(f">>>START")
print(f"    - Relay (Data):      Port {ZMQ_PORT_DATA}")
print(f"    - Decisions:         Port {ZMQ_PORT_DECISION}")

# --- 1. PLOT INITIALIZATION ---
fig, ax = plt.subplots(N_PLOTS, 1, sharex=True, figsize=(10, 8))
fig.suptitle(f"TEETH vs HEAD + RELAY")

lines = []
# Signal plot
ax[0].set_ylabel("Signal (uV)", fontsize=9)
line0, = ax[0].plot(times_buffer, np.zeros(BUFFER_SIZE), lw=1, color='tab:blue')
lines.append(line0)
ax[0].grid(True, alpha=0.5)

# Power plot
ax[1].set_ylabel("Power (Ratio)", fontsize=9)
line1, = ax[1].plot(times_buffer, np.zeros(BUFFER_SIZE), lw=2, color='tab:red')
lines.append(line1)

# Threshold lines
line_thresh_teeth = ax[1].axhline(y=MNOZNIK_DOLNY_Zeby, color='g', linestyle='--', label='Teeth')
line_thresh_head = ax[1].axhline(y=MNOZNIK_GORNY_Glowa, color='m', linestyle='--', label='Head')
ax[1].legend(loc='upper left')
ax[1].grid(True, alpha=0.5)
ax[1].set_yscale('log')
ax[-1].set_xlabel("Time (s)")

# --- 2. CALCULATION FUNCTION ---
def calculate_band_power(signal_chunk):
    if signal_chunk.shape[0] < SFREQ // 10: return 0.0
    freqs, psd = welch(signal_chunk, fs=SFREQ, nperseg=min(len(signal_chunk), FFT_WINDOW_SIZE))
    idx_band = np.logical_and(freqs >= FREQ_MIN, freqs <= FREQ_MAX)
    if np.sum(idx_band) == 0: return 0.0
    return np.mean(psd[idx_band])

# --- 3. MAIN LOOP ---
start_time = time.time()

def update_plot(frame):
    global eeg_buffer, power_buffer, processed_samples, block_until
    global counter_zacisk, is_calibrated, baseline_power
    
    current_time = time.time()
    elapsed = current_time - start_time
    
    try:
        # A. FETCH DATA FROM HARDWARE
        eeg.get_mne()
        if eeg.data.mne_raw is None: return lines
        
        all_data = eeg.data.mne_raw.get_data()
        total_samples = all_data.shape[1]
        
        if total_samples > processed_samples:
            # New data chunk
            new_chunk = all_data[:, processed_samples:]
            new_len = new_chunk.shape[1]
            
            # --- 1. RELAY (Sending raw uV to port 6000) ---
            chunk_uv = new_chunk * 1e6
            packet = {
                "data": chunk_uv,        
                "channels": ALL_CHANNELS_OUT, 
                "sfreq": SFREQ,
                "dc_offset": 0 # Sending 0, because the router sends raw data here
            }
            try:
                socket_data.send_pyobj(packet)
            except zmq.ZMQError:
                pass 
            # --------------------------------------------------

            processed_samples = total_samples
            
            # --- 2. LOCAL BUFFER UPDATE ---
            # Select only Fp1/Fp2 for Jarvis
            for i, raw_idx in enumerate(ch_indices):
                d = new_chunk[raw_idx, :]
                if new_len >= BUFFER_SIZE: eeg_buffer[i, :] = d[-BUFFER_SIZE:]
                else:
                    eeg_buffer[i, :-new_len] = eeg_buffer[i, new_len:]
                    eeg_buffer[i, -new_len:] = d

            # --- 3. PROCESSING ---
            raw_avg = np.mean(eeg_buffer, axis=0)
            
            filtered_signal = lfilter(b_notch, a_notch, raw_avg)
            filtered_signal = sosfilt(sos_high, filtered_signal)
            
            if BUFFER_SIZE >= FFT_WINDOW_SIZE:
                analysis_window = filtered_signal[-FFT_WINDOW_SIZE:]
                raw_metric_score = calculate_band_power(analysis_window)
            else:
                raw_metric_score = 0.0

            # --- 4. DETECTION LOGIC ---
            normalized_score = 0.0
            status_msg = "..."
            signal_to_send = 0 

            if not is_calibrated:
                status_msg = f"CALIBRATION... {elapsed:.1f}/{CZAS_KALIBRACJI}s"
                if raw_metric_score > 0:
                    calibration_buffer.append(raw_metric_score)
                
                if elapsed > CZAS_KALIBRACJI:
                    if len(calibration_buffer) > 5:
                        baseline_power = np.mean(calibration_buffer)
                        if baseline_power == 0: baseline_power = 1.0
                        
                        is_calibrated = True
                        print(f"\n SYSTEM CALIBRATED! Baseline: {baseline_power:.1e}")
                        
                        line_thresh_teeth.set_ydata([MNOZNIK_DOLNY_Zeby]) 
                        line_thresh_head.set_ydata([MNOZNIK_GORNY_Glowa])
                    normalized_score = 1.0 
            else:
                status_msg = "READY"
                normalized_score = raw_metric_score / baseline_power if baseline_power > 0 else 0
                
                if current_time < block_until:
                    status_msg = "COOLDOWN"
                else:
                    # HEAD (1)
                    if normalized_score > MNOZNIK_GORNY_Glowa:
                        print(f"\n >>> HEAD MOVEMENT! (x{normalized_score:.0f})")
                        block_until = current_time + COOLDOWN_PO_WYKRYCIU
                        counter_zacisk = 0 
                        signal_to_send = -1
                        status_msg = "HEAD MOVEMENT!"
                        
                    # TEETH (-1)
                    elif normalized_score > MNOZNIK_DOLNY_Zeby:
                        counter_zacisk += 1
                        if counter_zacisk >= MIN_LICZBA_KLATEK:
                            print(f"\n >>> TEETH CLENCH (x{normalized_score:.1f})")
                            block_until = current_time + COOLDOWN_PO_WYKRYCIU
                            counter_zacisk = 0
                            signal_to_send = 1
                            status_msg = "TEETH CLENCH!"     
                    else:
                        counter_zacisk = 0 

            # --- 5. BROADCASTING DECISIONS (5556) ---
            socket_decision.send_json({"move": signal_to_send})

            # --- 6. DRAWING ---
            if is_calibrated:
                log = f"\r[{status_msg}] Ratio: x{normalized_score:.1f}"
            else:
                log = f"\r{status_msg} Raw: {raw_metric_score:.1e}"
            sys.stdout.write(log.ljust(80))
            sys.stdout.flush()

            if new_len >= BUFFER_SIZE:
                power_buffer[:] = normalized_score
            else:
                power_buffer[:-new_len] = power_buffer[new_len:]
                power_buffer[-new_len:] = normalized_score

            lines[0].set_ydata(filtered_signal)
            lines[0].set_xdata(times_buffer)
            limit0 = max(np.max(np.abs(filtered_signal)), 10.0) * 1.1
            ax[0].set_ylim(-limit0, limit0)
            
            lines[1].set_ydata(power_buffer)
            lines[1].set_xdata(times_buffer)
            current_max = np.max(power_buffer)
            y_max = max(MNOZNIK_GORNY_Glowa * 1.5, current_max * 1.2)
            ax[1].set_ylim(0.5, y_max) 

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        return lines

    return lines

def run():
    def setup_acquisition():
        global eeg
        print(f"Connecting to system {DEVICE_NAME}...")
        try:
            mgr = EEGManager()
            eeg.setup(mgr, device_name=DEVICE_NAME, cap=HALO_CHANNELS_MAP, sfreq=SFREQ)
            eeg.start_acquisition()
            time.sleep(1.0)
            return mgr
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    mgr = setup_acquisition()
    try:
        ani = FuncAnimation(fig, update_plot, interval=50, blit=False, cache_frame_data=False)
        plt.show()
    finally:
        print("Closing...")
        eeg.stop_acquisition()
        mgr.disconnect()
        eeg.close()
        socket_data.close()
        socket_decision.close()
        context.term()

run()
