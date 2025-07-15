# Rugplay Trading Tool 🤖

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
![Selenium](https://img.shields.io/badge/Selenium-4.0%2B-green?style=for-the-badge&logo=selenium)
![Tkinter](https://img.shields.io/badge/UI-Tkinter-orange?style=for-the-badge)

A multi-featured automation tool with a graphical user interface (GUI) for interacting with the Rugplay platform. It includes manual trading, a "Sell All" function, a sniper bot for new coins, and a random trading bot.

---

## ⚠️ Important Disclaimer ⚠️

> **This tool is for educational purposes ONLY.**
> - The platform, Rugplay, does **NOT** use real money. It is a simulation/game.
> - Automating user activity is likely against the platform's Terms of Service.
> - **Using this tool can and likely will result in a permanent ban from the platform.**
> - The author is not responsible for any consequences of using this software. Use it at your own risk.

---

## ✨ Features

- **Graphical User Interface:** Easy-to-use interface built with `Tkinter`.
- **Portfolio Dashboard:** View your current USD balance and total portfolio value in real-time.
- **Manual Trading:**
    - Buy or sell any token you hold.
    - Use percentage buttons (25%, 50%, 75%, 95%) for quick amount calculation.
    - Manually input a specific trade amount.
- **🔥 Sell All Tokens:** A one-click button to liquidate your entire token portfolio.
- **Sniper Bot:**
    - Automatically monitors the market for the newest coin listings.
    - Immediately places a BUY order when a new coin is detected.
    - Spawns a dedicated worker to monitor the new token.
    - Sells the token after the first new buyer appears or after a timeout.
- **Random Bot:**
    - Alternates between buying and selling a pre-selected token at random intervals and amounts.
    - A simple bot for generating activity.
- **Hybrid Automation:**
    - Uses fast, direct **API calls** for most trading actions to ensure speed.
    - Uses **Selenium UI automation** for complex actions that require scraping or are difficult to replicate via the API.
- **Debug Mode:** Toggle between headless (background) and visible browser modes. The visible mode uses slower UI automation for all trades, making it easier to debug.
- **Persistent Session:** Saves your Chrome browser profile to keep you logged in between sessions.

---

## 🚀 Getting Started

Follow these steps to get the tool up and running.

### Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [Google Chrome](https://www.google.com/chrome/) browser
- [ChromeDriver](https://chromedriver.chromium.org/downloads) that **matches your Google Chrome version**.

### Installation

1.  **Clone the repository:**
    ```sh
    git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
    cd your-repo-name
    ```

2.  **Install the required Python packages:**
    ```sh
    pip install selenium requests
    ```

3.  **Configure the script:**
    Open the Python script in your favorite editor and change the `CHROMEDRIVER_PATH` variable to the location where you saved ChromeDriver.

    **Example for macOS/Linux:**
    ```python
    # --- Configuration & Constants ---
    CHROMEDRIVER_PATH = "/Users/yourname/Downloads/chromedriver"
    ```
    **Example for Windows:**
    ```python
    # --- Configuration & Constants ---
    CHROMEDRIVER_PATH = "C:\\Users\\yourname\\Downloads\\chromedriver.exe"
    ```

---

## 📖 How to Use

1.  **Run the script:**
    ```sh
    python your_script_name.py
    ```
2.  **First-Time Login:**
    - A Chrome window will open.
    - **Log in to your Rugplay account manually** inside this window.
    - Once logged in, click the **"Proceed After Login"** button in the tool's GUI.
    - The tool will capture your session, and the browser will restart in headless mode (unless Debug Mode is on). Your login will now be saved for future sessions.

3.  **Using the Bots:**
    - **Manual Tab:** Select a token from your portfolio to perform manual trades or use the "Sell All" button.
    - **Sniper Bot Tab:** Enter a fixed USD amount or select a percentage of your balance to use for each snipe. Click "Start Sniper Bot".
    - **Random Bot Tab:** First, select the token you want the bot to trade in the "Manual" tab. Then, switch to the "Random Bot" tab, set a max buy limit, and click "Start Random Bot".

---

## 🛠️ How It Works

The script is a `Tkinter` application that manages `Selenium` and `requests` threads.

-   `TradeApp(tk.Tk)`: The main class that builds and manages the GUI, handles user input, and starts/stops the automation threads.
-   `RugplayAPI`: A helper class that uses `driver.execute_script()` to make JavaScript `fetch` calls to the website's internal APIs. This is much faster and more reliable than navigating and clicking through the UI.
-   **Session Management**: On the first run, the user logs in manually. The tool then saves the entire Chrome user profile (cookies, session data, etc.) to the `~/chromeprofile` directory. Subsequent runs load this profile, keeping the user logged in.
-   **Hybrid Trading Approach**:
    -   **API Trading (`_trade_via_api`)**: For speed and reliability, bots and manual trades (in normal mode) use the `requests` library to send POST requests directly to the `/api/coin/{token_symbol}/trade` endpoint, mimicking the website's own authenticated calls.
    -   **UI Automation (`_trade_token_flow`, `_sell_max_for_token`)**: In Debug Mode, or for actions that are complex (like scraping the "Max sellable" amount which isn't available in the portfolio API), the tool uses Selenium to directly control the browser, click buttons, and enter text.
-   **Multithreading**: Each bot and major background task (like selling all tokens) runs in its own `threading.Thread` to prevent the GUI from freezing. All GUI updates from these threads are safely passed back to the main thread using `self.after()`.
-   **Sniper Bot Logic**:
    1.  `_sniper_scanner_logic`: An API-polling loop that constantly checks the `/api/market` endpoint for a new coin.
    2.  `_sniper_buy_logic`: When a new coin is found, it's added to a queue. This thread processes the queue, buying the coin via the fast API method.
    3.  `_snipe_post_buy_worker`: After a successful buy, a new **parallel worker** is spawned. This worker creates its own cloned browser instance to monitor the purchased coin and execute the sell logic without interfering with the main scanner and buyer threads.

readme and script is generted by gemini
but thoroughly tested and edited to have cool features
