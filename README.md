# Rugplay Sniper Bot

A simple trading bot with a graphical user interface (GUI) for the platform `rugplay.com`. It provides tools for manual trading, automated sniping of new tokens, and portfolio management.

This AI script was created by **Gemini**.

---

## Key Functionality

* **GUI Dashboard**: A user-friendly interface built with `Tkinter` to display your USD balance, total portfolio value, and control all trading functions.
* **Manual Trading**: Select any token you own from a dropdown list and execute buy or sell orders. You can use quick percentage buttons (25%, 50%, 75%, 95%) or enter a manual amount.
* **🔥 Sell All Tokens**: A single-click button to automatically liquidate every token in your portfolio. The bot iterates through each holding and executes a maximum sell order.
* **Sniper Bot**: An automated function that monitors for the newest coin listed on the market. When a new coin appears, the bot will automatically execute a buy order for a pre-configured amount (either a fixed USD value or a percentage of your available balance).
* **Session Management**: On the first run, you log in manually through the browser. The bot saves your session in a Chrome user profile, allowing it to run in headless mode for all subsequent actions.

---

## Requirements & Setup

To run this bot, you'll need the following installed on your system.

1.  **Python 3**: The script is written in Python.
2.  **Google Chrome**: The bot uses Selenium to automate the Google Chrome browser.
3.  **ChromeDriver**: You must download the version of ChromeDriver that **perfectly matches your installed Google Chrome version**.
4.  **Python Libraries**: Install the required `selenium` library using pip.
    ```bash
    pip install selenium
    ```

### Configuration

Before running the script, you must update the following variable inside the Python file:

* `CHROMEDRIVER_PATH`: Change the path `/usr/bin/chromedriver` to the exact location where you saved the ChromeDriver executable on your computer.

### First-Time Use

1.  Run the Python script.
2.  A Chrome window will open. **Log into your rugplay.com account manually.**
3.  Once you are logged in, click the **"Proceed After Login"** button in the bot's GUI.
4.  The bot will confirm the login, save the session, and (by default) restart in headless mode for all future operations. You are now ready to use the trading functions.



-----------------------------------------


this discription is also ai generated
Its mainly used on linux but could also work on other platforms
please help me clean this mess up, im not good at coding
