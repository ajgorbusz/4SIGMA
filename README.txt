SYSTEM DESCRIPTION

The system allows you to control presentations (e.g., PowerPoint, PDF) using
EEG signals collected from the BrainAccess Halo headband. The system consists
of several modules communicating via the ZMQ protocol.

MAIN MODULES:

System Launcher (system_launcher.py) - Launches all processes.

Move Detector (move_detector.py) - Connects to the headband, analyzes signal.

Blink Detector (blink_detector.py) - Detects blinks (activation signal).

Core Unit (core_unit.py) - System brain, manages states.

Slide Controller (slide_controller.py) - Simulates key presses.

LED Controller (led_controller.py) - Displays a status dot on the screen.

HARDWARE REQUIREMENTS

BrainAccess Halo device (e.g., model BA HALO 057).

Computer running Windows/Linux/macOS with Bluetooth support.

INSTALLATION

Ensure you have Python installed (version 3.8 or newer).

Install the required libraries using the command:

pip install -r requirements.txt

Note: The brainaccess library must be available in your environment
(installed according to the device manufacturer's instructions).

(Linux Only) If using Linux, install Tkinter support:
sudo apt-get install python3-tk

STARTUP

Put on the BrainAccess Halo headband and ensure it is turned on.

Run the main startup script:

python system_launcher.py

Wait for initialization:

Startup messages for individual modules will appear in the console.

A RED dot (LED overlay) will appear in the bottom right corner of the screen.

A window with the EEG signal plot (from Move Detector) will open.

USER MANUAL (PRESENTATION CONTROL)

After starting the system, follow these steps:

Open your presentation (PowerPoint/PDF).

Click on the presentation window to make it active (focused).

The system operates based on a state machine (indicated by the dot color):

[RED DOT] - System Standby / Waiting for Activation

The system ignores jaw movements to avoid accidental switching.
-> ACTION: Blink your eyes distinctly to activate listening.

[GREEN DOT] - System Ready

After blinking, wait approx. 3 seconds (stabilization time).
When the dot turns green, the system listens for a move command.
-> ACTION: Clench your teeth to switch the slide.

[ORANGE DOT] - Cooldown

After switching a slide, the system enters a rest state for 2 seconds.
After this time, the dot returns to RED, and the cycle repeats.

TROUBLESHOOTING

"ZMQ Connection Error":
Ensure you are launching the system via system_launcher.py, not by running
individual files. The Core Unit must start first.

No reaction to blinks:
Check the plot window (Move Detector) to see if the signal on the occipital
channels (O1/O2) is clean and if the headband fits properly.

Slides are not switching:
Ensure the presentation window is active (clicked with the mouse).
The slide_controller.py script simulates keys in the currently active window.

SHUTDOWN

To safely shut down the system, go to the console where you started
system_launcher.py and press Ctrl+C.
