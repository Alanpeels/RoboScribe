from flask import Flask
import threading
import bot  # Assuming your main bot code is in bot.py

app = Flask(__name__)

@app.route("/")
def home():
    return "RoboScribe Bot is running", 200

if __name__ == "__main__":
    # Run the bot in a separate thread so Flask can run in main thread
    threading.Thread(target=lambda: bot.main()).start()

    # Run Flask server on 0.0.0.0:8080 to listen on all interfaces
    app.run(host="0.0.0.0", port=8080)
