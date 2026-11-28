# gunicorn.conf.py — main.py এর পাশে রাখুন (gunicorn নিজে থেকেই পড়ে)
# Bot/monitor state RAM-এ থাকে, তাই অবশ্যই ১টা worker। concurrency আসবে threads থেকে।
import os
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
workers = 1
threads = 16
timeout = 300
graceful_timeout = 30
keepalive = 5
