# 🛍️ # Web-Scraping-and-Price-Monitoring-App

**Stop hitting refresh. Start saving money.**



---

## Web Scraping and Price Monitoring App is a powerful and lightweight Python script that automates the tedious task of price watching. Never miss a deal on your favorite products from Amazon and Flipkart again. Set a target price, and let the tracker notify you the moment the price drops!

## ✨ Key Features

-   **🛒 Multi-Store Support:** Tracks products on Amazon.in and Flipkart.com.
-   **🔔 Smart Alerts:** Get instant email notifications when a product's price drops below your desired threshold.
-   **🤖 Hybrid Scraping:** Uses a fast, efficient `requests` & `BeautifulSoup` method first, with a powerful `Selenium` fallback for dynamic, hard-to-scrape content.
-   **📈 Price History:** Saves all price checks to a local SQLite database, so you can track trends over time.
-   **📄 Detailed Reports:** Generate a command-line report to view the complete price history of any product you're tracking.
-   **🔒 Secure & Private:** Your email credentials are kept safe and local in a `.env` file, never hard-coded.
-   **💻 CLI-Powered:** A simple and intuitive command-line interface for easy management.

## ⚙️ How It Works

The process is simple and fully automated after the initial setup:

1.  **ADD:** You add a product URL and set a target price.
2.  **SCRAPE:** The script visits the page periodically to get the current price.
3.  **COMPARE:** It compares the new price to the last known price and your target threshold.
4.  **ALERT:** If the price drops below your threshold, it instantly sends you an email!

## 🛠️ Tech Stack

-   **Backend:** Python
-   **Web Scraping:** Requests, BeautifulSoup, Selenium
-   **Database:** SQLite
-   **Scheduling:** schedule
-   **Data Handling:** Pandas
-   **Configuration:** python-dotenv

## 🚀 Getting Started

Follow these steps to get your personal price tracker up and running.

### 1. Prerequisites

-   Python 3.x
-   Google Chrome installed
-   `chromedriver` (ensure it's in your system's PATH)

### 2. Installation

```bash
# 1. Clone the repository (or just download the script)
# git clone [https://github.com/your-username/price-pulse-tracker.git](https://github.com/your-username/price-pulse-tracker.git)
# cd price-pulse-tracker

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install the required packages
pip install -r requirements.txt 
# (Or: pip install requests beautifulsoup4 selenium pandas schedule python-dotenv)
