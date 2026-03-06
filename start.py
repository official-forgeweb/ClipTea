# start.py — Entry point for the bot
import subprocess
import sys
import os

# Install requirements first
subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

# Run the bot
os.system(f"{sys.executable} bot.py")