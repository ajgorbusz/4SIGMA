import sys
import zmq
import threading
import tkinter as tk
from enum import Enum

# --- ZMQ CONFIGURATION ---
ZMQ_HOST = "tcp://localhost:5557"

# --- COLOR DEFINITIONS ---
class LedColor(Enum):
    RED = "#FF0000"      # Listening / Waiting
    ORANGE = "#FFA500"   # Rest / Cooldown
    GREEN = "#00FF00"    # Ready for command

# --- WINDOW SETTINGS ---
TRANSPARENT_BG_COLOR = '#010101' 

class LedOverlay:
    """
    Creates a transparent, always-on-top window with a colored circle.
    """
    def __init__(self):
        self.root = tk.Tk()
        
        # 1. Remove Title Bar
        self.root.overrideredirect(True)
        
        # 2. Keep Always on Top
        self.root.wm_attributes("-topmost", True)
        
        # 3. Set Transparency
        self.root.config(bg=TRANSPARENT_BG_COLOR)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_BG_COLOR)
        except tk.TclError:
            pass

        # Geometry
        self.size = 50
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Position: Bottom Right Corner
        x_pos = screen_width - self.size - 20
        y_pos = screen_height - self.size - 20
        self.root.geometry(f"{self.size}x{self.size}+{x_pos}+{y_pos}")

        # Canvas
        self.canvas = tk.Canvas(self.root, width=self.size, height=self.size, 
                                bg=TRANSPARENT_BG_COLOR, highlightthickness=0)
        self.canvas.pack()
        
        # Draw Initial Circle (Red)
        self.indicator = self.canvas.create_oval(2, 2, self.size-2, self.size-2, 
                                                 fill=LedColor.RED.value, outline="")

    def update_state(self, flag):
        """
        Updates circle color based on flag.
        """
        color = LedColor.RED.value
        
        if flag == 1:
            color = LedColor.GREEN.value
        elif flag == 2:
            color = LedColor.ORANGE.value
            
        self.canvas.itemconfig(self.indicator, fill=color)

    def start(self):
        self.root.mainloop()

class ZmqListener(threading.Thread):
    """
    Background thread for ZMQ listening.
    """
    def __init__(self, gui):
        threading.Thread.__init__(self)
        self.gui = gui
        self.running = True
        self.daemon = True 

    def run(self):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        
        # Timeout 1000ms
        socket.setsockopt(zmq.RCVTIMEO, 1000)
        
        try:
            print(f"LED Controller: Connecting to {ZMQ_HOST}...")
            socket.connect(ZMQ_HOST)
            socket.setsockopt_string(zmq.SUBSCRIBE, "") 
            
            while self.running:
                try:
                    msg = socket.recv_json()
                    flag = msg.get("flag")
                    if flag is not None:
                        self.gui.update_state(flag)
                except zmq.Again:
                    continue
                except zmq.ContextTerminated:
                    break
                    
        except Exception as e:
            print(f"ZMQ Error: {e}")
        finally:
            socket.close()
            context.term()

def run_led_controller():
    print("--- LED CONTROLLER (OVERLAY) ---")
    print("Press Ctrl+C in terminal to stop.")
    
    gui = LedOverlay()
    listener = ZmqListener(gui)
    listener.start()
    
    try:
        gui.start()
    except KeyboardInterrupt:
        pass
    finally:
        listener.running = False

if __name__ == "__main__":
    run_led_controller()
