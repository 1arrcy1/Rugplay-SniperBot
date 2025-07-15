import tkinter as tk
from tkinter import ttk, messagebox
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    WebDriverException, NoSuchWindowException, TimeoutException,
    NoSuchElementException
)
import time
from datetime import datetime
import json
import threading
import math
import signal
import sys
import random
import os
import shutil
import tempfile
import itertools
import requests


# --- Configuration & Constants ---
CHROMEDRIVER_PATH = "/usr/bin/chromedriver"
CHROME_USER_DATA_DIR = os.path.expanduser("~/chromeprofile")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DEBUG_MODE = False
HEADLESS_MODE = not DEBUG_MODE

# URLs
BASE_URL = "https://rugplay.com"
PORTFOLIO_API_URL = f"{BASE_URL}/api/portfolio/total"
MARKET_API_URL = f"{BASE_URL}/api/market?sortBy=createdAt&sortOrder=desc&limit=50"
NEWEST_COIN_API_URL = f"{BASE_URL}/api/market?sortBy=createdAt&sortOrder=desc&limit=1"
HOLDERS_API_URL_TEMPLATE = f"{BASE_URL}/api/coin/{{token_symbol}}/holders?limit=50"
TRADE_API_URL_TEMPLATE = f"{BASE_URL}/api/coin/{{token_symbol}}/trade"

# XPaths
DIALOG_CONTENT_XPATH = "//div[@data-slot='dialog-content']"
TRADE_BUTTON_XPATH_TEMPLATE = "//button[contains(translate(text(), 'BUYSELL', 'buysell'), '{trade_type}')]"
AMOUNT_INPUT_XPATH = "//input[@type='number' and @placeholder='0.00']"
INSUFFICIENT_FUNDS_XPATH = "//*[contains(text(), 'Insufficient')]"
CONFIRM_BUTTON_XPATH_TEMPLATE = f"{DIALOG_CONTENT_XPATH}//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{{trade_type}} {{token_symbol}}')]"
TRADE_OUTCOME_XPATH = "//*[contains(text(), 'successfully') or contains(text(), 'Trade successful')] | //div[contains(text(), 'Trade failed')]"

# --- XPaths for Sell All functionality ---
SELL_TAB_XPATH = "//button[contains(translate(text(), 'SELL', 'sell'), 'sell')]"
MAX_BUTTON_XPATH = "//button[text()='Max']"
CONFIRM_SELL_BUTTON_XPATH_TEMPLATE = "//div[@data-slot='dialog-content']//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sell {token_symbol}')]"


class RugplayAPI:
    """Handles all JavaScript-based API interactions with rugplay.com."""
    def __init__(self, driver):
        self.driver = driver

    def _fetch(self, url):
        """Generic method to execute a fetch request and return JSON."""
        js_script = f"""
            return fetch('{url}', {{ headers: {{ 'Content-Type': 'application/json', 'User-Agent': '{USER_AGENT}' }} }})
            .then(response => response.text())
            .catch(error => JSON.stringify({{'error': error.message, 'status': 'fetch_failed'}}));
        """
        try:
            if not self.is_browser_open():
                return {'error': 'Browser is not open.'}
            response_text = self.driver.execute_script(js_script)

            # Handle cases where the API returns an HTML login page instead of JSON
            if response_text.strip().startswith('<'):
                return {'error': 'API returned HTML. Session may be invalid.'}

            return json.loads(response_text)
        except (WebDriverException, json.JSONDecodeError) as e:
            return {'error': f"API fetch failed: {e}"}

    def get_portfolio(self):
        return self._fetch(PORTFOLIO_API_URL)

    def get_recent_coins(self):
        return self._fetch(MARKET_API_URL)

    def get_newest_coin(self):
        return self._fetch(NEWEST_COIN_API_URL)

    def get_token_holders(self, token_symbol):
        url = HOLDERS_API_URL_TEMPLATE.format(token_symbol=token_symbol)
        return self._fetch(url)

    def is_browser_open(self):
        """Checks if the Selenium browser instance is still alive."""
        if not self.driver:
            return False
        try:
            _ = self.driver.window_handles
            return True
        except (WebDriverException, NoSuchWindowException):
            return False


