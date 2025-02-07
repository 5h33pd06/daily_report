import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_secret(filepath):
    """Read a Docker secret from a file."""
    try:
        with open(filepath, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        return None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_scheduler.log'),
        logging.StreamHandler()
    ]
)

# Credentials from environment/secrets
EMAIL_USER = get_secret(os.getenv("EMAIL_USER_FILE"))
EMAIL_PASSWORD = get_secret(os.getenv("EMAIL_PASSWORD_FILE"))
EMAIL_RECEIVER = get_secret(os.getenv("EMAIL_RECEIVER_FILE"))
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:31337")

def fetch_dashboard_data():
    """Fetch news data from the running dashboard."""
    try:
        response = requests.get(f"{DASHBOARD_URL}/dashboard_data")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching dashboard data: {str(e)}")
        return []

def format_email_content(news_items):
    """Format news items for email content."""
    content = "Daily Cybersecurity Briefing\n\n"
    for news in news_items:
        title = news.get("title", "No Title")
        link = news.get("link", "No Link")
        pub_date = news.get("pub_date", "Unknown Date")
        source = news.get("source", "Unknown Source")
        topic = news.get("topic", "General")

        content += f"- {title}\n  Source: {source}\n  Topic: {topic}\n  Published: {pub_date}\n  Link: {link}\n\n"

    return content

def send_email():
    """Send an email with the latest news."""
    logging.info("Starting email sending process")

    if not all([EMAIL_USER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        logging.error("Email credentials are not set.")
        return

    news_items = fetch_dashboard_data()
    content = format_email_content(news_items)

    subject = "Daily Cybersecurity Briefing"
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject

    msg.attach(MIMEText(content, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
            logging.info("Email sent successfully.")
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")

def main():
    """Main function to send email."""
    logging.info("Email scheduler script started")
    send_email()
    logging.info("Email scheduler script completed")

if __name__ == "__main__":
    main()
