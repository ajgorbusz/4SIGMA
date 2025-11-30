import sys
import zmq
import threading
import tkinter as tk
from enum import Enum
import signal

# --- ZMQ Configuration ---
ZMQ_HOST = "tcp://localhost:5557"

# --- Color Definition ---
class LedColor(Enum):
    RED = "#FF0000"      # Red (Listening / Rest)
    ORANGE = "#FFA500"   # Orange (Wait / Detected)
    GREEN = "#00FF00"    # Green (Ready)

# --- Window Settings ---
TRANSPARENT_BG = '#010101' 

class LedOverlay:
    def __init__(self):
        self.root = tk.Tk()
        
        # 1. Remove title bar
        self.root.overrideredirect(True)
        
        # 2. Window always on top
        self.root.wm_attributes("-topmost", True)
        
        # 3. Transparency
        self.root.config(bg=TRANSPARENT_BG)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_BG)
        except tk.TclError:
            pass 

        # Dot size
        self.size = 50
        
        # Position: Bottom Right Corner
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x_pos = screen_width - self.size - 20
        y_pos = screen_height - self.size - 20
        
        self.root.geometry(f"{self.size}x{self.size}+{x_pos}+{y_pos}")
        
        # 4. Canvas
        self.canvas = tk.Canvas(
            self.root, 
            width=self.size, 
            height=self.size, 
            bg=TRANSPARENT_BG, 
            highlightthickness=0
        )
        self.canvas.pack()
        
        # 5. Drawing the circle
        self.led_circle = self.canvas.create_oval(
            2, 2, self.size-2, self.size-2, 
            fill=LedColor.RED.value, 
            outline="" 
        )

    def update_state(self, flag):
        color = LedColor.RED.value
        debug_text = "UNKNOWN"

        if flag == 0:   # BLI
            color = LedColor.ORANGE.value
            debug_text = "CALM DOWN (Orange)"
        elif flag == 1: # RDY
            color = LedColor.GREEN.value
            debug_text = "READY (Green)"
        elif flag == 2: # RST
            color = LedColor.RED.value
            debug_text = "LISTENING (Red)"

        self.canvas.itemconfig(self.led_circle, fill=color)
        print(f"--- LED: {debug_text} ---")

    def watch_for_kill_signal(self):
        """
        This is a key function. It wakes up the GUI every 500ms so Python can
        process the Ctrl+C signal (KeyboardInterrupt).
        """
        self.root.after(500, self.watch_for_kill_signal)

    def start(self):
        # Start the "watchdog"
        self.watch_for_kill_signal()
        self.root.mainloop()
    
    def stop(self):
        self.root.quit()
        self.root.destroy()

class ZmqListener(threading.Thread):
    def __init__(self, gui_controller):
        super().__init__()
        self.gui = gui_controller
        self.daemon = True 
        self.running = True
        self.context = None
        self.socket = None

    def run(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        
        # Receive timeout (1000ms), so the thread doesn't hang indefinitely
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        
        try:
            print(f"Connecting to ZMQ on: {ZMQ_HOST}...")
            self.socket.connect(ZMQ_HOST)
            self.socket.setsockopt_string(zmq.SUBSCRIBE, "") 
            
            while self.running:
                try:
                    msg = self.socket.recv_json()
                    flag = msg.get("flag")
                    if flag is not None:
                        self.gui.update_state(flag)
                except zmq.Again:
                    # No message in this cycle, check running flag and loop again
                    continue
                except zmq.ContextTerminated:
                    break
                    
        except Exception as e:
            print(f"ZMQ Error: {e}")
        finally:
            if self.socket: self.socket.close()
            if self.context: self.context.term()

def run():
    print("--- LED CONTROLLER (TRANSPARENT MODE) ---")
    print("Press Ctrl+C in terminal to exit.")
    
    gui = LedOverlay()
    listener = ZmqListener(gui)
    listener.start()
    
    try:
        gui.start()
    except KeyboardInterrupt:
        print("\nStopping LED interface...")
        listener.running = False
        gui.stop()
        sys.exit(0)
