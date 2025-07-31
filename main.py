import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sqlite3
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import schedule
import time
import argparse
import os
from datetime import datetime

from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()
# Configuration
DATABASE = 'price_data.db'
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_USER = os.getenv('EMAIL_USER')  # Set environment variables
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')  # Set environment variables
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def setup_database():
    conn = sqlite3.connect(DATABASE)
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
    conn.close()

def add_product(url, threshold, name=None):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO products (url, name, threshold) VALUES (?, ?, ?)", 
                 (url, name, threshold))
        conn.commit()
        print(f"Product added: {name or url}")
    except sqlite3.IntegrityError:
        print("Product already exists in database")
    conn.close()

def get_scraped_price(url):
    domain = url.split("//")[-1].split("/")[0]
    if 'amazon' in domain:
        return scrape_amazon(url)
    elif 'flipkart' in domain:
        return scrape_flipkart(url)
    else:
        print(f"Unsupported website: {domain}")
        return None

def scrape_amazon(url):
    try:
        # First try with requests/BeautifulSoup
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try different selectors
            selectors = [
                'span.a-price-whole',
                'span#priceblock_ourprice',
                'span#priceblock_dealprice'
            ]
            
            for selector in selectors:
                price_element = soup.select_one(selector)
                if price_element:
                    price = price_element.get_text().replace(',', '').strip()
                    if price.isdigit():
                        return float(price)
        
        # Fallback to Selenium if dynamic content
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        # Wait for price element to load
        try:
            price_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span.a-price-whole")))
            price = price_element.text.replace(',', '').strip()
            return float(price)


            
            # price_element = WebDriverWait(driver, 10).until(
            #     EC.presence_of_element_located((By.CSS_SELECTOR, "span.a-price-whole"))
            # price = price_element.text.replace(',', '').strip()
            # return float(price)
        except:
            return None
        finally:
            driver.quit()
            
    except Exception as e:
        print(f"Amazon scraping error: {e}")
        return None

def scrape_flipkart(url):
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try different selectors
            selectors = [
                'div._30jeq3._16Jk6d',
                'div._30jeq3._1_WHN1'
            ]
            
            for selector in selectors:
                price_element = soup.select_one(selector)
                if price_element:
                    price = price_element.get_text().replace('₹', '').replace(',', '').strip()
                    if price.isdigit():
                        return float(price)
        
        # Fallback to Selenium
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        try:
            price_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div._30jeq3._16Jk6d")))
            price = price_element.text.replace('₹', '').replace(',', '').strip()
            return float(price)
        except:
            return None
        finally:
            driver.quit()
            
    except Exception as e:
        print(f"Flipkart scraping error: {e}")
        return None

def save_price(product_id, price):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT INTO price_history (product_id, price) VALUES (?, ?)",
             (product_id, price))
    conn.commit()
    conn.close()

def check_price_drop():
    conn = sqlite3.connect(DATABASE)
    products = pd.read_sql_query("SELECT * FROM products", conn)
    
    for _, product in products.iterrows():
        current_price = get_scraped_price(product['url'])
        if current_price is None:
            continue
            
        save_price(product['id'], current_price)
        
        # Get previous price
        history = pd.read_sql_query(f"SELECT price FROM price_history WHERE product_id = {product['id']} ORDER BY timestamp DESC LIMIT 2", conn)
        
        if len(history) > 1:
            previous_price = history.iloc[1]['price']
            if current_price < previous_price:
                print(f"Price drop detected for {product['name']}: ₹{previous_price} → ₹{current_price}")
                
                # Check if below threshold
                if current_price < product['threshold']:
                    send_alert(product, current_price, previous_price)
    
    conn.close()

def send_alert(product, current_price, previous_price):
    if not all([EMAIL_USER, EMAIL_PASSWORD, NOTIFICATION_EMAIL]):
        print("Email credentials not configured. Skipping alert.")
        return
        
    try:
        subject = f"Price Alert for {product['name']}!"
        body = f"""
        Price drop detected!
        
        Product: {product['name']}
        URL: {product['url']}
        
        Previous Price: ₹{previous_price}
        Current Price: ₹{current_price}
        
        Price is now below your threshold of ₹{product['threshold']}!
        """
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = NOTIFICATION_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USER, NOTIFICATION_EMAIL, msg.as_string())
        server.quit()
        
        print("Alert email sent successfully!")
        
    except Exception as e:
        print(f"Failed to send email: {e}")

def generate_price_report():
    conn = sqlite3.connect(DATABASE)
    products = pd.read_sql_query("SELECT * FROM products", conn)
    
    for _, product in products.iterrows():
        history = pd.read_sql_query(
            f"SELECT price, timestamp FROM price_history WHERE product_id = {product['id']} ORDER BY timestamp",
            conn
        )
        
        if not history.empty:
            print(f"\nPrice History for {product['name']}:")
            print(history)
            
            # Simple price change calculation
            initial_price = history.iloc[0]['price']
            current_price = history.iloc[-1]['price']
            change = current_price - initial_price
            change_percent = (change / initial_price) * 100
            
            print(f"\nOverall Change: {'+' if change >= 0 else ''}{change_percent:.2f}%")
            print(f"From ₹{initial_price} to ₹{current_price}")
    
    conn.close()

def run_scheduler(interval_hours=6):
    schedule.every(interval_hours).hours.do(check_price_drop)
    
    print(f"Starting price monitoring. Checking every {interval_hours} hours...")
    while True:
        schedule.run_pending()
        time.sleep(60)

def main():
    setup_database()
    
    parser = argparse.ArgumentParser(description="Price Monitoring Tool")
    subparsers = parser.add_subparsers(dest='command')
    
    # Add product command
    add_parser = subparsers.add_parser('add', help='Add a new product to monitor')
    add_parser.add_argument('url', help='Product URL')
    add_parser.add_argument('--threshold', type=float, required=True, help='Price threshold for alerts')
    add_parser.add_argument('--name', help='Product name (optional)')
    
    # Start monitoring command
    monitor_parser = subparsers.add_parser('start', help='Start monitoring prices')
    monitor_parser.add_argument('--interval', type=int, default=6, 
                               help='Check interval in hours (default: 6)')
    
    # Generate report command
    report_parser = subparsers.add_parser('report', help='Generate price history report')
    
    args = parser.parse_args()
    
    if args.command == 'add':
        add_product(args.url, args.threshold, args.name)
    elif args.command == 'start':
        # Run initial check
        check_price_drop()
        # Start scheduler
        run_scheduler(args.interval)
    elif args.command == 'report':
        generate_price_report()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()