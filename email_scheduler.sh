#!/bin/bash
export PATH=$PATH:/usr/local/bin
export EMAIL_USER_FILE="/run/secrets/email_user"
export EMAIL_PASSWORD_FILE="/run/secrets/email_password"
export EMAIL_RECEIVER_FILE="/run/secrets/email_receiver"
export NEWSAPI_KEY_FILE="/run/secrets/newsapi_key"
export FLASK_ENV="production"
export PYTHONUNBUFFERED=1

echo "Running email_scheduler.sh at $(date)" >> /app/logs/email_scheduler_debug.log

/usr/local/bin/python3 /app/email_scheduler.py >> /app/logs/email_scheduler_debug.log 2>&1