class TradeApp(tk.Tk):
    """Main application class for the trading tool."""
    def __init__(self):
        super().__init__()
        self.selenium_driver = None
        self.api = None
        self.log_history = []
        self.current_coin_holdings = []
        self.session_cookie = None

        # Bot state
        self.sniper_bot_active = False
        self.random_bot_active = False
        self.sniper_bot_thread = None
        self.random_bot_thread = None

        # Window references
        self.history_window = None
        self.log_text_widget = None
        self.recent_coins_window = None

        self._setup_gui()
        self.update_status("Initializing application...")
        threading.Thread(target=self._run_selenium_thread, args=(True,), daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)


    # --- GUI Setup ---
    def _setup_gui(self):
        self.title("Rugplay Balance & Trade Tool")
        self.geometry("550x700")
        self.resizable(False, False)

        # --- UI Variables ---
        self.selected_token_symbol = tk.StringVar(self, "Loading...")
        self.buy_percentage = tk.StringVar(self)
        self.sell_percentage = tk.StringVar(self)
        self.sniper_buy_percentage = tk.StringVar(self)
        self.balance_var = tk.StringVar(self, "Balance (USD): Loading...")
        self.portfolio_var = tk.StringVar(self, "Portfolio Value: Loading...")
        self.status_var = tk.StringVar(self, "Initializing...")
        self.debug_var = tk.BooleanVar(value=DEBUG_MODE)

        # --- Main Layout ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(expand=True, fill="both")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        self._create_dashboard(main_frame)
        self.notebook = self._create_notebook(main_frame)
        self._create_bottom_controls(main_frame)
        self._create_status_bar(main_frame)

    def _create_dashboard(self, parent):
        dashboard_frame = ttk.Frame(parent)
        dashboard_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        dashboard_frame.columnconfigure(0, weight=1)

        ttk.Label(dashboard_frame, text="Rugplay Portfolio Dashboard", font=("Arial", 16, "bold")).pack(pady=5)
        ttk.Label(dashboard_frame, textvariable=self.balance_var, font=("Arial", 12)).pack(pady=2)
        ttk.Label(dashboard_frame, textvariable=self.portfolio_var, font=("Arial", 12)).pack(pady=2)

        self.action_button = ttk.Button(dashboard_frame, text="Proceed After Login", command=self._proceed_after_login, state=tk.DISABLED)
        self.action_button.pack(pady=10)

    def _finalize_sell_all_ui(self):
        """Helper to re-enable UI elements after the sell-all process."""
        self.after(0, lambda: self.sell_all_button.config(state=tk.NORMAL))
        self.after(0, lambda: self.buy_button.config(state=tk.NORMAL))
        self.after(0, lambda: self.sell_button.config(state=tk.NORMAL))

    def _finalize_manual_trade_ui(self):
        """Helper to re-enable manual trade buttons after a trade attempt."""
        if self.buy_button and self.buy_button.winfo_exists():
            self.buy_button.config(state=tk.NORMAL)
        if self.sell_button and self.sell_button.winfo_exists():
            self.sell_button.config(state=tk.NORMAL)




    def _force_reload_coin_page(self, driver, token_symbol, log_prefix):
        """
        Navigates to the coin page and performs a hard reload, clearing cache
        to ensure all UI data is fresh before scraping.
        """
        self.after(0, lambda: self.update_status(f"🛠️ {log_prefix} Force-reloading page to get fresh data..."))
        try:
            # Navigate to the correct page
            coin_page_url = f"{BASE_URL}/coin/{token_symbol}"
            if driver.current_url != coin_page_url:
                driver.get(coin_page_url)

            # Use Chrome DevTools Protocol to clear cache and force reload
            driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
            driver.execute_cdp_cmd('Page.reload', {'ignoreCache': True})

            # Wait for the page to be ready after the reload
            WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, SELL_TAB_XPATH))
            )
            self.after(0, lambda: self.update_status(f"✅ {log_prefix} Page reloaded successfully."))
            return True
        except Exception as e:
            self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Force reload failed: {err}", is_error=True))
            return False


    def _scrape_and_calculate_sell_amount(self, token_symbol):
        """
        Performs a force-reload and then scrapes the UI to determine the optimal
        sell amount, checking for 'Max sellable' as the priority.
        """
        log_prefix = f"[RandomBot:{token_symbol}]"
        driver = self.selenium_driver

        # 1. Force a hard reload to get fresh data
        if not self._force_reload_coin_page(driver, token_symbol, log_prefix):
            return 0 # Return 0 if reload fails

        try:
            # 2. Scrape the now-fresh data
            self.after(0, lambda: self.update_status(f"{log_prefix} Scraping fresh sell data..."))

            # Click the 'SELL' tab
            sell_tab = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, SELL_TAB_XPATH)))
            driver.execute_script("arguments[0].click();", sell_tab)

            # Scrape the panel text to find "Available" or "Max sellable"
            panel_element = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.XPATH, "//input[@type='number']/ancestor::div[2]")))
            panel_text = panel_element.text
            parts = panel_text.split()

            # Check for "Max sellable" first, just like the sniper bot
            if "Max sellable" in panel_text:
                max_sellable_text = next((f"{parts[i+1]}" for i, x in enumerate(parts) if x == "sellable:"), "0")
                amount = float(max_sellable_text.replace(',', ''))
                self.after(0, lambda a=amount: self.update_status(f"{log_prefix} Pool limit detected. Selling max: {a}"))
                return amount

            # Fallback to "Available" if no pool limit
            elif "Available" in panel_text:
                available_text = next((f"{parts[i+1]}" for i, x in enumerate(parts) if x == "Available:"), "0")
                available_amount = float(available_text.replace(',', ''))
                sell_percentage = random.uniform(0.20, 0.95)
                amount = math.floor(available_amount * sell_percentage)
                self.after(0, lambda p=int(sell_percentage*100), a=amount: self.update_status(f"{log_prefix} No limit. Selling {p}% ({a})"))
                return amount
            else:
                self.after(0, lambda: self.update_status(f"{log_prefix} Could not find sellable amount on page.", is_error=True))
                return 0
        except Exception as e:
            self.after(0, lambda err=e: self.update_status(f"{log_prefix} Failed to scrape sell amount after reload: {err}", is_error=True))
            return 0




















    def _trade_via_api(self, token_symbol, trade_type, amount, worker_name="API", on_complete=None):
        """Executes a trade using the direct API endpoint."""
        log_prefix = f"[{worker_name}:{token_symbol}]"
        self.after(0, lambda: self.update_status(f"{log_prefix} Firing {trade_type} API for {amount}..."))

        trade_successful = False
        try:
            if not self.session_cookie:
                self.after(0, lambda: self.update_status(f"❌ {log_prefix} Trade failed: No session cookie.", is_error=True))
                return False

            url = TRADE_API_URL_TEMPLATE.format(token_symbol=token_symbol)
            headers = {
                'User-Agent': USER_AGENT,
                'Content-Type': 'application/json',
                'Origin': BASE_URL,
                'Referer': f'{BASE_URL}/coin/{token_symbol}',
                'Cookie': self.session_cookie
            }
            payload = {"type": trade_type.upper(), "amount": float(amount)}

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=15)

                if response.status_code in [200, 204] and not response.text:
                    self.after(0, lambda: self.update_status(f"✅ {log_prefix} Trade successful (No Content response)."))
                    threading.Thread(target=self._check_balance).start()
                    trade_successful = True
                else:
                    response_data = response.json()
                    if response.status_code == 200 and response_data.get('success'):
                        self.after(0, lambda: self.update_status(f"✅ {log_prefix} Trade successful!"))
                        threading.Thread(target=self._check_balance).start()
                        trade_successful = True
                    else:
                        error_msg = response_data.get('message', response.text)
                        self.after(0, lambda: self.update_status(f"❌ {log_prefix} Trade failed: '{error_msg}'.", is_error=True))
            except requests.exceptions.RequestException as e:
                self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Trade request error: {err}", is_error=True))
            except json.JSONDecodeError:
                self.after(0, lambda: self.update_status(f"❌ {log_prefix} Trade failed: Invalid JSON in response: {response.text}", is_error=True))

        finally:
            # FIX: Execute the on_complete callback to re-enable UI elements
            if on_complete:
                self.after(0, on_complete)
            return trade_successful

    def _create_notebook(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.grid(row=1, column=0, sticky="nsew", pady=5)

        manual_tab = self._create_manual_tab(notebook)
        sniper_tab = self._create_sniper_tab(notebook)
        random_tab = self._create_random_tab(notebook)

        notebook.add(manual_tab, text="Manual")
        notebook.add(sniper_tab, text="Sniper Bot")
        notebook.add(random_tab, text="Random Bot")
        return notebook

    def _create_manual_tab(self, parent):
        tab = ttk.Frame(parent, padding="10")
        tab.columnconfigure(0, weight=1)

        # Token Selection
        token_frame = ttk.Frame(tab)
        token_frame.grid(row=0, column=0, pady=10, sticky="ew")
        ttk.Label(token_frame, text="Select Token:").pack(side=tk.LEFT, padx=5)
        self.token_menu = ttk.OptionMenu(token_frame, self.selected_token_symbol, "Loading...", command=lambda _: self._calculate_trade_amount_display('SELL'))
        self.token_menu.pack(side=tk.LEFT, padx=5, expand=True, fill="x")

        # Sell All Button
        self.sell_all_button = ttk.Button(tab, text="🔥 Sell All Tokens 🔥", command=self._start_sell_all_thread)
        self.sell_all_button.grid(row=1, column=0, pady=(5, 10))


        # Buy/Sell Frames
        self._create_trade_frame(tab, "Buy", self.buy_percentage, 2)
        self._create_trade_frame(tab, "Sell", self.sell_percentage, 3)
        return tab

    def _create_trade_frame(self, parent, trade_type, percentage_var, grid_row):
        is_buy = trade_type == "Buy"
        amount_label = "Amount (USD):" if is_buy else "Amount (Tokens):"

        frame = ttk.LabelFrame(parent, text=trade_type, padding=(10, 5))
        frame.grid(row=grid_row, column=0, padx=10, pady=5, sticky="ew")
        frame.columnconfigure(1, weight=1)

        # Percentage Radio Buttons
        ttk.Label(frame, text="Percentage:").grid(row=0, column=0, padx=5, sticky="e")
        radio_frame = ttk.Frame(frame)
        radio_frame.grid(row=0, column=1, sticky="w")
        for option in ["25%", "50%", "75%", "95%"]:
            rb = ttk.Radiobutton(radio_frame, text=option, variable=percentage_var, value=option, command=lambda tt=trade_type: self._calculate_trade_amount_display(tt))
            rb.pack(side=tk.LEFT, padx=2)

        # Amount Entry
        ttk.Label(frame, text=amount_label).grid(row=1, column=0, padx=5, pady=2, sticky="e")
        amount_entry = ttk.Entry(frame, width=25)
        amount_entry.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        amount_entry.insert(0, "0")
        amount_entry.bind("<KeyRelease>", lambda event: percentage_var.set(""))

        # Trade Button
        button = ttk.Button(frame, text=f"{trade_type} Selected Token", command=lambda tt=trade_type.upper(): self._execute_trade(tt))
        button.grid(row=2, column=0, columnspan=2, pady=5)

        # Store references
        if is_buy:
            self.buy_amount_entry = amount_entry
            self.buy_button = button
        else:
            self.sell_amount_entry = amount_entry
            self.sell_button = button

    def _create_sniper_tab(self, parent):
        tab = ttk.Frame(parent, padding="10")
        tab.columnconfigure(0, weight=1)

        config_frame = ttk.LabelFrame(tab, text="Configuration", padding=10)
        config_frame.grid(row=0, column=0, sticky="ew")
        config_frame.columnconfigure(1, weight=1)

        # Fixed Amount Entry
        ttk.Label(config_frame, text="Amount (USD):").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.sniper_buy_amount_entry = ttk.Entry(config_frame, width=25)
        self.sniper_buy_amount_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.sniper_buy_amount_entry.bind("<KeyRelease>", lambda event: self.sniper_buy_percentage.set(""))

        # Percentage Radio Buttons
        ttk.Label(config_frame, text="Percentage:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        sniper_radio_frame = ttk.Frame(config_frame)
        sniper_radio_frame.grid(row=1, column=1, sticky="w")
        for option in ["25%", "50%", "75%", "95%"]:
            rb = ttk.Radiobutton(sniper_radio_frame, text=option, variable=self.sniper_buy_percentage, value=option, command=lambda: self.sniper_buy_amount_entry.delete(0, tk.END))
            rb.pack(side=tk.LEFT, padx=2)

        self.sniper_bot_button = ttk.Button(tab, text="Start Sniper Bot", command=self._toggle_sniper_bot, state=tk.DISABLED)
        self.sniper_bot_button.grid(row=1, column=0, pady=20)
        return tab

    def _create_random_tab(self, parent):
        tab = ttk.Frame(parent, padding="10")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        config_frame = ttk.LabelFrame(tab, text="Configuration", padding=10)
        config_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        ttk.Label(config_frame, text="Max Buy (USD):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.random_max_buy_entry = ttk.Entry(config_frame, width=15)
        self.random_max_buy_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.random_max_buy_entry.insert(0, "10") # Default value

        self.random_bot_button = ttk.Button(tab, text="Start Random Bot", command=self._toggle_random_bot, state=tk.DISABLED)
        self.random_bot_button.grid(row=1, column=0, pady=20)
        ttk.Label(tab, text="Note: Select a token in the 'Manual' tab first.").grid(row=2, column=0, pady=5)
        return tab

    def _create_bottom_controls(self, parent):
        bottom_frame = ttk.Frame(parent)
        bottom_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        bottom_frame.columnconfigure(0, weight=1)

        self.recent_coins_button = ttk.Button(bottom_frame, text="Show/Hide Recent Coins", command=self._toggle_recent_coins_window)
        self.recent_coins_button.pack(pady=5)

    def _create_status_bar(self, parent):
        status_frame = ttk.Frame(parent)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        status_frame.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1) # Push status label to the bottom

        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("Arial", 10), wraplength=530)
        self.status_label.grid(row=0, column=0, sticky="sw")

        debug_frame = ttk.Frame(status_frame)
        debug_frame.grid(row=1, column=0, sticky="w")

        self.debug_checkbox = ttk.Checkbutton(debug_frame, text="Debug Mode", variable=self.debug_var, command=self._toggle_debug_mode)
        self.debug_checkbox.pack(side=tk.LEFT)
        self.history_button = ttk.Button(debug_frame, text="History", command=self._toggle_log_history_window)
        if DEBUG_MODE:
            self.history_button.pack(side=tk.LEFT, padx=10)

    # --- GUI Update & Helpers ---
    def update_status(self, gui_message, console_message=None, is_error=False):
        if not self.winfo_exists(): return

        timestamp = datetime.now().strftime("%H:%M:%S")
        log_prefix = "[ERROR]" if is_error else "[CONSOLE]"
        message_to_log = f"{timestamp} {log_prefix} {console_message or gui_message}"

        print(message_to_log)
        self.log_history.append(message_to_log)

        # Update external history window if open
        if self.log_text_widget and self.log_text_widget.winfo_exists():
            self.log_text_widget.config(state=tk.NORMAL)
            self.log_text_widget.insert(tk.END, message_to_log + "\n")
            self.log_text_widget.see(tk.END)
            self.log_text_widget.config(state=tk.DISABLED)

        # Update main status label
        self.status_var.set(gui_message)
        self.status_label.config(foreground="red" if is_error else "black")
        self.update_idletasks()

    def _update_balance_labels(self, portfolio_data):
        base_balance = float(portfolio_data.get("baseCurrencyBalance", 0.0))
        total_value = float(portfolio_data.get("totalCoinValue", 0.0))
        currency = portfolio_data.get("currency", "$")

        self.balance_var.set(f"Balance (USD): {currency}{base_balance:.2f}")
        self.portfolio_var.set(f"Portfolio Value: {currency}{total_value:.2f}")

        self.update_status("Balance check successful!", "GUI balance labels updated.")
        self._calculate_trade_amount_display('BUY')
        self._calculate_trade_amount_display('SELL')

    def _populate_token_dropdown(self, coin_holdings_data):
        self.current_coin_holdings = coin_holdings_data
        token_symbols = sorted([h.get("symbol", "N/A") for h in coin_holdings_data if h.get("symbol")])

        menu = self.token_menu['menu']
        menu.delete(0, 'end')

        if not token_symbols:
            token_symbols = ["No Tokens Found"]
            self.selected_token_symbol.set(token_symbols[0])
        else:
             for symbol in token_symbols:
                menu.add_command(label=symbol, command=tk._setit(self.selected_token_symbol, symbol, self._on_token_select))

        if self.selected_token_symbol.get() not in token_symbols and token_symbols:
             self.selected_token_symbol.set(token_symbols[0])

        self._on_token_select(self.selected_token_symbol.get())
        self.update_status("Token list updated.", "Token dropdown populated.")

    def _on_token_select(self, selection):
        self._calculate_trade_amount_display('SELL')

    def _calculate_trade_amount_display(self, trade_type):
        is_buy = trade_type.upper() == 'BUY'
        amount_entry = self.buy_amount_entry if is_buy else self.sell_amount_entry
        try:
            percentage_var = self.buy_percentage if is_buy else self.sell_percentage

            percentage_str = percentage_var.get()
            if not percentage_str: return

            percentage = float(percentage_str.replace('%', '')) / 100.0

            if is_buy:
                balance_str = self.balance_var.get().split('$')[-1]
                available_balance = float(balance_str)
                calculated_amount = math.floor(available_balance * percentage)
            else: # SELL
                selected_symbol = self.selected_token_symbol.get()
                holding = next((h for h in self.current_coin_holdings if h.get("symbol") == selected_symbol), None)
                holding_quantity = float(holding.get("quantity", 0.0)) if holding else 0.0
                calculated_amount = math.floor(holding_quantity * percentage)

            amount_entry.delete(0, tk.END)
            amount_entry.insert(0, str(calculated_amount))
        except (ValueError, IndexError):
            amount_entry.delete(0, tk.END)
            amount_entry.insert(0, "0")

    # --- Selenium & Trading Logic ---
    def _run_selenium_thread(self, initial_run=False):
        global HEADLESS_MODE
        if self.selenium_driver and self.api.is_browser_open():
            self.selenium_driver.quit()
        self.selenium_driver = None

        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
        options.add_argument("--window-size=1280,720")
        if not initial_run and HEADLESS_MODE:
            options.add_argument("--headless=new")
            status_msg = "Opening browser in headless mode..."
        else:
            status_msg = "Opening browser for manual login..." if initial_run else "Opening browser in normal mode..."

        self.after(0, lambda: self.update_status(status_msg))

        try:
            service = Service(CHROMEDRIVER_PATH)
            self.selenium_driver = webdriver.Chrome(service=service, options=options)
            self.api = RugplayAPI(self.selenium_driver)
            self.selenium_driver.get(BASE_URL)

            if initial_run:
                self.after(0, lambda: self.update_status("Browser open. Please log in, then click 'Proceed'."))
                self.after(0, lambda: self.action_button.config(state=tk.NORMAL))
            else:
                self.after(0, lambda: self.update_status("Browser is ready."))
                self.after(0, lambda: self.action_button.config(state=tk.NORMAL))
                if not self.sniper_bot_active and not self.random_bot_active:
                    self.sniper_bot_button.config(state=tk.NORMAL)
                    self.random_bot_button.config(state=tk.NORMAL)
                threading.Thread(target=self._check_balance).start()
        except Exception as e:
            self.after(0, lambda e=e: self.update_status(f"Failed to start browser: {e}", is_error=True))
            self.after(0, lambda: self.action_button.config(state=tk.DISABLED))

    def _proceed_after_login(self):
        global HEADLESS_MODE
        if not self.api or not self.api.is_browser_open(): return

        self.action_button.config(state=tk.DISABLED)

        # Perform an initial balance check to confirm login
        portfolio_data = self.api.get_portfolio()
        if 'error' in portfolio_data:
            self.update_status(f"Login/Session Check Failed: {portfolio_data['error']}", is_error=True)
            self.action_button.config(state=tk.NORMAL)
            return

        # --- CAPTURE SESSION COOKIE ---
        try:
            cookies = self.selenium_driver.get_cookies()
            if not cookies:
                self.update_status("Could not retrieve session cookie. Please try again.", is_error=True)
                self.action_button.config(state=tk.NORMAL)
                return
            self.session_cookie = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            self.update_status("Session cookie captured successfully.", "Auth cookie stored.")
        except Exception as e:
            self.update_status(f"Error capturing cookie: {e}", is_error=True)
            self.action_button.config(state=tk.NORMAL)
            return
        # --- END OF COOKIE CAPTURE ---

        self._update_balance_labels(portfolio_data)
        self._populate_token_dropdown(portfolio_data.get("coinHoldings", []))

        # Reconfigure button for future use
        self.action_button.config(text="Restart & Refresh", command=lambda: threading.Thread(target=self._run_selenium_thread).start())

        # Switch to headless mode if not debugging
        if not DEBUG_MODE:
            HEADLESS_MODE = True
            self.update_status("Login confirmed. Switching to headless mode...")
            threading.Thread(target=self._run_selenium_thread).start()
        else:
            self.update_status("Login confirmed. Debug mode is ON, staying in normal browser.")
            self.action_button.config(state=tk.NORMAL)

    def _check_balance(self):
        if not self.api or not self.api.is_browser_open(): return

        self.after(0, lambda: self.update_status("Checking balance...", f"Requesting {PORTFOLIO_API_URL}"))
        portfolio_data = self.api.get_portfolio()

        if 'error' in portfolio_data:
            msg = portfolio_data['error']
            self.after(0, lambda: self.update_status(f"Balance check failed: {msg}", is_error=True))
            if "HTML" in msg:
                self.after(0, lambda: self.update_status("Refreshing page to fix session..."))
                self.selenium_driver.refresh()
        else:
            self.after(0, lambda: self._update_balance_labels(portfolio_data))
            self.after(0, lambda: self._populate_token_dropdown(portfolio_data.get("coinHoldings", [])))

    def _execute_trade(self, trade_type):
        token_symbol = self.selected_token_symbol.get()
        amount_entry = self.buy_amount_entry if trade_type == 'BUY' else self.sell_amount_entry
        amount_str = amount_entry.get()

        if token_symbol in ["Loading...", "No Tokens Found"]:
            messagebox.showerror("Error", "Please select a valid token.")
            return
        try:
            amount = float(amount_str)
            if amount <= 0: raise ValueError("Amount must be positive.")
        except ValueError:
            messagebox.showerror("Invalid Amount", "Please enter a valid positive number for the trade.")
            return

        self.buy_button.config(state=tk.DISABLED)
        self.sell_button.config(state=tk.DISABLED)

        # --- Check Debug Mode ---
        if DEBUG_MODE:
            self.update_status(f"[DEBUG] Using UI method for {trade_type} {token_symbol}.")
            threading.Thread(target=self._trade_token_flow, args=(token_symbol, trade_type, amount, self.selenium_driver, "Manual")).start()
        else:
            # Pass the callback function to re-enable the buttons on completion
            threading.Thread(target=self._trade_via_api, args=(token_symbol, trade_type, amount, "Manual", self._finalize_manual_trade_ui)).start()
        # --- End Check ---
        # The incorrect self.after(3000, ...) lines have been removed.


    def _trade_token_flow(self, token_symbol, trade_type, amount, driver, worker_name="Manual"):
        log_prefix = f"[{worker_name}:{token_symbol}]"
        self.after(0, lambda: self.update_status(f"{log_prefix} Starting {trade_type} for {amount}..."))

        trade_successful = False
        try:
            coin_page_url = f"{BASE_URL}/coin/{token_symbol}"
            if driver.current_url != coin_page_url:
                self.after(0, lambda: self.update_status(f"{log_prefix} Navigating to coin page..."))
                driver.get(coin_page_url)

            WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, TRADE_BUTTON_XPATH_TEMPLATE.format(trade_type='buy')))
            )

            trade_button_xpath = TRADE_BUTTON_XPATH_TEMPLATE.format(trade_type=trade_type.lower())
            trade_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, trade_button_xpath)))
            trade_button.click()
            self.after(0, lambda: self.update_status(f"{log_prefix} Clicked '{trade_type.upper()}' tab."))

            amount_input = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.XPATH, AMOUNT_INPUT_XPATH)))
            amount_input.clear()
            amount_input.send_keys(str(amount))
            self.after(0, lambda: self.update_status(f"{log_prefix} Entered amount: {amount}"))

            confirm_xpath = CONFIRM_BUTTON_XPATH_TEMPLATE.format(trade_type=trade_type.lower(), token_symbol=token_symbol.lower())
            confirm_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, confirm_xpath)))
            driver.execute_script("arguments[0].click();", confirm_button)

            outcome_element = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'successful') or contains(text(), 'failed')]")))
            if 'successful' in outcome_element.text.lower():
                self.after(0, lambda: self.update_status(f"✅ {log_prefix} Trade successful!"))
                WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.XPATH, DIALOG_CONTENT_XPATH)))
                trade_successful = True
            else:
                self.after(0, lambda: self.update_status(f"❌ {log_prefix} Trade failed: '{outcome_element.text}'.", is_error=True))

        except Exception as e:
            self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Trade failed with exception: {err}", is_error=True))

        finally:
            # FIX: Only re-enable buttons if it was a manual trade
            if worker_name == "Manual":
                self.after(0, self._finalize_manual_trade_ui)
            return trade_successful



    def _start_sell_all_thread(self):
        """Starts the sell-all process in a dedicated thread."""
        if messagebox.askyesno("Confirm Sell All", "Are you sure you want to sell ALL tokens in your portfolio? This action cannot be undone."):
            self.update_status("Starting Sell All process...", "User confirmed sell all.")
            self.sell_all_button.config(state=tk.DISABLED)
            self.buy_button.config(state=tk.DISABLED)
            self.sell_button.config(state=tk.DISABLED)
            threading.Thread(target=self._sell_all_tokens_flow, daemon=True).start()

    def _sell_all_tokens_flow(self):
        """The main logic for selling all tokens, executed in a thread."""
        if not self.api or not self.api.is_browser_open():
            self.after(0, lambda: self.update_status("Sell All failed: Browser not open.", is_error=True))
            return

        # Check for session cookie if not in debug mode
        if not DEBUG_MODE and not self.session_cookie:
            self.after(0, lambda: self.update_status("Sell All failed: API session not ready.", is_error=True))
            self._finalize_sell_all_ui()
            return

        self.after(0, lambda: self.update_status("Fetching portfolio for sell-all...", "Requesting portfolio API."))
        portfolio_data = self.api.get_portfolio()
        if 'error' in portfolio_data:
            self.after(0, lambda: self.update_status(f"Could not get portfolio: {portfolio_data['error']}", is_error=True))
            self._finalize_sell_all_ui()
            return

        holdings = portfolio_data.get("coinHoldings", [])
        tokens_to_sell = [(h['symbol'], float(h.get('quantity', 0))) for h in holdings if h.get('symbol') and float(h.get('quantity', 0)) > 0.0001]

        if not tokens_to_sell:
            self.after(0, lambda: self.update_status("Portfolio is empty. Nothing to sell."))
            self._finalize_sell_all_ui()
            return

        self.after(0, lambda: self.update_status(f"Found {len(tokens_to_sell)} tokens to sell."))

        for token_symbol, quantity in tokens_to_sell:
            # --- Check Debug Mode ---
            if DEBUG_MODE:
                self.after(0, lambda t=token_symbol: self.update_status(f"[DEBUG] Using UI method to sell {t}"))
                self._sell_max_for_token(self.selenium_driver, token_symbol)
            else:
                self.after(0, lambda t=token_symbol, q=quantity: self.update_status(f"Selling all {q} of {t} via API"))
                self._trade_via_api(token_symbol, 'SELL', quantity, "SellAll")
            # --- End Check ---
            time.sleep(1)

        self.after(0, lambda: self.update_status("✅ Sell All process complete."))
        threading.Thread(target=self._check_balance).start()
        self._finalize_sell_all_ui()

    def _sell_max_for_token(self, driver, token_symbol):
        """Performs a single max sell for a given token, updating the GUI."""
        self.after(0, lambda t=token_symbol: self.update_status(f"Attempting MAX SELL for: {t}"))
        try:
            coin_page_url = f"{BASE_URL}/coin/{token_symbol}"
            if driver.current_url != coin_page_url:
                self.after(0, lambda: driver.get(coin_page_url))
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            sell_tab = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, SELL_TAB_XPATH)))
            driver.execute_script("arguments[0].click();", sell_tab)

            max_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, MAX_BUTTON_XPATH)))
            driver.execute_script("arguments[0].click();", max_button)

            confirm_xpath = CONFIRM_SELL_BUTTON_XPATH_TEMPLATE.format(token_symbol=token_symbol.lower())
            confirm_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, confirm_xpath)))
            driver.execute_script("arguments[0].click();", confirm_button)

            outcome_element = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'successful') or contains(text(), 'failed')]")))
            outcome_text = outcome_element.text

            if 'successful' in outcome_text.lower():
                self.after(0, lambda t=token_symbol, o=outcome_text: self.update_status(f"✅ SELL SUCCESSFUL for {t}. Message: '{o}'"))
                WebDriverWait(driver, 5).until(EC.invisibility_of_element_located((By.XPATH, DIALOG_CONTENT_XPATH)))
            else:
                self.after(0, lambda t=token_symbol, o=outcome_text: self.update_status(f"❌ SELL FAILED for {t}. Message: '{o}'.", is_error=True))

        except TimeoutException:
            self.after(0, lambda t=token_symbol: self.update_status(f"Timeout selling {t}. Token might be gone.", is_error=True))
        except Exception as e:
            self.after(0, lambda t=token_symbol, err=e: self.update_status(f"An error occurred selling {t}: {err}", is_error=True))



    def _toggle_random_bot(self):
        self.random_bot_active = not self.random_bot_active

        if self.random_bot_active:
            if not self.api or not self.api.is_browser_open():
                messagebox.showerror("Error", "Browser is not running. Please start it first.")
                self.random_bot_active = False
                return

            token_symbol = self.selected_token_symbol.get()
            if token_symbol in ["Loading...", "No Tokens Found"]:
                messagebox.showerror("Error", "Please select a token from the 'Manual' tab before starting this bot.")
                self.random_bot_active = False
                return

            # --- Start Bot: Disable conflicting controls ---
            self.random_bot_button.config(text="Stop Random Bot")
            self.sniper_bot_button.config(state=tk.DISABLED)
            self.notebook.tab(0, state="disabled") # Manual Tab
            self.notebook.tab(1, state="disabled") # Sniper Tab

            self.random_bot_thread = threading.Thread(target=self._random_bot_logic, daemon=True)
            self.random_bot_thread.start()
        else:
            # --- Stop Bot: Re-enable all controls ---
            self.random_bot_button.config(text="Start Random Bot")
            self.sniper_bot_button.config(state=tk.NORMAL)
            self.notebook.tab(0, state="normal")
            self.notebook.tab(1, state="normal")
            self.update_status("Random Bot Stopped.")




    def _random_bot_logic(self):
        self.after(0, lambda: self.update_status("Random Bot Activated!", "Random bot thread started."))
        last_trade_type = 'SELL'  # Start by buying first

        while self.random_bot_active:
            try:
                # Check for valid session and browser state
                if (not self.session_cookie) or (not self.api.is_browser_open()):
                    self.after(0, lambda: self.update_status("Session/Browser not ready, stopping bot.", is_error=True))
                    self.after(0, self._toggle_random_bot)
                    break

                token_symbol = self.selected_token_symbol.get()
                trade_type = 'BUY' if last_trade_type == 'SELL' else 'SELL'
                trade_successful = False
                amount = 0

                if trade_type == 'BUY':
                    balance_str = self.balance_var.get().split('$')[-1]
                    available_balance = float(balance_str.replace(',', ''))

                    try:
                        # Get the user-defined max buy limit from the UI
                        max_buy_limit = float(self.random_max_buy_entry.get())
                    except ValueError:
                        max_buy_limit = 10.0 # Default to 10 if input is invalid

                    if available_balance > 1:
                        # Determine the max possible buy, respecting the user's limit
                        max_buy = min(available_balance * 0.80, max_buy_limit)
                        if max_buy > 1:
                            # Calculate a more random amount within the allowed range
                            amount = math.floor(random.uniform(max_buy * 0.20, max_buy * 0.95))

                    if amount > 0:
                        # Use the fast API to buy
                        trade_successful = self._trade_via_api(token_symbol, trade_type, amount, "RandomBot")

                    last_trade_type = 'BUY' # Set type for next iteration

                else:  # SELL logic
                    # Use the robust scraping method to determine the sell amount
                    amount = self._scrape_and_calculate_sell_amount(token_symbol)

                    if amount > 0:
                        # Use the fast API to sell the scraped amount
                        trade_successful = self._trade_via_api(token_symbol, trade_type, amount, "RandomBot")

                    last_trade_type = 'SELL' # Set type for next iteration

            except Exception as e:
                self.after(0, lambda e=e: self.update_status(f"Critical error in random bot: {e}", is_error=True))
                time.sleep(2) # Keep a small sleep only for critical error cases












    def _toggle_sniper_bot(self):
        self.sniper_bot_active = not self.sniper_bot_active

        if self.sniper_bot_active:
            if not self.api or not self.api.is_browser_open():
                messagebox.showerror("Error", "Browser is not running. Please start it first.")
                self.sniper_bot_active = False
                return
            if not self.sniper_buy_amount_entry.get() and not self.sniper_buy_percentage.get():
                messagebox.showerror("Input Error", "Please set a buy amount or a percentage.")
                self.sniper_bot_active = False
                return

            self.sniper_bot_button.config(text="Stop Sniper Bot")
            self.random_bot_button.config(state=tk.DISABLED)
            self.notebook.tab(0, state="disabled")
            self.notebook.tab(2, state="disabled")

            # --- Setup for the hybrid model ---
            self.snipe_queue = []
            self.worker_id_counter = itertools.count(1)

            # --- Launch scanner and the NEW buy-only action thread ---
            self.scanner_thread = threading.Thread(target=self._sniper_scanner_logic, daemon=True)
            self.buy_thread = threading.Thread(target=self._sniper_buy_logic, daemon=True)
            self.scanner_thread.start()
            self.buy_thread.start()
        else:
            # --- Stop Bot: Re-enable all controls ---
            self.sniper_bot_button.config(text="Start Sniper Bot")
            self.random_bot_button.config(state=tk.NORMAL)
            self.notebook.tab(0, state="normal")
            self.notebook.tab(2, state="normal")
            self.update_status("Sniper Bot Stopped.")

    def _sniper_scanner_logic(self):
        """Finds new coins and adds them to the buy queue."""
        last_seen_coin_symbol = None
        self.after(0, lambda: self.update_status("[SCANNER] Starting scan for new coins..."))
        try:
            initial_coin_data = self.api.get_newest_coin()
            if initial_coin_data.get("coins"):
                last_seen_coin_symbol = initial_coin_data["coins"][0].get('symbol')
        except Exception: pass

        while self.sniper_bot_active:
            time.sleep(0.5)
            try:
                newest_coin_data = self.api.get_newest_coin()
                current_newest = newest_coin_data.get("coins", [{}])[0].get('symbol') if newest_coin_data.get("coins") else last_seen_coin_symbol
                gui_msg = f"[SNIPER] Monitoring... Newest: {current_newest or 'N/A'}"
                console_msg = f"Scanning for new coins... Current newest found: {current_newest or 'N/A'}"
                self.after(0, lambda gm=gui_msg, cm=console_msg: self.update_status(gm, cm))

                if newest_coin_data.get("coins"):
                    newest_symbol = newest_coin_data["coins"][0].get('symbol')
                    if newest_symbol and newest_symbol != last_seen_coin_symbol:
                        self.after(0, lambda s=newest_symbol: self.update_status(f"✨ [SCANNER] New coin detected: {s}! Added to buy queue."))
                        last_seen_coin_symbol = newest_symbol
                        self.snipe_queue.append(newest_symbol)
            except Exception:
                time.sleep(2)
                continue

    def _sniper_buy_logic(self):
        """Processes the buy queue sequentially using the fast main browser."""
        self.after(0, lambda: self.update_status("[BUY-THREAD] Waiting for coins in queue..."))
        while self.sniper_bot_active:
            if self.snipe_queue:
                token_symbol = self.snipe_queue.pop(0)
                log_prefix = f"[BUY-THREAD:{token_symbol}]"
                self.after(0, lambda: self.update_status(f"{log_prefix} Processing buy..."))

                try:
                    buy_amount = 0
                    fixed_amount = self.sniper_buy_amount_entry.get()
                    if fixed_amount:
                        buy_amount = int(fixed_amount)
                    else:
                        percentage = float(self.sniper_buy_percentage.get().replace('%', '')) / 100.0
                        balance_str = self.balance_var.get().split('$')[-1]
                        buy_amount = math.floor(float(balance_str) * percentage)

                    if buy_amount < 1:
                        self.after(0, lambda a=buy_amount: self.update_status(f"{log_prefix} Insufficient amount ({a}). Skipping."))
                        continue

                    # Execute the buy using the main driver
                    buy_successful = self._trade_via_api(token_symbol, 'BUY', buy_amount, "SniperAPI")

                    if buy_successful:
                        # --- Launch the parallel post-buy worker ---
                        worker_id = next(self.worker_id_counter)
                        self.after(0, lambda s=token_symbol, w_id=worker_id: self.update_status(f"✅ {log_prefix} Buy successful! Spawning Worker-{w_id} for monitoring."))

                        worker_thread = threading.Thread(target=self._snipe_post_buy_worker, args=(token_symbol, worker_id), daemon=True)
                        worker_thread.start()
                    else:
                        self.after(0, lambda: self.update_status(f"❌ {log_prefix} Buy failed."))

                except Exception as e:
                    self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Critical buy error: {err}", is_error=True))
            else:
                time.sleep(0.2)

    def _snipe_post_buy_worker(self, token_symbol, worker_id):
        """Monitors and sells a single coin using the robust, UI-scraping sell logic."""
        worker_name = f"Worker-{worker_id}"
        log_prefix = f"[{worker_name}:{token_symbol}]"
        dedicated_driver = None
        temp_profile_path = ""

        # --- Helper function for recovery, now lives inside the worker ---
        def recover_with_hard_reload(driver, thread_api, reason=""):
            self.after(0, lambda r=reason: self.update_status(f"⚠️ {log_prefix} {r}. Initiating recovery..."))
            if not driver or not thread_api.is_browser_open():
                self.after(0, lambda: self.update_status(f"{log_prefix} Browser not found during recovery.", is_error=True))
                return False
            try:
                coin_page_url = f"{BASE_URL}/coin/{token_symbol}"
                if driver.current_url != coin_page_url:
                    driver.get(coin_page_url)

                driver.execute_cdp_cmd('Storage.clearDataForOrigin', {
                    'origin': BASE_URL,
                    'storageTypes': 'appcache,cache_storage,file_systems,indexeddb,shader_cache,websql'
                })
                driver.execute_cdp_cmd('ServiceWorker.enable', {})
                driver.execute_cdp_cmd('ServiceWorker.stopAllWorkers', {})
                driver.execute_cdp_cmd('Network.setCacheDisabled', {'cacheDisabled': True})
                driver.execute_cdp_cmd('Page.reload', {'ignoreCache': True})

                WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, SELL_TAB_XPATH)))
                self.after(0, lambda: self.update_status(f"✅ {log_prefix} Recovery successful. Page is ready."))
                return True
            except Exception as e:
                self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Recovery failed: {err}", is_error=True))
                return False

        try:
            # 1. Setup browser clone
            self.after(0, lambda: self.update_status(f"🛠️ {log_prefix} Cloning profile..."))
            source_profile = CHROME_USER_DATA_DIR
            temp_profile_path = tempfile.mkdtemp(suffix=f"_worker_{worker_id}")
            ignore_patterns = shutil.ignore_patterns('Singleton*', 'lockfile', '*Cache*', '*Code Cache*', '*ShaderCache*')
            shutil.copytree(source_profile, temp_profile_path, dirs_exist_ok=True, ignore=ignore_patterns)

            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument(f"--user-data-dir={temp_profile_path}")
            options.add_argument("--window-size=1280,720")
            if not DEBUG_MODE:
                options.add_argument("--headless=new")

            service = Service(CHROMEDRIVER_PATH)
            dedicated_driver = webdriver.Chrome(service=service, options=options)
            thread_api = RugplayAPI(dedicated_driver)

            dedicated_driver.get(BASE_URL)
            WebDriverWait(dedicated_driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            self.after(0, lambda: self.update_status(f"✅ {log_prefix} Worker browser ready. Starting monitoring..."))

            # 2. Monitor for new buyers
            monitoring_duration = 180
            new_buyer_found = False
            initial_holders_data = thread_api.get_token_holders(token_symbol)
            if 'error' in initial_holders_data:
                raise Exception(f"API error getting initial holders: {initial_holders_data['error']}")

            target_holder_count = len(initial_holders_data.get('holders', [])) + 1

            for i in range(monitoring_duration):
                if not self.sniper_bot_active: break
                current_holders_data = thread_api.get_token_holders(token_symbol)
                if 'error' in current_holders_data:
                    time.sleep(1)
                    continue

                current_holder_count = len(current_holders_data.get('holders', []))
                time_left = monitoring_duration - i
                self.after(0, lambda: self.update_status(f"{log_prefix} Monitoring... {time_left}s left | Holders: {current_holder_count}/{target_holder_count}"))

                if current_holder_count >= target_holder_count:
                    self.after(0, lambda c=current_holder_count: self.update_status(f"✅ {log_prefix} New buyer detected! Holders: {c}."))
                    new_buyer_found = True
                    break
                time.sleep(1)

            if not new_buyer_found:
                self.after(0, lambda: self.update_status(f"{log_prefix} Monitoring timed out. Selling anyway."))

            # --- START OF CORRECTED SELL LOGIC ---
            self.after(0, lambda: self.update_status(f"⏳ {log_prefix} Pausing before sell-off..."))
            time.sleep(1)

            if not recover_with_hard_reload(dedicated_driver, thread_api, "Preparing for sell-off"): return

            sell_attempt = 0
            while self.sniper_bot_active and sell_attempt < 10:
                sell_attempt += 1
                self.after(0, lambda s=sell_attempt: self.update_status(f"{log_prefix} Sell attempt #{s}."))
                try:
                    sell_tab_button = WebDriverWait(dedicated_driver, 15).until(EC.element_to_be_clickable((By.XPATH, SELL_TAB_XPATH)))
                    sell_tab_button.click()

                    panel_element = WebDriverWait(dedicated_driver, 10).until(EC.visibility_of_element_located((By.XPATH, "//input[@type='number' and @placeholder='0.00']/ancestor::div[2]")))
                    panel_text = panel_element.text
                    parts = panel_text.split()
                    available_text = next((f"{parts[i+1]}" for i, x in enumerate(parts) if x == "Available:"), "Not Found")
                    max_sellable_text = next((f"{parts[i+1]}" for i, x in enumerate(parts) if x == "sellable:"), "Not Found")
                    self.after(0, lambda: self.update_status(f"[DEBUG] {log_prefix} SCRAPED -> Available: {available_text} | Max sellable: {max_sellable_text}"))

                    if "Max sellable" in panel_text:
                        self.after(0, lambda: self.update_status(f"{log_prefix} Action: Pool limit detected. Selling max."))
                        WebDriverWait(dedicated_driver, 5).until(EC.element_to_be_clickable((By.XPATH, MAX_BUTTON_XPATH))).click()
                    elif "Available" in panel_text:
                        self.after(0, lambda: self.update_status(f"{log_prefix} Action: No pool limit. Selling 80%."))
                        available_amount_val = float(available_text.replace(',', ''))
                        final_amount = math.floor(available_amount_val * 0.80)
                        if final_amount < 1:
                            self.after(0, lambda: self.update_status(f"{log_prefix} Remainder too small. Ending cycle."))
                            break
                        amount_input_element = dedicated_driver.find_element(By.XPATH, AMOUNT_INPUT_XPATH)
                        amount_input_element.clear()
                        amount_input_element.send_keys(str(final_amount))
                    else:
                        raise Exception("Could not find 'Available' or 'Max sellable' text.")

                    confirm_button = WebDriverWait(dedicated_driver, 10).until(EC.element_to_be_clickable((By.XPATH, CONFIRM_SELL_BUTTON_XPATH_TEMPLATE.format(token_symbol=token_symbol.lower()))))
                    dedicated_driver.execute_script("arguments[0].click();", confirm_button)

                    outcome_element = WebDriverWait(dedicated_driver, 15).until(EC.visibility_of_element_located((By.XPATH, TRADE_OUTCOME_XPATH)))
                    outcome_text = outcome_element.text
                    if 'successful' in outcome_text.lower():
                        self.after(0, lambda o=outcome_text: self.update_status(f"✅ {log_prefix} Sell successful: '{o}'"))
                        WebDriverWait(dedicated_driver, 10).until(EC.invisibility_of_element_located((By.XPATH, DIALOG_CONTENT_XPATH)))
                        if "Max sellable" in panel_text:
                            self.after(0, lambda: self.update_status(f"{log_prefix} Pool limit sell complete. Re-evaluating..."))
                            time.sleep(1)
                            continue
                        else:
                            break
                    else:
                        raise Exception(f"Trade failed with message: '{outcome_text}'")
                except Exception as e:
                    if not recover_with_hard_reload(dedicated_driver, thread_api, f"Error on sell attempt #{sell_attempt}: {e}"):
                        return
                    continue
            # --- END OF CORRECTED SELL LOGIC ---

        except Exception as e:
            self.after(0, lambda err=e: self.update_status(f"❌ {log_prefix} Worker error: {err}", is_error=True))
        finally:
            if dedicated_driver:
                dedicated_driver.quit()
            if temp_profile_path and os.path.exists(temp_profile_path):
                shutil.rmtree(temp_profile_path, ignore_errors=True)
            self.after(0, lambda: self.update_status(f"🗑️ {log_prefix} Worker finished and cleaned up."))










# ... This is where the next method in the class starts, like _toggle_recent_coins_window ...


    # --- Window Management & Shutdown ---
    def _toggle_recent_coins_window(self):
        if self.recent_coins_window and self.recent_coins_window.winfo_exists():
            self.recent_coins_window.destroy()
            self.recent_coins_window = None
            return

        if not self.api or not self.api.is_browser_open():
            messagebox.showerror("Error", "Browser is not running.")
            return

        win = tk.Toplevel(self)
        self.recent_coins_window = win
        win.title("Recently Created Coins")
        win.geometry("600x400")

        tree_frame = ttk.Frame(win)
        tree_frame.pack(expand=True, fill="both", padx=10, pady=10)

        cols = ("Symbol", "Name", "Created At")
        tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        for col in cols: tree.heading(col, text=col)
        tree.pack(side="left", expand=True, fill="both")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        vsb.pack(side='right', fill='y')
        tree.configure(yscrollcommand=vsb.set)

        def refresh_data():
            for i in tree.get_children(): tree.delete(i)
            threading.Thread(target=self._fetch_and_display_recent_coins, args=(tree,)).start()

        ttk.Button(win, text="Refresh", command=refresh_data).pack(pady=5)
        refresh_data()

    def _fetch_and_display_recent_coins(self, tree):
        data = self.api.get_recent_coins()
        if 'error' in data or not tree.winfo_exists(): return

        for coin in data.get("coins", []):
            try:
                dt_obj = datetime.fromisoformat(coin.get("createdAt", "").replace('Z', '+00:00'))
                readable_date = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                readable_date = coin.get("createdAt", "N/A")

            if tree.winfo_exists():
                tree.insert("", "end", values=(coin.get("symbol", "N/A"), coin.get("name", "N/A"), readable_date))

    def _toggle_log_history_window(self):
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.destroy()
            self.history_window = None
            self.log_text_widget = None
            return

        win = tk.Toplevel(self)
        self.history_window = win
        win.title("Log History")
        win.geometry("800x500")
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_window_close(win, 'history_window', 'log_text_widget'))

        txt_frame = ttk.Frame(win)
        txt_frame.pack(expand=True, fill="both", padx=5, pady=5)
        log_text = tk.Text(txt_frame, wrap="word", font=("Courier New", 10))
        vsb = ttk.Scrollbar(txt_frame, orient="vertical", command=log_text.yview)
        log_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        log_text.pack(side="left", fill="both", expand=True)

        for entry in self.log_history: log_text.insert(tk.END, entry + "\n")
        log_text.see(tk.END)
        log_text.config(state=tk.DISABLED)
        self.log_text_widget = log_text

    def _toggle_debug_mode(self):
        global DEBUG_MODE, HEADLESS_MODE
        DEBUG_MODE = self.debug_var.get()
        HEADLESS_MODE = not DEBUG_MODE

        if DEBUG_MODE:
            self.history_button.pack(side=tk.LEFT, padx=10)
        else:
            self.history_button.pack_forget()
            if self.history_window and self.history_window.winfo_exists():
                self.history_window.destroy()

        self.update_status(f"Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}. Restarting browser...")
        self.action_button.config(text="Proceed After Login", command=self._proceed_after_login, state=tk.DISABLED)
        threading.Thread(target=self._run_selenium_thread).start()

    def _on_window_close(self, window, window_attr, widget_attr=None):
        """Generic handler for closing Toplevel windows."""
        if window and window.winfo_exists():
            window.destroy()
        setattr(self, window_attr, None)
        if widget_attr:
            setattr(self, widget_attr, None)

    def _on_closing(self):
        """Handles proper shutdown of Selenium and Tkinter."""
        self.sniper_bot_active = False
        self.random_bot_active = False
        if self.selenium_driver:
            print("[INFO] Quitting Selenium driver...")
            if self.api.is_browser_open():
                self.selenium_driver.quit()
            self.selenium_driver = None
        print("[INFO] Application closing.")
        self.destroy()
        sys.exit(0)


def signal_handler(sig, frame):
    """Handles Ctrl+C for graceful shutdown."""
    print("\n[INFO] Ctrl+C detected. Shutting down gracefully...")
    if app:
        app.after(0, app._on_closing)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    app = TradeApp()
    app.mainloop()
