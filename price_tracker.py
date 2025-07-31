import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import sqlite3
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import schedule
import time
import argparse
import os
import re
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
DATABASE = 'price_data.db'
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Connection': 'keep-alive'
}

# --- Database Functions ---

def setup_database():
    """Initializes the SQLite database and creates tables if they don't exist."""
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS products
                     (id INTEGER PRIMARY KEY, 
                     url TEXT UNIQUE, 
                     name TEXT,
                     threshold REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS price_history
                     (id INTEGER PRIMARY KEY,
                     product_id INTEGER,
                     price REAL,
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY(product_id) REFERENCES products(id))''')
        conn.commit()

def add_product(url, threshold, name=None):
    """Adds a new product to the database."""
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO products (url, name, threshold) VALUES (?, ?, ?)", 
                     (url, name, threshold))
            conn.commit()
            print(f"Product added: {name or url}")
        except sqlite3.IntegrityError:
            print("Product with this URL already exists in the database.")

def save_price(product_id, price):
    """Saves a new price entry for a product."""
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO price_history (product_id, price) VALUES (?, ?)",
                 (product_id, price))
        conn.commit()

# --- Web Scraping Functions ---

def parse_price(price_text):
    """
    FIX: Robustly parses price from text.
    Handles currency symbols, commas, and converts to float.
    Replaces the fragile .isdigit() check.
    """
    if price_text is None:
        return None
    # Use regex to find numbers (including decimals) and remove commas
    price_search = re.search(r'[\d,]+\.?\d*', price_text)
    if price_search:
        price_str = price_search.group(0).replace(',', '')
        try:
            return float(price_str)
        except (ValueError, TypeError):
            return None
    return None

def get_scraped_price(url):
    """Determines which scraper to use based on the URL's domain."""
    domain = url.split("//")[-1].split("/")[0]
    
    # Define selectors for each supported site. This makes it easier to update.
    site_selectors = {
        'amazon': [
            'span.a-price-whole', 
            '#priceblock_ourprice', 
            '#priceblock_dealprice',
            'span.priceToPay>span.a-offscreen' # More modern selector
        ],
        'flipkart': [
            'div._30jeq3._16Jk6d', 
            'div._30jeq3._1_WHN1'
        ]
    }

    scraper_to_use = None
    selectors = []

    if 'amazon' in domain:
        scraper_to_use = scrape_website
        selectors = site_selectors['amazon']
    elif 'flipkart' in domain:
        scraper_to_use = scrape_website
        selectors = site_selectors['flipkart']
    else:
        print(f"Unsupported website: {domain}")
        return None

    return scraper_to_use(url, selectors)

def scrape_website(url, selectors):
    """
    Generic scraping function for any website.
    Tries with requests/BeautifulSoup first, then falls back to Selenium.
    """
    # 1. Try with requests/BeautifulSoup (fast method)
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for selector in selectors:
            price_element = soup.select_one(selector)
            if price_element:
                price = parse_price(price_element.get_text())
                if price:
                    print(f"Successfully scraped price (fast method): {price}")
                    return price

    except requests.exceptions.RequestException as e:
        print(f"Requests failed: {e}. Trying with Selenium.")

    # 2. Fallback to Selenium (slower, for dynamic content)
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument(f"user-agent={HEADERS['User-Agent']}")
        
        # IMPORTANT: Ensure chromedriver is in your PATH or specify its location:
        # from selenium.webdriver.chrome.service import Service
        # service = Service(executable_path='/path/to/your/chromedriver')
        # driver = webdriver.Chrome(service=service, options=chrome_options)
        driver = webdriver.Chrome(options=chrome_options)
        
        driver.get(url)
        
        for selector in selectors:
            try:
                price_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                price = parse_price(price_element.text)
                if price:
                    print(f"Successfully scraped price (Selenium method): {price}")
                    return price
            except TimeoutException:
                # This is expected if a selector doesn't match, just try the next one
                continue 
                
    except WebDriverException as e:
        print(f"ERROR: WebDriver setup failed. Ensure chromedriver is installed and in your PATH.")
        print(f"Details: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during Selenium scraping: {e}")
        return None
    finally:
        if 'driver' in locals():
            driver.quit()
            
    print("Scraping failed. Could not find price on the page.")
    return None


# --- Core Logic & Email ---

def check_price_drop():
    """
    Main job function: iterates through products, gets current price,
    and sends an alert if the price drops below the threshold.
    """
    with sqlite3.connect(DATABASE) as conn:
        products = pd.read_sql_query("SELECT * FROM products", conn)
        
        for _, product in products.iterrows():
            print(f"\nChecking price for: {product['name']} ({product['url']})")
            current_price = get_scraped_price(product['url'])
            
            if current_price is None:
                print("Could not retrieve price. Skipping.")
                continue
                
            save_price(product['id'], current_price)
            
            # Use parameterized query for safety and clarity
            history = pd.read_sql_query(
                "SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 2",
                conn,
                params=(product['id'],)
            )
            
            if len(history) > 1:
                previous_price = history.iloc[1]['price']
                if current_price < previous_price:
                    print(f"PRICE DROP DETECTED for {product['name']}: ₹{previous_price} → ₹{current_price}")
                    
                    if current_price <= product['threshold']:
                        print(f"Price is below threshold of ₹{product['threshold']}. Sending alert...")
                        send_alert(product, current_price, previous_price)
                else:
                    print(f"Price has not dropped. Current: ₹{current_price}, Previous: ₹{previous_price}")
            else:
                print(f"First price recorded for this product: ₹{current_price}")

def send_alert(product, current_price, previous_price):
    """Sends an email alert for a price drop."""
    if not all([EMAIL_USER, EMAIL_PASSWORD, NOTIFICATION_EMAIL]):
        print("Email credentials not configured in .env file. Skipping alert.")
        return
        
    try:
        subject = f"Price Alert for {product['name']}!"
        body = f"""
        Price drop detected!
        
        Product: {product['name']}
        URL: {product['url']}
        
        Previous Price: ₹{previous_price}
        Current Price:  ₹{current_price}
        
        The price is now below your threshold of ₹{product['threshold']}!
        """
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = NOTIFICATION_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, NOTIFICATION_EMAIL, msg.as_string())
        
        print("Alert email sent successfully!")
        
    except Exception as e:
        print(f"Failed to send email: {e}")

def generate_price_report():
    """Generates and prints a price history report for all products."""
    with sqlite3.connect(DATABASE) as conn:
        products = pd.read_sql_query("SELECT * FROM products", conn)
        
        for _, product in products.iterrows():
            history = pd.read_sql_query(
                "SELECT price, timestamp FROM price_history WHERE product_id = ? ORDER BY timestamp",
                conn,
                params=(product['id'],)
            )
            
            if not history.empty:
                print(f"\n--- Price History for {product['name']} ---")
                print(history.to_string())
                
                initial_price = history.iloc[0]['price']
                current_price = history.iloc[-1]['price']
                change = current_price - initial_price
                
                if initial_price > 0:
                    change_percent = (change / initial_price) * 100
                    print(f"\nOverall Change: {'+' if change >= 0 else ''}{change_percent:.2f}% (From ₹{initial_price} to ₹{current_price})")
                else:
                    print(f"\nInitial price was zero. Current price: ₹{current_price}")


def run_scheduler(interval_hours=6):
    """Schedules the price check job to run at a regular interval."""
    schedule.every(interval_hours).hours.do(check_price_drop)
    
    print(f"Starting price monitoring. Checking every {interval_hours} hours...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# --- Main Execution ---

def main():
    """Parses command-line arguments and executes the corresponding function."""
    setup_database()
    
    parser = argparse.ArgumentParser(description="E-commerce Price Monitoring Tool")
    subparsers = parser.add_subparsers(dest='command', help='Available commands', required=True)
    
    # 'add' command
    add_parser = subparsers.add_parser('add', help='Add a new product to monitor')
    add_parser.add_argument('url', help='Full product URL')
    add_parser.add_argument('--threshold', type=float, required=True, help='Price threshold for alerts')
    add_parser.add_argument('--name', help='Product name (if not provided, will be scraped)')
    
    # 'start' command
    monitor_parser = subparsers.add_parser('start', help='Start monitoring prices on a schedule')
    monitor_parser.add_argument('--interval', type=int, default=6, help='Check interval in hours (default: 6)')
    
    # 'check' command
    subparsers.add_parser('check', help='Run a single price check for all products')
    
    # 'report' command
    subparsers.add_parser('report', help='Generate a price history report')
    
    args = parser.parse_args()
    
    if args.command == 'add':
        add_product(args.url, args.threshold, args.name)
    elif args.command == 'start':
        print("Running an initial check before starting the schedule...")
        check_price_drop()
        run_scheduler(args.interval)
    elif args.command == 'check':
        check_price_drop()
    elif args.command == 'report':
        generate_price_report()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
