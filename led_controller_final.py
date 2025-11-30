import sys
import zmq
import threading
import tkinter as tk
from enum import Enum
import signal

# --- 0. CONFIGURATION ---
ZMQ_HOST = "tcp://localhost:5557"  # Core Unit Publisher Address
TRANSPARENT_BG = '#010101'         # Color key for transparency

# --- 1. COLOR DEFINITIONS ---
class LedColor(Enum):
    """
    Enum defining the colors for system states.
    """
    RED = "#FF0000"      # State: BLINK_WAIT (Listening for blink) / REST
    ORANGE = "#FFA500"   # State: WAIT (Cooldown) / DETECTED
    GREEN = "#00FF00"    # State: READY (Listening for jaw/head commands)

# --- 2. GUI CLASS ---
class LedOverlay:
    """
    Creates a transparent, topmost overlay window containing a single colored circle (LED).
    This provides visual feedback to the user on top of the presentation.
    """
    def __init__(self):
        self.root = tk.Tk()
        
        # Window Configuration
        self.root.overrideredirect(True)       # Remove title bar and borders
        self.root.wm_attributes("-topmost", True) # Keep window always on top
        
        # Transparency Configuration
        # Note: -transparentcolor works on Windows. On Linux/Mac behavior might vary,
        # but setting bg color is standard fallback.
        self.root.config(bg=TRANSPARENT_BG)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_BG)
        except tk.TclError:
            pass 

        # Dimensions and Position
        self.size = 50
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Position: Bottom-Right corner
        x_pos = screen_width - self.size - 20
        y_pos = screen_height - self.size - 20
        self.root.geometry(f"{self.size}x{self.size}+{x_pos}+{y_pos}")
        
        # Canvas Setup
        self.canvas = tk.Canvas(
            self.root, 
            width=self.size, 
            height=self.size, 
            bg=TRANSPARENT_BG, 
            highlightthickness=0
        )
        self.canvas.pack()
        
        # Draw Initial LED (Red by default)
        self.led_item = self.draw_led(LedColor.RED.value)

    def draw_led(self, color):
        """Draws the circle on the canvas."""
        padding = 5
        return self.canvas.create_oval(
            padding, padding, 
            self.size - padding, self.size - padding, 
            fill=color, outline=""
        )

    def update_state(self, flag_code):
        """
        Updates the LED color based on the flag received from Core Unit.
        
        Args:
            flag_code (int): 
                0 -> RED (Blink Wait)
                1 -> ORANGE (Wait/Cooldown)
                2 -> GREEN (Ready for Command)
        """
        color = LedColor.RED.value  # Default
        
        if flag_code == 0:
            color = LedColor.RED.value
        elif flag_code == 1:
            color = LedColor.ORANGE.value
        elif flag_code == 2:
            color = LedColor.GREEN.value
            
        self.canvas.itemconfig(self.led_item, fill=color)

    def start(self):
        """Starts the Tkinter main event loop."""
        self.root.mainloop()
        
    def stop(self):
        """Destroys the window and stops the loop."""
        self.root.quit()

# --- 3. NETWORK LISTENER THREAD ---
class ZmqListener(threading.Thread):
    """
    Background thread that listens for status updates from the Core Unit via ZMQ
    and updates the GUI accordingly.
    """
    def __init__(self, gui_instance):
        super().__init__()
        self.gui = gui_instance
        self.running = True
        self.context = None
        self.socket = None

    def run(self):
        """Main thread loop."""
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        
        # Set receive timeout to 1000ms to allow checking 'self.running' flag
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        
        try:
            print(f"Connecting to ZMQ Core at: {ZMQ_HOST}...")
            self.socket.connect(ZMQ_HOST)
            self.socket.setsockopt_string(zmq.SUBSCRIBE, "") 
            
            while self.running:
                try:
                    # Non-blocking receive (due to timeout)
                    msg = self.socket.recv_json()
                    flag = msg.get("flag")
                    
                    if flag is not None:
                        # Update GUI (Thread-safe enough for simple Tkinter updates)
                        self.gui.update_state(flag)
                        
                except zmq.Again:
                    # Timeout reached, loop again to check self.running
                    continue
                except zmq.ContextTerminated:
                    break
                    
        except Exception as e:
            print(f"ZMQ Error: {e}")
        finally:
            if self.socket: self.socket.close()
            if self.context: self.context.term()

    def stop(self):
        """Signals the thread to stop."""
        self.running = False

# --- 4. MAIN EXECUTION ---
if __name__ == "__main__":
    print("--- LED STATUS CONTROLLER (TRANSPARENT OVERLAY) ---")
    print("Press Ctrl+C in terminal to exit.")
    
    # Initialize GUI
    gui = LedOverlay()
    
    # Initialize and start Network Thread
    listener = ZmqListener(gui)
    listener.start()
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nExiting...")
        listener.stop()
        gui.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Start GUI Loop (Blocking)
        gui.start()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        # Ensure thread finishes
        listener.join(timeout=2.0)