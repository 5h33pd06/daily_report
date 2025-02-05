from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, flash
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import smtplib
import os
import json
import time
import threading
from dotenv import load_dotenv
from urllib.parse import urlparse
from collections import defaultdict
from pytz import timezone
from logging.handlers import RotatingFileHandler

# Load environment variables from .env file
load_dotenv()

def get_secret(filepath):
    """Read a Docker secret from a file."""
    try:
        with open(filepath, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        return None

app = Flask(__name__)

NEWS_SOURCES_FILE = "news_sources.json"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
TOPICS_FILE = "topics.json"
CACHE_FILE = "news_cache.json"
EMAIL_USER = get_secret(os.getenv("EMAIL_USER_FILE"))
EMAIL_PASSWORD = get_secret(os.getenv("EMAIL_PASSWORD_FILE"))
EMAIL_RECEIVER = get_secret(os.getenv("EMAIL_RECEIVER_FILE"))
NEWSAPI_KEY = get_secret(os.getenv("NEWSAPI_KEY_FILE"))
app.secret_key = get_secret(os.getenv('SECRET_KEY_FILE'))  # Needed for flash messages
app.config['DEBUG'] = False

def load_cache():
    """Load the cached data from the cache file."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                logging.error("Error decoding JSON in cache file.")
    return {}

def save_cache(data):
    """Save the data to the cache file."""
    with open(CACHE_FILE, 'w') as file:
        json.dump(data, file, indent=4)

def is_cache_valid():
    """Check if the cache is valid based on the timestamp."""
    if not os.path.exists(CACHE_FILE):
        return False

    try:
        with open(CACHE_FILE, 'r') as file:
            cache_data = json.load(file)

        last_fetched = cache_data.get('last_fetched')
        if not last_fetched:
            return False

        # Parse the timestamp using fromisoformat
        last_fetched_time = datetime.fromisoformat(last_fetched)
        cache_age = datetime.utcnow() - last_fetched_time

        # Consider cache valid if it's less than 1 hour old
        return cache_age <= timedelta(hours=1)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        logging.error(f"Error checking cache validity: {e}")
        return False

@app.template_filter('strftime')
def _jinja2_filter_datetime(date, fmt=None):
    if not date:
        return ''
    if fmt:
        return date.strftime(fmt)
    return date.strftime("%Y-%m-%d %H:%M:%S")
    
def load_news_sources():
    """Load news sources from the JSON file."""
    if not os.path.exists(NEWS_SOURCES_FILE):
        logging.warning(f"News sources file '{NEWS_SOURCES_FILE}' not found.")
        return []
    with open(NEWS_SOURCES_FILE, "r") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON in '{NEWS_SOURCES_FILE}': {e}")
            return []

def save_news_sources(news_sources):
    """Save news sources to a JSON file."""
    with open(NEWS_SOURCES_FILE, 'w') as file:
        json.dump(news_sources, file, indent=4)

# Set up logging
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)

# Load topics from a JSON file
def load_topics_from_json():
    """Load the list of topics from a JSON file."""
    try:
        with open(TOPICS_FILE, 'r') as file:
            topics = json.load(file)
        return [topic["topic"] for topic in topics]  # Extract the topic names
    except FileNotFoundError:
        logging.warning("topics.json file not found.")
        return []
    except json.JSONDecodeError:
        logging.error("Error reading topics file.")
        return []
        
def save_topics_to_json(topics):
    """Save the list of topics to a JSON file."""
    try:
        # Ensure the structure matches the existing format
        topics_data = [{"topic": topic} for topic in topics]
        with open(TOPICS_FILE, 'w') as file:
            json.dump(topics_data, file, indent=4)
    except Exception as e:
        logging.error(f"Error saving topics to {TOPICS_FILE}: {e}")

def fetch_google_news_rss(topic):
    try:
        google_news_url = f"https://news.google.com/rss/search?q={topic}&hl=en-US&gl=US&ceid=US:en"

        response = requests.get(google_news_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")

        items = soup.find_all("item")
        news_items = []
        for item in items[:5]:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")

            if title and link:
                article_pub_date = pub_date.get_text().strip() if pub_date else datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                article_datetime = datetime.strptime(article_pub_date, '%a, %d %b %Y %H:%M:%S %Z')
                
                # Only add articles from the last 24 hours
                if article_datetime > datetime.utcnow() - timedelta(days=1):
                    news_items.append({
                        "title": title.get_text().strip(),
                        "link": link.get_text().strip(),
                        "pub_date": article_pub_date,
                        "source": "Google News",
                        "topic": topic
                    })
        logging.info(f"Fetched {len(news_items)} articles from Google News for topic: {topic}")
        return news_items
    except Exception as e:
        logging.error(f"Error fetching Google News RSS feed: {str(e)}")
        return []

def fetch_newsapi_articles():
    """Fetch cybersecurity news from NewsAPI and cache the results."""
    if is_cache_valid():
        logging.info("Using cached NewsAPI data.")
        cache = load_cache()
        return cache.get('articles', [])

    logging.info("Fetching new data from NewsAPI.")
    topics = load_topics_from_json()
    if not topics:
        logging.warning("No topics found in topics.json")
        return []

    one_day_ago = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    combined_query = " OR ".join(topics)
    params = {
        'apiKey': NEWSAPI_KEY,
        'q': combined_query,
        'from': one_day_ago,
        'language': 'en',
        'sortBy': 'publishedAt'
    }

    try:
        response = requests.get(NEWSAPI_URL, params=params)
        response.raise_for_status()
        json_response = response.json()

        # Ensure the response structure is valid
        if not isinstance(json_response, dict) or json_response.get('status') != 'ok':
            logging.warning("Unexpected response format or status from NewsAPI.")
            return []

        articles = json_response.get('articles', [])
        formatted_articles = [
            {
                "title": article.get("title"),
                "link": article.get("url"),
                "pub_date": article.get("publishedAt"),
                "source": "NewsAPI",
                "last_updated": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            for article in articles
            if article.get("title") and article.get("url")
            and article.get("publishedAt")
            and datetime.strptime(article.get("publishedAt"), '%Y-%m-%dT%H:%M:%SZ') > datetime.utcnow() - timedelta(days=1)
        ]

        # Save the fetched data into cache
        cache_data = {
            'last_fetched': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'articles': formatted_articles
        }
        save_cache(cache_data)
        logging.info(f"Fetched {len(formatted_articles)} articles from NewsAPI")
        return formatted_articles

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching news from NewsAPI: {str(e)}")
        return []

    except (ValueError, KeyError) as e:
        logging.error(f"Error processing NewsAPI response: {str(e)}")
        return []

def is_valid_rss_url(url):
    """Check if the provided URL is a valid RSS feed."""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.content, "xml")
        if soup.find("rss") or soup.find("feed"):
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking RSS URL: {e}")
        return False

from collections import defaultdict

def fetch_cybersecurity_news():
    """Fetches cybersecurity news from multiple RSS feeds."""
    news_items = defaultdict(lambda: defaultdict(list))  # Group by source and then by topic
    topics = load_topics_from_json()  # Get predefined topics

    news_sources = load_news_sources()
    logging.info(f"Attempting to fetch news from {len(news_sources)} sources")

    for source in news_sources:
        url = source.get("url")
        name = source.get("name", "Unknown Source")
        
        try:
            logging.info(f"Fetching news from {name}: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # Try parsing as XML first
            soup = BeautifulSoup(response.content, "xml")
            
            # Look for items in different XML structures
            items = soup.find_all("item") or soup.find_all("entry")
            logging.info(f"Found {len(items)} items for {name}")

            for item in items[:5]:  # Limit to 5 items per source
                # Extract title
                title = item.find("title")
                if not title:
                    logging.warning(f"No title found in item for {name}")
                    continue
                title_text = title.get_text().strip()

                # Extract link
                link = item.find("link")
                if not link:
                    logging.warning(f"No link found for item in {name}")
                    continue
                
                # Handle different link formats
                if link.get_text():
                    link_url = link.get_text().strip()
                elif link.get("href"):
                    link_url = link.get("href")
                else:
                    logging.warning(f"Could not extract link for item in {name}")
                    continue

                # Extract publication date
                pub_date = item.find("pubDate") or item.find("published")
                if pub_date:
                    pub_date_str = pub_date.get_text().strip()
                    try:
                        pub_date_obj = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                    except ValueError:
                        try:
                            # Try alternative date formats
                            pub_date_obj = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%S%z")
                        except ValueError:
                            pub_date_obj = datetime.utcnow()
                else:
                    pub_date_obj = datetime.utcnow()

                # Only include articles from the last 24 hours
                if datetime.utcnow() - pub_date_obj < timedelta(days=1):
                    # Determine topic
                    article_topic = "General"
                    for topic in topics:
                        if topic.lower() in title_text.lower():
                            article_topic = topic
                            break
                    
                    news_items[name][article_topic].append({
                        "title": title_text,
                        "link": link_url,
                        "pub_date": pub_date_obj.strftime('%Y-%m-%d %H:%M:%S'),
                        "source": name,
                        "topic": article_topic
                    })

        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching news from {name} ({url}): {str(e)}")
        except Exception as e:
            logging.error(f"Unexpected error processing {name}: {str(e)}")

    return news_items


# Add routes for managing topics
@app.route('/add_topic', methods=['POST'])
def add_topic():
    """Add a new topic to the JSON file."""
    topic = request.form.get('topic')
    if topic:
        topics = load_topics_from_json()
        if topic not in topics:  # Prevent duplicates
            topics.append(topic)
            save_topics_to_json(topics)
            flash(f"Topic '{topic}' added successfully.", "success")
        else:
            flash(f"Topic '{topic}' already exists.", "warning")
    else:
        flash("Topic cannot be empty.", "error")
    return redirect(url_for("dashboard"))
    
@app.route("/edit_topic/<int:index>", methods=["GET", "POST"])
def edit_topic(index):
    """Edit an existing topic."""
    topics = load_topics_from_json()
    if index >= len(topics):
        flash("Invalid topic index.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        topic = request.form.get("topic")
        if topic:
            topics[index] = topic
            save_topics_to_json(topics)
            flash("Topic updated successfully.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Topic cannot be empty.", "error")

    return render_template("edit_topic.html", topic=topics[index], index=index)

@app.route('/delete_topic/<topic>', methods=['POST'])
def delete_topic(topic):
    """Delete a topic."""
    topics = load_topics_from_json()
    if topic in topics:
        topics.remove(topic)
        save_topics_to_json(topics)
        flash(f"Topic '{topic}' deleted successfully.", "success")
    else:
        flash(f"Topic '{topic}' not found.", "error")
    return redirect(url_for("dashboard"))
    
@app.route('/add_source', methods=['POST'])
def add_source():
    news_sources = load_news_sources()
    name = request.form['name']
    url = request.form['url']
    news_sources.append({'name': name, 'url': url})
    save_news_sources(news_sources)
    return jsonify({'message': 'Source added!'})

def get_dashboard_data():
    """Fetch and combine data from RSS, NewsAPI, and Google News RSS sources."""
    rss_news = fetch_cybersecurity_news()  # Existing RSS sources
    newsapi_articles = fetch_newsapi_articles()  # Existing NewsAPI sources
    google_news_articles = []  # New Google News source
    topics = load_topics_from_json()
    
    for topic in topics:
        google_news_articles += fetch_google_news_rss(topic)
        
    # Combine all sources
    all_news = []
    for source_dict in rss_news.values():
        for topic_list in source_dict.values():
            all_news.extend(topic_list)
    
    all_news.extend(newsapi_articles)
    all_news.extend(google_news_articles)
    
    # Log the number of articles found
    logging.info(f"Total articles found: {len(all_news)}")
    
    # Sort by publication date (descending)
    all_news.sort(key=lambda x: x.get("pub_date", ""), reverse=True)
    
    return all_news

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
    """Send an email containing the same data as the dashboard."""
    news_items = get_dashboard_data()
    content = format_email_content(news_items)

    if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        logging.error("Email credentials are not set.")
        return

    subject = "Daily Cybersecurity Briefing"
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject

    # Add the email body content
    msg.attach(MIMEText(content, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
            logging.info("Email sent successfully.")
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")


@app.route("/send_email", methods=["POST"])
def send_email_route():
    """Manually trigger an email with the latest dashboard data."""
    send_email()
    flash("Email sent successfully.", "success")
    return redirect(url_for("dashboard"))
    
def start_scheduler():
    """Schedule the email to be sent every day at 8:00 AM in the specified timezone."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_email, 'cron', hour=8, minute=0, timezone=timezone('US/Eastern'))
    scheduler.start()
    logging.info("Scheduler started.")

def list_scheduled_jobs(scheduler):
    jobs = scheduler.get_jobs()
    for job in jobs:
        print(f"Job: {job.id}, Next run time: {job.next_run_time}")

@app.route('/stop_alerts/<int:index>', methods=['POST'])
def stop_alerts(index):
    news_sources = load_news_sources()
    
    if index < len(news_sources):
        # Update the source to stop alerts or mark it as inactive
        news_sources[index]['alerts_enabled'] = False
        save_news_sources(news_sources)
        flash("Alerts stopped for this source.", "success")
    else:
        flash("Invalid news source index.", "error")
    
    return redirect(url_for("dashboard"))

@app.route("/")
def dashboard():
    """Display the dashboard with all fetched news."""
    # Fetch news data from multiple sources
    all_news = get_dashboard_data()
    
    # Group news by source and topic
    grouped_news = defaultdict(lambda: defaultdict(list))
    for news_item in all_news:
        source = news_item.get("source", "Unknown Source")
        topic = news_item.get("topic", "General")
        grouped_news[source][topic].append(news_item)
    
    # Get list of topics for the template
    topics = load_topics_from_json()
    
    # Get list of news sources for the template
    news_sources = load_news_sources()
    
    return render_template("dashboard.html", 
                            news_items=all_news, 
                            grouped_news=grouped_news,
                            topics=topics,
                            news_sources=news_sources)

@app.route('/add_news_source', methods=['POST'])
def add_news_source():
    """Add a new news source to the application."""
    name = request.form.get('name')
    url = request.form.get('url')

    # Check if name or URL is missing
    if not name or not url:
        flash("Both name and URL are required.", "error")
        return redirect(url_for('dashboard'))

    # Check if the URL is a valid RSS feed
    if not is_valid_rss_url(url):
        flash("Invalid RSS feed URL.", "error")
        return redirect(url_for('dashboard'))

    # Load the current news sources from the file
    news_sources = load_news_sources()

    # Add the new source
    news_sources.append({"name": name, "url": url})

    # Save the updated list back to the JSON file
    save_news_sources(news_sources)

    # Flash success message and redirect to the dashboard
    flash("News source added successfully.", "success")
    return redirect(url_for('dashboard'))

@app.route("/edit_news_source/<int:index>", methods=["GET", "POST"])
def edit_news_source(index):
    news_sources = load_news_sources()

    if index >= len(news_sources):
        flash("Invalid news source index.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form["name"]
        url = request.form["url"]

        if not name or not url:
            flash("Both name and URL are required.", "error")
            return redirect(url_for("edit_news_source", index=index))

        news_sources[index]["name"] = name
        news_sources[index]["url"] = url
        save_news_sources(news_sources)

        flash("News source updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_news_source.html", source=news_sources[index], index=index)

@app.route("/delete_news_source/<int:index>", methods=["POST"])
def delete_news_source(index):
    news_sources = load_news_sources()

    if index < len(news_sources):
        news_sources.pop(index)
        save_news_sources(news_sources)
        flash("News source deleted successfully.", "success")
    else:
        flash("Invalid news source index.", "error")

    return redirect(url_for("dashboard"))
    
# Route to display the Google news articles
@app.route("/google_news", methods=["GET"])
def google_news():
    topics = load_topics_from_json()
    news_data = {}
    for topic in topics:
        news_data[topic] = fetch_google_news_rss(topic)  # Pass the topic to the function
    return render_template("google_news.html", news_data=news_data)
    
@app.route("/management")
def management_page():
    """Render the management page for topics and news sources."""
    # Load topics
    topics = load_topics_from_json()
    
    # Load news sources
    news_sources = load_news_sources()
    
    return render_template("management.html", 
                            topics=topics, 
                            news_sources=news_sources)

if __name__ == "__main__":
    # Start scheduler in a background thread
    threading.Thread(target=start_scheduler, daemon=True).start()
    app.run(host='0.0.0.0', port=31337)