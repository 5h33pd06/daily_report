# daily_report
A customizable daily report dashboard that will email a briefing every morning

This runs a docker that will run a flask server that serves up a webpage that collates news feeds from the previous 24 hours and displays them. It will also email a daily briefing at 8AM EST every day to a specified email.

Inside the "secrets" directory, you will need to add information related to the email address and password for the sending email, the receiver's email address, the flask secret key, and the newsapi key (if you choose to use NewsAPI).

The news_sources.json and topics.json files contain the sources that the briefing will pull from. There is the ability to add and remove sourcs and topics from a webpage linked to the dashboard. It currently has cybersecurity sources and topics. The sources are pulled directly from RSS feeds.

![image](https://github.com/user-attachments/assets/3633e541-d4cf-4fce-a92b-db6962631c66)
Website Dashboard

![image](https://github.com/user-attachments/assets/9d031061-c096-4dbd-97ce-6c409eacf080)
Email briefing
