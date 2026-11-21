#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import sqlite3
import hashlib
import secrets
import json
import time
import subprocess
import shutil
import threading
import re
import signal
import zipfile
from datetime import datetime, timedelta
from queue import Queue, Empty
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash, send_file, send_from_directory
from functools import wraps
import psutil
import requests
from importlib.metadata import distributions
import importlib


PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", "photo")
STATIC_PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", "static", "photo")
for _d in (PHOTO_DIR, STATIC_PHOTO_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

# Common packages that bots often need (auto-detect + quick install)
COMMON_BOT_PACKAGES = [
    "edge_tts", "PyJWT", "google-play-scraper", "httpx", "aiohttp",
    "pycryptodome", "protobuf", "protobuf-decoder", "colorama", "psutil",
    "requests", "flask", "pillow", "numpy", "gtts", "playsound",
    "websocket-client", "python-socketio", "fastapi", "uvicorn",
]

def pip_install(packages, upgrade=False, quiet=True):
    """Install one or more packages via pip. Returns (ok, message)."""
    if isinstance(packages, str):
        packages = [packages]
    packages = [p.strip() for p in packages if p and p.strip()]
    if not packages:
        return False, "No packages specified"
    cmd = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    if quiet:
        cmd.append("--quiet")
    cmd.extend(packages)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True, f"Installed: {', '.join(packages)}"
        err = (result.stderr or result.stdout or "Unknown error")[-800:]
        return False, err
    except subprocess.TimeoutExpired:
        return False, "pip install timed out (5 min)"
    except Exception as e:
        return False, str(e)


def install_dependencies():
    required_pkgs = [
        "colorama", "psutil", "flask", "requests",
        "httpx", "aiohttp", "pycryptodome", "protobuf-decoder", "google-play-scraper",
        "PyJWT", "edge-tts",
    ]
    import_map = {
        "pycryptodome": "Crypto",
        "protobuf-decoder": "protobuf_decoder",
        "google-play-scraper": "google_play_scraper",
        "edge-tts": "edge_tts",
        "PyJWT": "jwt",
    }
    for pkg in required_pkgs:
        mod = import_map.get(pkg, pkg.replace("-", "_"))
        try:
            __import__(mod)
        except ImportError:
            try:
                print(f"[DEPS] Installing missing: {pkg}")
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"], timeout=120)
            except Exception as e:
                print(f"[DEPS] Failed {pkg}: {e}")

install_dependencies()

from colorama import init, Fore, Style
init(autoreset=True)

# Free Fire auto account creator (optional module)
try:
    from ff_account import create_account_sync, DEFAULT_BIO as FF_DEFAULT_BIO
    FF_CREATE_AVAILABLE = True
except Exception as _ff_err:
    create_account_sync = None
    FF_DEFAULT_BIO = "[C][B]WEB : MAHIR.XO.JE [FFD700]TG : MAHIR0208"
    FF_CREATE_AVAILABLE = False
    print(f"[FF] Account create module not loaded: {_ff_err}")

app = Flask(__name__)

SECRET_KEY_FILE = ".secret_key"
if os.path.exists(SECRET_KEY_FILE):
    try:
        with open(SECRET_KEY_FILE, 'r') as f:
            app.secret_key = f.read().strip()
    except:
        app.secret_key = secrets.token_hex(32)
else:
    app.secret_key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, 'w') as f:
            f.write(app.secret_key)
        os.chmod(SECRET_KEY_FILE, 0o600)
    except: pass

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # set True only behind HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

DB_FILE = "users.db"
MAHIR_SOURCE = "mahir.py"
USER_BOTS_DIR = "."
MASTER_ADMIN_UID = "1120167200"

_KX = bytes([0x53,0x65,0x63,0x72,0x65,0x74,0x4b,0x65,
             0x79,0x32,0x30,0x32,0x34,0x58,0x59,0x5a])
_KA_U = bytes([0x1e,0x24,0x2b,0x3b,0x37,0x54,0x1f,
               0x26,0x29,0x12,0x67,0x77,0x76])
_KA_P = bytes([0x1e,0x24,0x2b,0x3b,0x37,0x44,0x79,
               0x55,0x4b,0x02,0x08,0x72])

def _kx_decode(p):
    return bytes(b ^ _KX[i % len(_KX)] for i, b in enumerate(p)).decode()

OWNER_USERNAME = _kx_decode(_KA_U)
OWNER_PASSWORD = _kx_decode(_KA_P)

DB_DOWNLOAD_PASSWORD = "MAHIRDB"

monitors_lock = threading.Lock()


def get_db_connection():
    """Thread-safe SQLite connection with timeout + WAL for concurrency."""
    conn = sqlite3.connect(DB_FILE, timeout=30)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn



# ============================================================
#  DATABASE
# ============================================================
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        email TEXT,
        registration_key TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_admin INTEGER DEFAULT 0,
        is_agent INTEGER DEFAULT 0,
        admin_uid TEXT,
        bot_uid TEXT,
        bot_pw TEXT,
        bot_file TEXT,
        bot_pid INTEGER,
        bot_status TEXT DEFAULT 'not_configured',
        key_limit INTEGER DEFAULT -1,
        can_manage_db INTEGER DEFAULT 0,
        bot_disabled_by_admin INTEGER DEFAULT 0,
        disable_reason TEXT,
        subscription_expiry TIMESTAMP NULL,
        created_by_agent TEXT,
        bot_force_active INTEGER DEFAULT 0,
        personal_notice TEXT,
        personal_notice_enabled INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        used_by TEXT,
        used_at TIMESTAMP,
        is_used INTEGER DEFAULT 0,
        expiry_date TIMESTAMP NULL,
        duration_days INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscription_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        extended_by TEXT,
        extended_by_role TEXT,
        days_added INTEGER,
        mode TEXT,
        old_expiry TIMESTAMP,
        new_expiry TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # ✅ নতুন যোগ করা টেবিল (সোশ্যাল লিংকের জন্য)
    c.execute('''CREATE TABLE IF NOT EXISTS custom_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        icon TEXT NOT NULL,
        section TEXT DEFAULT 'Social',
        sort_order INTEGER DEFAULT 0
    )''')
    
    conn.commit()
    conn.close()


def migrate_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in c.fetchall()}
        if 'key_limit' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN key_limit INTEGER DEFAULT -1')
        if 'can_manage_db' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN can_manage_db INTEGER DEFAULT 0')
        if 'bot_disabled_by_admin' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN bot_disabled_by_admin INTEGER DEFAULT 0')
        if 'disable_reason' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN disable_reason TEXT')
        if 'subscription_expiry' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN subscription_expiry TIMESTAMP NULL')
        if 'created_by_agent' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN created_by_agent TEXT')
        if 'bot_force_active' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN bot_force_active INTEGER DEFAULT 0')
        if 'personal_notice' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN personal_notice TEXT')
        if 'personal_notice_enabled' not in cols:
            c.execute('ALTER TABLE users ADD COLUMN personal_notice_enabled INTEGER DEFAULT 0')
        if 'desired_bot_state' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN desired_bot_state TEXT DEFAULT 'running'")

        # custom_links: section + sort_order for reorder & group titles
        try:
            c.execute("PRAGMA table_info(custom_links)")
            lcols = {row[1] for row in c.fetchall()}
            if 'section' not in lcols:
                c.execute("ALTER TABLE custom_links ADD COLUMN section TEXT DEFAULT 'Social'")
            if 'sort_order' not in lcols:
                c.execute("ALTER TABLE custom_links ADD COLUMN sort_order INTEGER DEFAULT 0")
            c.execute("UPDATE custom_links SET sort_order = id WHERE sort_order IS NULL OR sort_order = 0")
            c.execute("UPDATE custom_links SET section = 'Social' WHERE section IS NULL OR section = ''")
        except Exception as _le:
            print(f"custom_links migrate: {_le}")

        c.execute("PRAGMA table_info(keys)")
        kcols = {row[1] for row in c.fetchall()}
        if 'duration_days' not in kcols:
            c.execute('ALTER TABLE keys ADD COLUMN duration_days INTEGER DEFAULT 0')

        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscription_history'")
        if not c.fetchone():
            c.execute('''CREATE TABLE subscription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                extended_by TEXT,
                extended_by_role TEXT,
                days_added INTEGER,
                mode TEXT,
                old_expiry TIMESTAMP,
                new_expiry TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        else:
            c.execute("PRAGMA table_info(subscription_history)")
            hcols = {row[1] for row in c.fetchall()}
            if 'extended_by_role' not in hcols:
                c.execute('ALTER TABLE subscription_history ADD COLUMN extended_by_role TEXT')

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Migration warning: {e}")


def backfill_created_by_agent():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT id, registration_key FROM users 
                     WHERE (created_by_agent IS NULL OR created_by_agent='') 
                     AND is_admin=0 AND is_agent=0''')
        rows = c.fetchall()
        fixed = 0
        for user_id, reg_key in rows:
            if not reg_key:
                continue
            c.execute('SELECT created_by FROM keys WHERE key=?', (reg_key,))
            kr = c.fetchone()
            if not kr or not kr[0]:
                continue
            agent_name = kr[0]
            if agent_name in ('admin', 'system', 'MAHIR TCP', 'OWNER'):
                continue
            c.execute('UPDATE users SET created_by_agent=? WHERE id=?', (agent_name, user_id))
            fixed += 1
        conn.commit()
        conn.close()
        if fixed:
            print(f"✅ Backfilled created_by_agent for {fixed} users")
    except Exception as e:
        print(f"Backfill error: {e}")


# ============================================================
#  MASKING HELPERS
# ============================================================
def mask_email(email):
    if not email or '@' not in str(email):
        return '—'
    email = str(email)
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        masked_local = '*' * max(len(local), 2)
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_password(pw, length=8):
    if not pw:
        return '—'
    return '●' * length


def mask_bot_password(pw, length=10):
    if not pw:
        return '—'
    return '●' * length


def mask_uid(uid):
    if not uid:
        return '—'
    uid = str(uid)
    if len(uid) <= 4:
        return '●' * len(uid)
    return uid[:3] + '●' * (len(uid) - 5) + uid[-2:]

def ensure_default_links():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM custom_links")
        if c.fetchone()[0] == 0:
            default_links = [
                ("Telegram", "https://t.me/mahirtcpchat", "fab fa-telegram", "Social", 1),
                ("TikTok", "https://www.tiktok.com/@MAHIR__222", "fab fa-tiktok", "Social", 2),
                ("WhatsApp Channel", "https://whatsapp.com/channel/0029Vb9Omjk2ZjCevpv6h209", "fab fa-whatsapp", "Social", 3),
                ("WhatsApp Group", "https://chat.whatsapp.com/CTiEuMnEKacHZ7wirSNjqs", "fab fa-whatsapp", "Social", 4),
                ("Website", "https://MAHIR.XO.JE/", "fas fa-globe", "Social", 5),
            ]
            c.executemany("INSERT INTO custom_links (name, url, icon, section, sort_order) VALUES (?, ?, ?, ?, ?)", default_links)
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error ensuring default links: {e}")

# Call this at startup
ensure_default_links()

def get_setting(key, default=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key=?', (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except: return default


def set_setting(key, value):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
        conn.commit()
        conn.close()
        return True
    except: return False

def get_auto_bio():
    return get_setting('auto_bio_text', FF_DEFAULT_BIO if 'FF_DEFAULT_BIO' in dir() else "[C][B]WEB : MAHIR.XO.JE [FFD700]TG : MAHIR0208")

def get_youtube_link():
    return get_setting('youtube_link', 'https://youtube.com/@MAHIR')

def get_app_link():
    return get_setting('app_download_link', '#')

def get_default_region():
    return get_setting('default_ff_region', 'BD')


def get_logo_url():
    """Return local photo URL for logo, or a sensible default."""
    fname = get_setting('logo_image', '')
    if fname:
        path = os.path.join(PHOTO_DIR, fname)
        if os.path.exists(path):
            return f"/photo/{fname}"
    # Fallback: first .png/.jpg in photo folder
    try:
        for f in sorted(os.listdir(PHOTO_DIR)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                return f"/photo/{f}"
    except Exception:
        pass
    return "/photo/default_logo.png"  # will 404 gracefully or we place a default


def get_cover_url():
    fname = get_setting('cover_image', '')
    if fname:
        path = os.path.join(PHOTO_DIR, fname)
        if os.path.exists(path):
            return f"/photo/{fname}"
    try:
        for f in sorted(os.listdir(PHOTO_DIR)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')) and 'cover' in f.lower():
                return f"/photo/{f}"
        for f in sorted(os.listdir(PHOTO_DIR)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                return f"/photo/{f}"
    except Exception:
        pass
    return get_logo_url()


def list_photo_files():
    files = []
    try:
        for f in sorted(os.listdir(PHOTO_DIR)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')):
                size = os.path.getsize(os.path.join(PHOTO_DIR, f))
                files.append({
                    'name': f,
                    'url': f'/photo/{f}',
                    'size': size,
                    'size_str': f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB",
                })
    except Exception as e:
        print(f"[PHOTO] list error: {e}")
    return files


def detect_missing_modules_from_text(text):
    """Parse ModuleNotFoundError / ImportError from log text."""
    missing = set()
    if not text:
        return []
    for m in re.finditer(r"No module named ['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
        missing.add(m.group(1).split('.')[0])
    for m in re.finditer(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
        missing.add(m.group(1).split('.')[0])
    # common aliases
    alias = {
        'Crypto': 'pycryptodome',
        'jwt': 'PyJWT',
        'edge_tts': 'edge-tts',
        'google_play_scraper': 'google-play-scraper',
        'PIL': 'Pillow',
        'cv2': 'opencv-python',
        'sklearn': 'scikit-learn',
    }
    return sorted({alias.get(m, m) for m in missing})



def get_installed_packages_info():
    """Return list of interesting installed packages."""
    result = []

    try:
        common_packages = {
            p.lower().replace('-', '_')
            for p in COMMON_BOT_PACKAGES
        }

        for dist in distributions():
            name = dist.metadata.get('Name', '')

            if name and name.lower().replace('-', '_') in common_packages:
                result.append({
                    'name': name,
                    'version': dist.version
                })

        result.sort(key=lambda x: x['name'].lower())

    except Exception as e:
        print(f"[PKG] list error: {e}")

    return result



def check_module_importable(mod_name):
    try:
        importlib.import_module(mod_name.replace('-', '_').split('.')[0])
        return True
    except Exception:
        return False


def log_subscription_history(user_id, username, extended_by, extended_by_role, days_added, mode, old_expiry, new_expiry):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO subscription_history 
                     (user_id, username, extended_by, extended_by_role, days_added, mode, old_expiry, new_expiry)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, username, extended_by, extended_by_role, days_added, mode,
                   old_expiry.isoformat() if old_expiry else None,
                   new_expiry.isoformat() if new_expiry else None))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"History log error: {e}")


def get_global_stop():
    return get_setting('global_bot_stop', '0') == '1'


def get_max_running_bots():
    """Max concurrent running bots. -1 = unlimited."""
    try:
        return int(get_setting('max_running_bots', '-1'))
    except Exception:
        return -1


def count_running_bots(exclude_user_id=None):
    """Count bots that currently have a live process."""
    n = 0
    with monitors_lock:
        for uid, m in list(monitors.items()):
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            try:
                if m.is_running and m.process is not None and m.process.poll() is None:
                    n += 1
            except Exception:
                pass
    return n


def is_bot_limit_full():
    """True when owner-set concurrent limit is reached."""
    max_b = get_max_running_bots()
    if max_b < 0:
        return False
    return count_running_bots() >= max_b


def get_global_notice():
    return get_setting(
        'global_notice_text',
        '╔══════════════════════════════╗\n'
        '🌸 **আসসালামু আলাইকুম** 🌸\n'
        '╚══════════════════════════════╝\n\n'
        '💙 **প্রিয় TCP Bot User সবাইকে,**\n\n'
        'আশা করি আল্লাহর রহমতে আপনারা সবাই ভালো আছেন এবং সুস্থ আছেন। 🤍\n\n'
        '🔥 **MAHIR TCP BOT**-এর সাথে থাকার জন্য আপনাদের সবাইকে আন্তরিকভাবে ধন্যবাদ। 🫶\n\n'
        '⚙️ Bot ব্যবহার করার সময় যদি কোনো **সমস্যা • Bug • Error • Update Issue** '
        'অথবা অন্য কোনো সমস্যা দেখতে পান, তাহলে অবশ্যই আমাদের জানাবেন।\n\n'
        '🛠️ আপনাদের দেওয়া রিপোর্ট অনুযায়ী সমস্যাগুলো ঠিক করার সর্বোচ্চ চেষ্টা করব, ইনশাআল্লাহ। ❤️\n\n'
        '⏳ কাজের ব্যস্ততার কারণে কোনো Update বা Fix দিতে মাঝে মাঝে একটু সময় লাগতে পারে। '
        'তবে চিন্তা করবেন না—সময় পেলেই সবকিছু ঠিক করার চেষ্টা করব। ⚡\n\n'
        '━━━━━━━━━━━━━━━━━━━━━━\n\n'
        '🌸 **সবাই ভালো থাকবেন**\n'
        '🤍 **সুস্থ থাকবেন**\n'
        '🤲 **নিজেদের খেয়াল রাখবেন**\n\n'
        '🔥 **MAHIR TCP BOT** 🔥\n'
        '💫 *Stay Connected • Stay Updated* 💫\n\n'
        '╚══════════════════════════════╝'
    )


def get_user_login_notice():
    return get_setting('user_login_notice_text', '')


def is_user_login_notice_enabled():
    return get_setting('user_login_notice_enabled', '0') == '1'


def validate_db_file(filepath):
    try:
        with open(filepath, 'rb') as f:
            header = f.read(16)
            if not header.startswith(b'SQLite format 3\x00'):
                return False, "Not a valid SQLite database file"
        conn = sqlite3.connect(filepath)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in c.fetchall()}
        missing = {'users', 'keys'} - tables
        if missing:
            conn.close()
            return False, f"Missing tables: {', '.join(missing)}"
        c.execute("PRAGMA integrity_check")
        result = c.fetchone()
        conn.close()
        if result[0] != 'ok':
            return False, f"Integrity: {result[0]}"
        return True, "OK"
    except sqlite3.DatabaseError as e:
        return False, f"Invalid: {e}"
    except Exception as e:
        return False, f"Error: {e}"


# Module-level DB init must NEVER crash the worker process
try:
    init_db()
    migrate_db()
    backfill_created_by_agent()
except Exception as _e:
    print(f'[STARTUP] DB init warning (will retry on first request): {_e}')

# Ensure WAL mode is active for concurrent access (owner panel + background threads)
try:
    _wal = get_db_connection()
    _wal.execute('PRAGMA journal_mode=WAL')
    _wal.execute('PRAGMA busy_timeout=30000')
    _wal.close()
except Exception as _e:
    print(f'[STARTUP] WAL init note: {_e}')


# ============================================================
#  HELPERS
# ============================================================
def sanitize_filename(name):
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)


def is_hashed(pw):
    return len(pw) == 64 and all(c in '0123456789abcdefABCDEF' for c in pw)


def check_password(stored, provided):
    if is_hashed(stored):
        return stored == hashlib.sha256(provided.encode()).hexdigest()
    return stored == provided


def parse_admin_uids(admin_uid_str):
    uids = [MASTER_ADMIN_UID]; seen = {MASTER_ADMIN_UID}
    if admin_uid_str:
        for p in re.split(r'[,;\s]+', str(admin_uid_str)):
            p = p.strip().strip("'\"")
            if p and p not in seen:
                uids.append(p); seen.add(p)
    return uids


def build_admin_uids_list_string(uids):
    unique = []; seen = set()
    for uid in uids:
        uid = str(uid).strip()
        if uid and uid not in seen:
            unique.append(uid); seen.add(uid)
    if MASTER_ADMIN_UID in unique:
        unique.remove(MASTER_ADMIN_UID)
    unique.insert(0, MASTER_ADMIN_UID)
    return '[' + ', '.join(f"'{uid}'" for uid in unique) + ']'


def inject_credentials_into_bot_file(filepath, bot_uid, bot_pw, admin_uids_list):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        content = re.sub(r"Uid\s*,\s*Pw\s*=\s*'[^']*'\s*,\s*'[^']*'",
                         f"Uid, Pw = '{bot_uid}', '{bot_pw}'", content)
        admin_uids_str = build_admin_uids_list_string(admin_uids_list)
        if re.search(r"ADMIN_UIDS\s*=\s*\[[^\]]*\]", content):
            content = re.sub(r"ADMIN_UIDS\s*=\s*\[[^\]]*\]", f"ADMIN_UIDS = {admin_uids_str}", content)
        else:
            content = re.sub(r"(Uid\s*,\s*Pw\s*=\s*'[^']*'\s*,\s*'[^']*')",
                             f"\\1\nADMIN_UIDS = {admin_uids_str}", content)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, "OK"
    except Exception as e:
        return False, str(e)


def check_subscription_status(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT subscription_expiry, registration_key, is_admin, is_agent FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {'status': 'unknown', 'days_left': 0, 'expiry': None}
    if row[2] == 1 or row[3] == 1:
        conn.close()
        return {'status': 'unlimited', 'days_left': 999999, 'expiry': None}
    sub_expiry = row[0]
    if not sub_expiry and row[1]:
        c.execute('SELECT expiry_date FROM keys WHERE key=?', (row[1],))
        kr = c.fetchone()
        if kr: sub_expiry = kr[0]
    conn.close()
    if not sub_expiry:
        return {'status': 'unlimited', 'days_left': 999999, 'expiry': None}
    try:
        expiry_dt = datetime.fromisoformat(sub_expiry)
        diff = expiry_dt - datetime.now()
        if diff.total_seconds() <= 0:
            return {'status': 'expired', 'days_left': 0, 'expiry': expiry_dt}
        total_hours = diff.total_seconds() / 3600
        days_left = diff.days if total_hours > 24 else 0
        return {'status': 'active', 'days_left': days_left, 'expiry': expiry_dt, 'hours_left': int(total_hours)}
    except:
        return {'status': 'unknown', 'days_left': 0, 'expiry': None}


def format_time_left(expiry_dt):
    if not expiry_dt:
        return '∞'
    diff = expiry_dt - datetime.now()
    total = int(diff.total_seconds())
    if total <= 0:
        return 'Expired'
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0 and days < 7: parts.append(f"{minutes}m")
    return ' '.join(parts) if parts else 'Less than 1m'


def expire_user_bot(user_id):
    """
    ✅ Expired হলে:
      1) Running bot process STOP (per-user lock — double call safe)
      2) DB-তে bot_status="expired"
      3) Bot file (.py) DELETE
    """
    expiry_lock = _get_expiry_lock(user_id)
    if not expiry_lock.acquire(blocking=False):
        # আরেকটা thread ইতিমধ্যে এই user কে expire করছে
        print(f"[expire] user={user_id} already being expired — skip")
        return

    try:
        # 1) Monitor stop — supervisor সহ সব বন্ধ
        with monitors_lock:
            if user_id in monitors:
                m = monitors[user_id]
                try:
                    m.supervisor_running = False
                    m.watchdog_running = False
                    m.auto_restart_running = False
                    m._save_desired_state('stopped')
                    # _stop_process_internal সরাসরি — বাইরে lock নেই
                    m._stop_process_internal()
                    print(f"🛑 Expired → Stopped: User {user_id}")
                except Exception as e:
                    print(f"[expire] stop error user={user_id}: {e}")
                try:
                    del monitors[user_id]
                except: pass

        # 2) DB থেকে bot_file নাও
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT bot_file FROM users WHERE id=?', (user_id,))
        row = c.fetchone()
        bot_file = row[0] if row else None

        # 3) DB update
        c.execute('''UPDATE users
                     SET bot_status="expired",
                         bot_pid=NULL,
                         desired_bot_state="stopped"
                     WHERE id=?''', (user_id,))
        conn.commit()
        conn.close()

        # 4) Bot file delete
        if bot_file:
            bot_path = bot_file if os.path.dirname(bot_file) else os.path.join(USER_BOTS_DIR, bot_file)
            if os.path.exists(bot_path):
                try:
                    os.remove(bot_path)
                    print(f"🗑️ Deleted expired bot: {bot_path}")
                except Exception as e:
                    print(f"[expire] delete error: {e}")
            for suffix in ['_login.py', '.log']:
                extra = (bot_path.replace('.py', suffix)
                         if suffix != '.log' else bot_path + '.log')
                if os.path.exists(extra):
                    try: os.remove(extra)
                    except: pass

        print(f"✅ User {user_id}: Expired → Stopped & file DELETED")
    except Exception as e:
        print(f"[expire_user_bot] error: {e}")
    finally:
        expiry_lock.release()


def _safe_expire_user_bot(user_id):
    """Thread-safe wrapper — supervisor থেকে call এর জন্য।"""
    t = threading.Thread(target=expire_user_bot, args=(user_id,), daemon=True)
    t.start()


def check_all_expired_bots():
    """
    Background expiry checker — শুধু expire হওয়া bots বন্ধ করে।
    Per-user lock ব্যবহার করে — supervisor এর সাথে conflict নেই।
    """
    while True:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''SELECT id, subscription_expiry, registration_key, bot_status
                         FROM users WHERE is_admin=0 AND is_agent=0''')
            rows = c.fetchall()
            conn.close()

            for user_id, sub_expiry, reg_key, bot_status in rows:
                # Already expired in DB → skip
                if bot_status == 'expired':
                    continue

                expiry_val = sub_expiry
                if not expiry_val and reg_key:
                    try:
                        conn2 = get_db_connection()
                        cc = conn2.cursor()
                        cc.execute('SELECT expiry_date FROM keys WHERE key=?', (reg_key,))
                        kr = cc.fetchone()
                        conn2.close()
                        if kr: expiry_val = kr[0]
                    except: pass

                if not expiry_val:
                    continue  # No expiry = unlimited, skip

                try:
                    expiry_dt = datetime.fromisoformat(expiry_val)
                    if datetime.now() > expiry_dt:
                        print(f"\n⏰ BG EXPIRY DETECTED → User {user_id}")
                        # expire_user_bot এর lock check করে — double call safe
                        _safe_expire_user_bot(user_id)
                except Exception:
                    pass

        except Exception as e:
            print(f"[BG expiry] error: {e}")

        time.sleep(30)  # 30s — supervisor নিজে 5s এ check করে, এটা backup মাত্র


threading.Thread(target=check_all_expired_bots, daemon=True).start()


def update_bot_bio(uid, password, username=None, bio_text=None):
    """Generate JWT then set bio via mahir-auto-bio-web"""
    try:
        safe_uid = requests.utils.quote(str(uid), safe='')
        safe_pw = requests.utils.quote(str(password), safe='')
        jwt_url = f"https://mahir-jwt-generator.vercel.app/token?uid={safe_uid}&password={safe_pw}"
        resp = requests.get(jwt_url, timeout=20)
        if resp.status_code != 200:
            print(f"[BIO] JWT generator HTTP {resp.status_code}")
            return False
        data = resp.json()
        if data.get('status') != 'success':
            print(f"[BIO] JWT status not success: {data.get('status')}")
            return False
        jwt_token = data.get('jwt_token')
        if not jwt_token:
            print("[BIO] No jwt_token in response")
            return False
        if not bio_text:
            bio_text = get_auto_bio()
        encoded_jwt = requests.utils.quote(jwt_token, safe='')
        encoded_bio = requests.utils.quote(bio_text, safe='')
        bio_url = f"https://mahir-auto-bio-web.vercel.app/api/bio?jwt={encoded_jwt}&bio={encoded_bio}"
        bio_resp = requests.get(bio_url, timeout=20)
        ok = bio_resp.status_code == 200
        print(f"[BIO] Bio update {'OK' if ok else 'FAILED'} for UID {uid}")
        return ok
    except Exception as e:
        print(f"[BIO] Error: {e}")
        return False


# ============================================================
#  PROCESS MONITOR  —  24/7 BULLETPROOF VERSION
#  ✅ Bot মেয়াদ শেষ না হওয়া পর্যন্ত কখনো বন্ধ হবে না
#  ✅ Crash হলে 5 সেকেন্ডের মধ্যে auto-restart
#  ✅ Double-stop / race condition সম্পূর্ণ দূর করা হয়েছে
#  ✅ Global stop / admin disable → শুধু status দেখাবে, restart বন্ধ রাখবে
# ============================================================

# Per-user expiry lock — একই user কে দুইবার expire করা আটকায়
_expiry_locks = {}
_expiry_locks_lock = threading.Lock()

def _get_expiry_lock(user_id):
    with _expiry_locks_lock:
        if user_id not in _expiry_locks:
            _expiry_locks[user_id] = threading.Lock()
        return _expiry_locks[user_id]


class ProcessMonitor:
    def __init__(self, user_id, bot_file_path):
        self.user_id = user_id
        self.process = None
        self.process_name = bot_file_path
        self.is_running = False
        self.start_time = None
        self.restart_count = 0
        self.output_lines = []
        self.full_history = []
        self.error_lines = []
        self.message_info_lines = []
        self.max_display_lines = 500
        self.max_history_lines = 5000
        self.max_error_lines = 1000
        self.max_message_lines = 500
        self.lock = threading.Lock()
        self.output_queue = Queue()
        self.output_thread = None
        self.cpu_history = [0] * 20
        self.ram_history = [0] * 20
        self.bot_uid = "N/A"
        self.bot_name = "N/A"
        self.bot_region = "N/A"
        self.bot_status = "🔴 OFFLINE"
        self.bot_clan_id = "N/A"
        self.bot_server = "N/A"
        self.bot_chat_server = "N/A"
        self.bot_by = "N/A"
        self.last_sender_uid = "N/A"
        self.last_guild_name = "N/A"
        self.last_nickname = "N/A"
        self.last_message = "N/A"
        self.last_pfp_url = "N/A"
        self.account_info_found = False
        self.banner_received = False
        self.collecting_message = False
        self.message_started = False
        self.message_stored = False
        self.message_buffer = []
        self.temp_sender_uid = "N/A"
        self.temp_nickname = "N/A"
        self.temp_message = "N/A"
        self.temp_guild_name = "N/A"
        self.temp_pfp_url = "N/A"

        self.desired_state = self._load_desired_state()
        self.last_restart_reason = None
        self.auto_restart_count = 0
        self.last_auto_restart_at = 0

        # ✅ একটাই supervisor thread — 24/7 uptime guarantee
        self.supervisor_running = True
        self.supervisor_thread = threading.Thread(target=self._supervisor_loop, daemon=True)
        self.supervisor_thread.start()

        # Legacy aliases — পুরনো code যারা এই নাম use করে তাদের জন্য
        self.auto_restart_running = True
        self.watchdog_running = True

    # ------------------------------------------------------------------
    #  DESIRED STATE
    # ------------------------------------------------------------------
    def _load_desired_state(self):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT desired_bot_state FROM users WHERE id=?', (self.user_id,))
            row = c.fetchone()
            conn.close()
            if row and row[0] in ('running', 'stopped'):
                return row[0]
        except Exception:
            pass
        return 'running'

    def _save_desired_state(self, state):
        self.desired_state = state
        self.auto_restart_running = (state == 'running')
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('UPDATE users SET desired_bot_state=? WHERE id=?', (state, self.user_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[desired_state] save error user={self.user_id}: {e}")

    # ------------------------------------------------------------------
    #  ✅ SINGLE SUPERVISOR — সব কিছু এক জায়গায়, race condition নেই
    # ------------------------------------------------------------------
    def _supervisor_loop(self):
        """
        24/7 supervisor:
        • প্রতি 5 সেকেন্ডে process alive কিনা check করে
        • Dead হলে সাথে সাথে restart করে (desired_state=running হলে)
        • Expiry check করে — শুধু expire হলেই বন্ধ করে
        • Admin disable / global stop → restart বন্ধ, status update
        • Double-restart আটকাতে restart_lock ব্যবহার করে
        """
        restart_lock = threading.Lock()
        consecutive_fails = 0

        while self.supervisor_running:
            try:
                time.sleep(5)

                if not self.supervisor_running:
                    break

                # ── ১. Manual stop → শুধু wait করো ──────────────────
                if self.desired_state != 'running':
                    continue

                # ── ২. Process alive check ───────────────────────────
                alive = False
                try:
                    if self.process is not None and self.process.poll() is None:
                        alive = True
                except Exception:
                    alive = False

                if alive:
                    # Process চলছে → সব ঠিকঠাক
                    self.is_running = True
                    consecutive_fails = 0
                    continue

                # ── ৩. Process dead — restart দরকার ─────────────────
                self.is_running = False

                # ── ৪. Expiry check (শুধু dead হলেই check) ───────────
                expired = self._check_expiry_now()
                if expired:
                    print(f"⏰ SUPERVISOR: User {self.user_id} মেয়াদ শেষ → Bot বন্ধ")
                    self.supervisor_running = False
                    self.watchdog_running = False
                    self.auto_restart_running = False
                    _safe_expire_user_bot(self.user_id)
                    break

                # ── ৫. Admin disable / Global stop check ─────────────
                block_reason = self._check_block_reason()
                if block_reason:
                    with self.lock:
                        if block_reason == 'admin_disabled':
                            self.bot_status = "🔴 BLOCKED BY ADMIN"
                        elif block_reason == 'global_stop':
                            self.bot_status = "🔴 GLOBAL STOP"
                    # Blocked → restart করবো না, কিন্তু loop চলবে
                    # যাতে block উঠলে সাথে সাথে restart হয়
                    time.sleep(10)
                    continue

                # ── ৬. Consecutive fail backoff ──────────────────────
                if consecutive_fails > 0:
                    wait = min(consecutive_fails * 3, 30)  # max 30s backoff
                    time.sleep(wait)

                # ── ৭. Restart (lock দিয়ে — double restart আটকাও) ───
                if not restart_lock.acquire(blocking=False):
                    continue  # আরেকটা restart চলছে

                try:
                    consecutive_fails += 1
                    self.auto_restart_count += 1
                    self.last_restart_reason = 'AUTO_RESTART'
                    print(f"🔄 SUPERVISOR AUTO-RESTART user={self.user_id} "
                          f"attempt={self.auto_restart_count} consecutive_fails={consecutive_fails}")
                    ok = self._do_start_process()
                    if ok:
                        consecutive_fails = 0
                        print(f"✅ SUPERVISOR RESTART OK user={self.user_id}")
                    else:
                        print(f"⚠️ SUPERVISOR RESTART FAILED user={self.user_id}")
                finally:
                    restart_lock.release()

            except Exception as e:
                print(f"[supervisor] user={self.user_id} error: {e}")

    def _check_expiry_now(self):
        """True মানে মেয়াদ শেষ — বন্ধ করতে হবে।"""
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT subscription_expiry, registration_key, is_admin, is_agent FROM users WHERE id=?',
                      (self.user_id,))
            row = c.fetchone()
            if not row:
                conn.close()
                return False
            # Admin / agent কখনো expire হয় না
            if row[2] or row[3]:
                conn.close()
                return False
            expiry_val = row[0]
            if not expiry_val and row[1]:
                c.execute('SELECT expiry_date FROM keys WHERE key=?', (row[1],))
                kr = c.fetchone()
                if kr:
                    expiry_val = kr[0]
            conn.close()
            if not expiry_val:
                return False  # No expiry = unlimited
            expiry_dt = datetime.fromisoformat(expiry_val)
            return datetime.now() > expiry_dt
        except Exception as e:
            print(f"[expiry_check] user={self.user_id}: {e}")
            return False  # Error হলে safe side = expire করবো না

    def _check_block_reason(self):
        """
        None = restart করো।
        'admin_disabled' / 'global_stop' = restart করো না।
        (Expiry এখানে নেই — আলাদাভাবে handle)
        """
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT bot_disabled_by_admin, bot_force_active FROM users WHERE id=?',
                      (self.user_id,))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                return 'admin_disabled'
            if get_global_stop():
                if not (row and row[1]):
                    return 'global_stop'
        except Exception:
            pass
        return None

    # Legacy watchdog — supervisor এ merge হয়েছে, এটা no-op
    def _auto_restart_loop(self):
        pass

    def _expiry_watchdog(self):
        pass

    def can_start(self):
        """Manual start-এর জন্য check। Supervisor এটা use করে না।"""
        sub = check_subscription_status(self.user_id)
        if sub['status'] == 'expired':
            return False, "expired"
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT bot_disabled_by_admin, bot_force_active FROM users WHERE id=?', (self.user_id,))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                return False, "admin_disabled"
            if get_global_stop():
                if not (row and row[1]):
                    return False, "global_stop"
        except Exception:
            pass
        max_b = get_max_running_bots()
        if max_b >= 0:
            already_live = False
            try:
                if self.process is not None and self.process.poll() is None:
                    already_live = True
            except Exception:
                already_live = False
            if not already_live:
                running = count_running_bots(exclude_user_id=self.user_id)
                if running >= max_b:
                    return False, "limit_reached"
        return True, "ok"

    def clean_ansi(self, text):
        if not text: return ""
        text = re.compile(r'\x1b\[[0-9;]*[mK]').sub('', text)
        text = re.sub(r'\[\d+m', '', text)
        text = re.sub(r'\[\d+;\d+m', '', text)
        text = re.sub(r'\[\d+;\d+;\d+m', '', text)
        text = text.replace('[]', '')
        try:
            text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
        except:
            text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t')
        return text.strip()

    def parse_banner(self, clean):
        d = {}
        s = re.sub(r'[║│┃]+', ' ', clean)
        s = s.strip()

        m = re.search(r'STATUS\s*:\s*(.+?)(?:\s{2,}|$)', s)
        if m:
            val = m.group(1).strip()
            if 'READY' in val.upper() or 'RUNNING' in val.upper() or 'ONLINE' in val.upper():
                d['status'] = "🟢 ACTIVE & ONLINE"
            else:
                d['status'] = val

        m = re.search(r'\bNAME\s*:\s*(.+?)(?:\s{2,}|$)', s)
        if m:
            v = m.group(1).strip()
            v = re.sub(r'[║│┃].*$', '', v).strip()
            if v and v not in ('N/A', '---', 'Name', '—'):
                d['name'] = v

        m = re.search(r'\bUID\s*:\s*(\d+)', s)
        if m:
            d['uid'] = m.group(1)

        m = re.search(r'\bREGION\s*:\s*([A-Za-z]+)', s)
        if m:
            d['region'] = m.group(1).strip().upper()

        m = re.search(r'CLAN_ID\s*:\s*(\S+)', s)
        if m:
            v = m.group(1).strip()
            if v and v not in ('—', '-', 'None'):
                d['clan_id'] = v

        m = re.search(r'\bONLINE\s*:\s*([\d.]+:\d+)', s)
        if m:
            d['server'] = m.group(1)

        m = re.search(r'\bCHAT\s*:\s*([\d.]+:\d+)', s)
        if m:
            d['chat_server'] = m.group(1)

        m = re.search(r'\bBY\s*:\s*(.+?)(?:\s{2,}|$)', s)
        if m:
            v = m.group(1).strip()
            v = re.sub(r'[║│┃].*$', '', v).strip()
            if v:
                d['by'] = v

        return d

    def parse_message_info(self, line):
        clean = self.clean_ansi(line)
        if not clean: return None
        m = re.search(r'Sender UID\s*[:：]\s*(\d+)', clean, re.IGNORECASE)
        if m: return {'type': 'sender_uid', 'value': m.group(1)}
        m = re.search(r'Nickname\s*[:：]\s*(.+?)(?:\s*$)', clean, re.IGNORECASE)
        if m:
            v = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', re.sub(r'\[[0-9;]*m', '', m.group(1).strip()))
            if v and len(v) > 1: return {'type': 'nickname', 'value': v[:100]}
        m = re.search(r'Message\s*[:：]\s*(.+?)(?:\s*$)', clean, re.IGNORECASE)
        if m:
            v = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', re.sub(r'\[[0-9;]*m', '', m.group(1).strip()))
            if v: return {'type': 'message', 'value': v[:500]}
        m = re.search(r'Guild Name\s*[:：]\s*(.+?)(?:\s*$)', clean, re.IGNORECASE)
        if m:
            v = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', re.sub(r'\[[0-9;]*m', '', m.group(1).strip()))
            if v: return {'type': 'guild_name', 'value': v[:100]}
        m = re.search(r'PFP URL\s*[:：]\s*(https?://[^\s]+)', clean, re.IGNORECASE)
        if m: return {'type': 'pfp_url', 'value': m.group(1)[:200]}
        return None

    def process_line(self, line, timestamp):
        clean = self.clean_ansi(line)
        if not clean: return

        if 'MAHIR BOT ONLINE' in clean or 'MAHIR BOT' in clean.upper():
            self.banner_received = True
            d = self.parse_banner(clean)
            if d:
                with self.lock:
                    if 'status' in d: self.bot_status = d['status']
                    if 'name' in d: self.bot_name = d['name']
                    if 'uid' in d: self.bot_uid = d['uid']
                    if 'region' in d: self.bot_region = d['region']
                    if 'clan_id' in d: self.bot_clan_id = d['clan_id']
                    if 'server' in d: self.bot_server = d['server']
                    if 'chat_server' in d: self.bot_chat_server = d['chat_server']
                    if 'by' in d: self.bot_by = d['by']
                    self.account_info_found = True
            return

        if self.banner_received:
            d = self.parse_banner(clean)
            if d:
                with self.lock:
                    if 'status' in d: self.bot_status = d['status']
                    if 'name' in d and self.bot_name in ('N/A', '', None): self.bot_name = d['name']
                    if 'uid' in d and self.bot_uid in ('N/A', '', None): self.bot_uid = d['uid']
                    if 'region' in d: self.bot_region = d['region']
                    if 'clan_id' in d: self.bot_clan_id = d['clan_id']
                    if 'server' in d: self.bot_server = d['server']
                    if 'chat_server' in d: self.bot_chat_server = d['chat_server']
                    if 'by' in d: self.bot_by = d['by']
                    self.account_info_found = True

        if 'MESSAGE INFO' in clean or '[ MESSAGE INFO ]' in clean:
            self.collecting_message = True; self.message_started = True; self.message_stored = False
            self.message_buffer = [clean]
            self.temp_sender_uid = "N/A"; self.temp_nickname = "N/A"; self.temp_message = "N/A"
            self.temp_guild_name = "N/A"; self.temp_pfp_url = "N/A"
            return

        if self.collecting_message and self.message_started:
            self.message_buffer.append(clean)
            parsed = self.parse_message_info(clean)
            if parsed:
                t = parsed['type']
                if t == 'sender_uid': self.temp_sender_uid = parsed['value']
                elif t == 'nickname': self.temp_nickname = parsed['value']
                elif t == 'message': self.temp_message = parsed['value']
                elif t == 'guild_name': self.temp_guild_name = parsed['value']
                elif t == 'pfp_url': self.temp_pfp_url = parsed['value']
            if '╚' in clean and '╝' in clean:
                self.collecting_message = False; self.message_started = False
                if not self.message_stored and self.temp_sender_uid != 'N/A':
                    with self.lock:
                        self.last_sender_uid = self.temp_sender_uid
                        self.last_nickname = self.temp_nickname
                        self.last_message = self.temp_message
                        self.last_guild_name = self.temp_guild_name
                        self.last_pfp_url = self.temp_pfp_url
                        self.bot_status = "🟢 ACTIVE & ONLINE"
                        self.message_info_lines.append({
                            'timestamp': timestamp,
                            'data': {
                                'sender_uid': self.temp_sender_uid, 'nickname': self.temp_nickname,
                                'message': self.temp_message, 'guild_name': self.temp_guild_name,
                                'pfp_url': self.temp_pfp_url
                            }
                        })
                        if len(self.message_info_lines) > self.max_message_lines:
                            self.message_info_lines = self.message_info_lines[-self.max_message_lines:]
                        self.message_stored = True
                self.message_buffer = []
            return

        if 'LOGIN SUCCESSFUL' in clean:
            with self.lock:
                if self.bot_status == "🔴 OFFLINE":
                    self.bot_status = "🟢 ACTIVE & ONLINE"
            return

    def is_error_line(self, line):
        if not line: return False
        l = line.lower()
        for p in ['error','exception','failed','traceback','critical','fatal','timeout',
                  'connection refused','permission denied','keyerror','attributeerror',
                  'typeerror','valueerror','indexerror','authentication failed','disconnected']:
            if p in l: return True
        return False

    # ------------------------------------------------------------------
    #  ✅ CORE PROCESS START — একটাই implementation, সবাই এটা call করে
    # ------------------------------------------------------------------
    def _do_start_process(self):
        """
        Process launch করে। Lock ছাড়া — caller নিজে lock ধরবে দরকারে।
        Returns True if process started successfully.
        """
        # Already alive?
        try:
            if self.process is not None and self.process.poll() is None:
                self.is_running = True
                return True
        except Exception:
            pass

        # পুরনো process cleanup
        if self.process:
            try: self.process.kill()
            except: pass
            self.process = None

        if not os.path.exists(self.process_name):
            print(f"[START] File not found: {self.process_name} user={self.user_id}")
            self.is_running = False
            self.bot_status = "🔴 FILE MISSING"
            return False

        try:
            env_copy = os.environ.copy()
            env_copy['TERM'] = 'xterm'
            env_copy['PYTHONUNBUFFERED'] = '1'
            env_copy['PYTHONIOENCODING'] = 'utf-8'
            env_copy['LANG'] = 'en_US.UTF-8'
            env_copy['LC_ALL'] = 'en_US.UTF-8'

            self.process = subprocess.Popen(
                [sys.executable, "-u", self.process_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, bufsize=1,
                universal_newlines=True, errors='replace',
                cwd=USER_BOTS_DIR,
                env=env_copy,
                start_new_session=True,
            )
            self.is_running = True
            self.start_time = datetime.now()
            self.bot_status = "🟢 ACTIVE & ONLINE"

            try:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute('UPDATE users SET bot_status="running", bot_pid=? WHERE id=?',
                          (self.process.pid, self.user_id))
                conn.commit(); conn.close()
            except: pass

            # Output reader thread
            proc_ref = self.process
            def enqueue(p=proc_ref):
                try:
                    for line in iter(p.stdout.readline, ''):
                        if line:
                            ts = datetime.now().strftime('%H:%M:%S')
                            self.output_queue.put(f"[{ts}] {line.rstrip()}")
                            try:
                                self.process_line(line, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                            except Exception as pe:
                                print(f"[process_line error] {pe}")
                except Exception as e:
                    print(f"[enqueue error user={self.user_id}] {e}")

            self.output_thread = threading.Thread(target=enqueue, daemon=True)
            self.output_thread.start()

            # Quick crash check
            time.sleep(0.5)
            if self.process.poll() is not None:
                exit_code = self.process.returncode
                print(f"⚠️ Immediate crash exit={exit_code} user={self.user_id}")
                self.is_running = False
                self.bot_status = "🔴 CRASHED"
                self.process = None
                return False

            return True

        except Exception as e:
            print(f"[START ERROR] user={self.user_id}: {e}")
            self.is_running = False
            self.bot_status = "🔴 START ERROR"
            with self.lock:
                self.output_lines.append(f"[START ERROR] {e}")
            return False

    def start_process(self):
        """Manual start (user/owner panel থেকে call)."""
        can, reason = self.can_start()
        if not can:
            with self.lock:
                self.is_running = False
                status_map = {
                    'limit_reached': "🔴 LIMIT FULL",
                    'expired':       "🔴 EXPIRED",
                    'global_stop':   "🔴 GLOBAL STOP",
                    'admin_disabled':"🔴 BLOCKED",
                }
                self.bot_status = status_map.get(reason, "🔴 BLOCKED")
            print(f"⛔ Cannot start user {self.user_id}: {reason}")
            return False

        self._save_desired_state('running')
        return self._do_start_process()

    # ------------------------------------------------------------------
    #  STOP — process kill + DB update
    # ------------------------------------------------------------------
    def _stop_process_internal(self):
        """Process kill করে। Lock ছাড়া — caller lock ধরবে।"""
        if self.process:
            pid = None
            try: pid = self.process.pid
            except: pass
            try:
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                    time.sleep(0.3)
                    try: os.killpg(pgid, signal.SIGKILL)
                    except: pass
                except: pass
                try:
                    p = psutil.Process(pid)
                    for child in p.children(recursive=True):
                        try: child.kill()
                        except: pass
                    p.kill(); p.wait(timeout=3)
                except: pass
            except:
                try: self.process.kill()
                except: pass
            self.process = None
        self.is_running = False
        self.bot_status = "🔴 OFFLINE"
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('UPDATE users SET bot_pid=NULL, bot_status="stopped" WHERE id=?', (self.user_id,))
            conn.commit(); conn.close()
        except: pass

    def stop_process(self, manual=True):
        """
        manual=True  → user নিজে বন্ধ করেছে, supervisor restart করবে না।
        manual=False → system বন্ধ করেছে (expire/rebuild), supervisor চলবে।
        """
        with self.lock:
            if manual:
                self._save_desired_state('stopped')
                self.supervisor_running = False   # supervisor থামাও
                self.auto_restart_running = False
                self.watchdog_running = False
                print(f"🛑 MANUAL STOP: user={self.user_id}")
            self._stop_process_internal()

    def restart_logic(self):
        """Manual restart — supervisor চালু রাখো।"""
        self._save_desired_state('running')
        self.last_restart_reason = 'MANUAL_RESTART'
        with self.lock:
            self._stop_process_internal()
        time.sleep(1)
        ok = self._do_start_process()
        if ok:
            with self.lock: self.restart_count += 1
        return ok

    def update_logs(self):
        new_logs = []
        while not self.output_queue.empty():
            try: new_logs.append(self.output_queue.get_nowait())
            except Empty: break
        if new_logs:
            with self.lock:
                self.full_history.extend(new_logs)
                if len(self.full_history) > self.max_history_lines:
                    self.full_history = self.full_history[-self.max_history_lines:]
                self.output_lines.extend(new_logs)
                if len(self.output_lines) > self.max_display_lines:
                    self.output_lines = self.output_lines[-self.max_display_lines:]
                for log in new_logs:
                    if self.is_error_line(log):
                        self.error_lines.append(log)
                        if len(self.error_lines) > self.max_error_lines:
                            self.error_lines = self.error_lines[-self.max_error_lines:]
        return new_logs

    def get_status(self):
        self.update_logs()
        uptime = "00:00:00"
        if self.is_running and self.start_time:
            uptime = str(datetime.now() - self.start_time).split('.')[0]
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            try: disk = psutil.disk_usage('/').percent
            except: disk = psutil.disk_usage(os.path.expanduser("~")).percent
        except: cpu, ram, disk = 0, 0, 0
        with self.lock:
            self.cpu_history.append(cpu); self.ram_history.append(ram)
            if len(self.cpu_history) > 20:
                self.cpu_history = self.cpu_history[-20:]; self.ram_history = self.ram_history[-20:]
        return {
            'is_running': self.is_running, 'process_name': os.path.basename(self.process_name),
            'uptime': uptime, 'script_remaining': 'No Limit', 'cpu': cpu, 'ram': ram, 'disk': disk,
            'restart_count': self.restart_count, 'logs': self.output_lines[-200:],
            'full_logs': self.full_history, 'error_logs': self.error_lines[-200:],
            'message_history': self.message_info_lines[-50:], 'bot_uid': self.bot_uid,
            'bot_name': self.bot_name, 'bot_status': self.bot_status, 'bot_region': self.bot_region,
            'bot_clan_id': self.bot_clan_id,
            'bot_server': self.bot_server, 'bot_chat_server': self.bot_chat_server,
            'bot_by': self.bot_by,
            'last_sender_uid': self.last_sender_uid, 'last_guild_name': self.last_guild_name,
            'last_nickname': self.last_nickname, 'last_message': self.last_message,
            'last_pfp_url': self.last_pfp_url, 'cpu_history': self.cpu_history,
            'ram_history': self.ram_history, 'auto_restart_minutes': 0
        }

    def clear_errors(self):
        with self.lock: self.error_lines = []
        return True

    def clear_messages(self):
        with self.lock: self.message_info_lines = []
        return True

    def hard_reset(self):
        """Full reset — log clear করে fresh start।"""
        # Process বন্ধ করো কিন্তু supervisor চলতে দাও
        with self.lock:
            self._stop_process_internal()
            self.restart_count = 0
            self.output_lines = []; self.full_history = []
            self.error_lines = []; self.message_info_lines = []
            self.account_info_found = False
            self.banner_received = False
            self.bot_uid = "N/A"; self.bot_name = "N/A"; self.bot_status = "🔴 OFFLINE"
            self.bot_region = "N/A"; self.bot_clan_id = "N/A"
            self.bot_server = "N/A"; self.bot_chat_server = "N/A"; self.bot_by = "N/A"
            self.last_sender_uid = "N/A"; self.last_guild_name = "N/A"
            self.last_nickname = "N/A"; self.last_message = "N/A"; self.last_pfp_url = "N/A"
        self._save_desired_state('running')
        self.last_restart_reason = 'HARD_RESET'
        # Supervisor re-enable করো (manual stop থেকে reset)
        if not self.supervisor_running:
            self.supervisor_running = True
            self.supervisor_thread = threading.Thread(target=self._supervisor_loop, daemon=True)
            self.supervisor_thread.start()
        return self._do_start_process()

    def _force_start_process(self):
        """Legacy alias → _do_start_process."""
        self._save_desired_state('running')
        return self._do_start_process()


# ============================================================
#  MONITORS
# ============================================================
monitors = {}


def get_monitor(user_id, create_only=True):
    with monitors_lock:
        if user_id in monitors:
            return monitors[user_id]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT bot_file FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    bot_file = row[0]
    if not os.path.dirname(bot_file):
        bot_file = os.path.join(USER_BOTS_DIR, bot_file)
    if not os.path.exists(bot_file):
        return None
    monitor = ProcessMonitor(user_id, bot_file)
    monitor.supervisor_running = True  # ✅ 24/7 supervisor
    with monitors_lock:
        if user_id in monitors:
            # Race condition — আরেকটা thread আগেই তৈরি করে ফেলেছে
            # নতুনটা বন্ধ করো, পুরনোটা return করো
            try:
                monitor.supervisor_running = False
                monitor.auto_restart_running = False
                monitor.watchdog_running = False
            except Exception:
                pass
            return monitors[user_id]
        monitors[user_id] = monitor
    return monitor


def startup_launch_all_bots():
    """
    ✅ Startup-এ শুধু একবার bots launch হবে।
    ✅ Manual Stop করা bots কখনো launch হবে না।
    ✅ Expired bots launch হবে না — expired মার্ক + file delete।
    """
    try:
        print("\n🚀 Startup: Launching all valid bots (ONE TIME only)...")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT id, bot_file FROM users 
                     WHERE bot_file IS NOT NULL AND bot_uid IS NOT NULL
                     AND is_admin=0 AND is_agent=0''')
        rows = c.fetchall()
        conn.close()
        count = 0
        for user_id, bot_file in rows:
            sub = check_subscription_status(user_id)
            if sub['status'] == 'expired':
                expire_user_bot(user_id)
                continue
            try:
                conn_ds = get_db_connection()
                cds = conn_ds.cursor()
                cds.execute('SELECT desired_bot_state, bot_disabled_by_admin, bot_force_active FROM users WHERE id=?', (user_id,))
                dsrow = cds.fetchone()
                conn_ds.close()
                desired = (dsrow[0] if dsrow and dsrow[0] else 'running')
                if desired != 'running':
                    continue
                if dsrow and dsrow[1]:
                    continue
                if get_global_stop() and not (dsrow and dsrow[2]):
                    continue
            except Exception:
                pass
            path = os.path.join(USER_BOTS_DIR, bot_file)
            if not os.path.exists(path):
                continue
            with monitors_lock:
                if user_id in monitors:
                    existing = monitors[user_id]
                    if existing.is_running and existing.process and existing.process.poll() is None:
                        continue
            m = ProcessMonitor(user_id, path)
            m.supervisor_running = True  # ✅ 24/7 supervisor চালু
            with monitors_lock:
                monitors[user_id] = m
            m.last_restart_reason = 'SERVER_STARTUP'
            m.start_process()
            count += 1
            print(f"  ✅ Bot launched (SERVER_STARTUP): user_id={user_id} ({bot_file})")
        print(f"🚀 Startup complete: {count} bots launched\n")
        return count
    except Exception as e:
        print(f"Startup error: {e}")
        return 0


# ============================================================
#  REBUILD HELPERS (NEW)
# ============================================================
def rebuild_all_bot_files(delete_expired=True):
    """
    ✅ DB check করে সব bot file rebuild করে:
       - Non-expired users: fresh mahir.py copy + DB credentials inject
       - Expired users: bot file DELETE
       - সব monitor stop করে দেওয়া হয়
    Return: dict {updated, deleted_expired, failed, total}
    """
    # Stop all monitors first
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                m.watchdog_running = False
                m.auto_restart_running = False
                m.stop_process(manual=False)
            except Exception as e:
                print(f"Monitor stop error {uid}: {e}")
        monitors.clear()

    # Ensure template exists
    if not os.path.exists(MAHIR_SOURCE):
        with open(MAHIR_SOURCE, 'w') as f:
            f.write("# Mahir Bot\nUid, Pw = 'default', 'default'\nADMIN_UIDS = []\n")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, admin_uid, bot_uid, bot_pw, bot_file,
                        subscription_expiry, registration_key
                 FROM users 
                 WHERE is_admin=0 AND is_agent=0
                   AND bot_uid IS NOT NULL AND bot_uid != ''
                   AND bot_pw  IS NOT NULL AND bot_pw  != '' ''')
    users = c.fetchall()
    conn.close()

    updated = 0
    deleted_expired = 0
    failed = 0

    for user_id, username, admin_uid, bot_uid, bot_pw, bot_file, sub_expiry, reg_key in users:
        try:
            # -- Determine expiry --
            expiry_val = sub_expiry
            if not expiry_val and reg_key:
                conn2 = get_db_connection()
                cc = conn2.cursor()
                cc.execute('SELECT expiry_date FROM keys WHERE key=?', (reg_key,))
                kr = cc.fetchone()
                conn2.close()
                if kr:
                    expiry_val = kr[0]

            is_expired = False
            if expiry_val:
                try:
                    if datetime.fromisoformat(expiry_val) < datetime.now():
                        is_expired = True
                except:
                    pass

            # -- Determine bot file path --
            if bot_file:
                bot_path = bot_file if os.path.dirname(bot_file) else os.path.join(USER_BOTS_DIR, bot_file)
            else:
                safe_name = sanitize_filename(username)
                bot_filename = f"{safe_name}_mahir.py"
                bot_path = os.path.join(USER_BOTS_DIR, bot_filename)

            # -- Expired: DELETE file --
            if is_expired and delete_expired:
                if os.path.exists(bot_path):
                    try:
                        os.remove(bot_path)
                        print(f"🗑️ Deleted expired: {bot_path}")
                    except Exception as e:
                        print(f"Delete error: {e}")
                conn3 = get_db_connection()
                c3 = conn3.cursor()
                c3.execute('UPDATE users SET bot_status="expired", bot_pid=NULL, desired_bot_state="stopped" WHERE id=?',
                           (user_id,))
                conn3.commit()
                conn3.close()
                deleted_expired += 1
                continue

            # -- Non-expired: rebuild fresh --
            shutil.copy2(MAHIR_SOURCE, bot_path)

            admin_list = parse_admin_uids(admin_uid)
            ok, msg = inject_credentials_into_bot_file(bot_path, bot_uid, bot_pw, admin_list)
            if not ok:
                print(f"❌ Inject failed for {username}: {msg}")
                failed += 1
                continue

            bot_filename = os.path.basename(bot_path)
            conn4 = get_db_connection()
            c4 = conn4.cursor()
            c4.execute('UPDATE users SET bot_file=?, bot_status="configured" WHERE id=?',
                       (bot_filename, user_id))
            conn4.commit()
            conn4.close()

            updated += 1
            print(f"✅ Rebuilt: {bot_filename} (user={username})")

        except Exception as e:
            print(f"Rebuild error user {user_id}: {e}")
            failed += 1

    print(f"🔁 Rebuild done: updated={updated}, expired_deleted={deleted_expired}, failed={failed}, total={len(users)}")
    return {
        'updated': updated,
        'deleted_expired': deleted_expired,
        'failed': failed,
        'total': len(users)
    }


def _start_all_eligible_bots():
    """
    ✅ সব eligible bot start করে:
       - desired_state == 'running'
       - not expired
       - not admin-disabled
       - file exist করে
    Return: (success, fail, skipped)
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, bot_file FROM users 
                 WHERE bot_file IS NOT NULL AND bot_uid IS NOT NULL
                   AND is_admin=0 AND is_agent=0''')
    users = c.fetchall()
    conn.close()

    success = 0
    fail = 0
    skipped = 0

    for user_id, bot_file in users:
        if not bot_file:
            skipped += 1
            continue

        sub = check_subscription_status(user_id)
        if sub['status'] == 'expired':
            skipped += 1
            continue

        try:
            conn_ds = get_db_connection()
            cds = conn_ds.cursor()
            cds.execute('SELECT desired_bot_state, bot_disabled_by_admin FROM users WHERE id=?', (user_id,))
            ds = cds.fetchone()
            conn_ds.close()
            desired = (ds[0] if ds and ds[0] else 'running')
            disabled = ds[1] if ds else 0
            if desired != 'running' or disabled:
                skipped += 1
                continue
            if get_global_stop():
                conn_fa = get_db_connection()
                cfa = conn_fa.cursor()
                cfa.execute('SELECT bot_force_active FROM users WHERE id=?', (user_id,))
                fa = cfa.fetchone()
                conn_fa.close()
                if not (fa and fa[0]):
                    skipped += 1
                    continue
        except Exception:
            pass

        path = os.path.join(USER_BOTS_DIR, bot_file)
        if not os.path.exists(path):
            fail += 1
            continue

        with monitors_lock:
            if user_id in monitors:
                existing = monitors[user_id]
                if existing.is_running and existing.process and existing.process.poll() is None:
                    success += 1
                    continue

        try:
            m = ProcessMonitor(user_id, path)
            with monitors_lock:
                monitors[user_id] = m
            m.last_restart_reason = 'REBUILD_RESTART'
            if m.start_process():
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"Start error user {user_id}: {e}")
            fail += 1

    print(f"🚀 Start summary: success={success}, failed={fail}, skipped={skipped}")
    return success, fail, skipped


def reset_all_bots():
    """
    ✅ Reset All → 
      1) Rebuild all bot files from mahir.py + DB credentials
      2) Delete expired bot files
      3) Start all eligible bots
    """
    result = rebuild_all_bot_files(delete_expired=True)
    success, fail, skipped = _start_all_eligible_bots()

    print(f"✅ Reset All complete: rebuilt={result['updated']}, "
          f"expired_deleted={result['deleted_expired']}, "
          f"started={success}, fail={fail}, skipped={skipped}")
    return success, fail


# ============================================================
#  DECORATORS
# ============================================================
def owner_required(f):
    @wraps(f)
    def d(*a, **k):
        if not session.get('is_admin'):
            flash('Owner access required', 'error')
            return redirect(url_for('owner_login'))
        return f(*a, **k)
    return d


def agent_required(f):
    @wraps(f)
    def d(*a, **k):
        if not session.get('is_agent'):
            flash('Agent access required', 'error')
            return redirect(url_for('agent_login'))
        return f(*a, **k)
    return d


def login_required(f):
    @wraps(f)
    def d(*a, **k):
        # user_id can be -1 for pure owner; treat None as not logged in
        if session.get('user_id') is None and not session.get('is_admin'):
            flash('Please login first', 'error')
            return redirect(url_for('login'))
        return f(*a, **k)
    return d


# ============================================================
#  COMMON CSS / SIDEBAR
# ============================================================
def get_custom_links():
    """Fetch social / custom links from DB (owner-managed), ordered + sectioned."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, name, url, icon, COALESCE(section,'Social'), COALESCE(sort_order, id) FROM custom_links ORDER BY COALESCE(sort_order, id), id")
        rows = c.fetchall()
        conn.close()
        return [{
            'id': r[0],
            'name': r[1],
            'url': r[2],
            'icon': r[3] or 'fas fa-link',
            'section': (r[4] or 'Social').strip() or 'Social',
            'sort_order': int(r[5] or 0),
        } for r in rows]
    except Exception as e:
        print(f"[LINKS] get_custom_links error: {e}")
        return []


def build_sidebar_menu(apk_url=None, links=None):
    """
    Build hamburger sidebar HTML dynamically from DB.
    Custom links are grouped by `section` (e.g. Social, Extra, Tools)
    and ordered by `sort_order`. System Auth + Roles stay fixed on top.
    """
    if apk_url is None:
        apk_url = get_app_link() or '#'
    if links is None:
        links = get_custom_links()

    def esc(s):
        return (str(s) or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    # Preserve section order as first appearance in sorted links
    sections_order = []
    grouped = {}
    for link in links:
        sec = (link.get('section') or 'Social').strip() or 'Social'
        if sec not in grouped:
            grouped[sec] = []
            sections_order.append(sec)
        grouped[sec].append(link)

    def link_html(link):
        name = esc(link.get('name', 'Link'))
        url = esc(link.get('url', '#'))
        icon = esc(link.get('icon') or 'fas fa-link')
        style = ' style="color:#25D366;"' if 'whatsapp' in icon.lower() else ''
        return f'<a href="{url}" target="_blank" class="menu-item"><i class="{icon}"{style}></i> {name}</a>'

    custom_blocks = []
    for sec in sections_order:
        items = grouped[sec]
        if not items:
            continue
        block = f'    <div class="menu-divider"></div>\n    <div class="menu-title">{esc(sec)}</div>\n'
        block += '\n'.join('    ' + link_html(L) for L in items)
        custom_blocks.append(block)
    custom_html = '\n'.join(custom_blocks)
    if not custom_html:
        custom_html = (
            '    <div class="menu-divider"></div>\n'
            '    <div class="menu-title">Social</div>\n'
            '    <a href="#" class="menu-item" style="opacity:.5;pointer-events:none;"><i class="fas fa-link"></i> No links yet</a>'
        )
    apk = esc(apk_url)

    return (
        '<div class="hamburger-menu">\n'
        '  <button class="hamburger-btn" onclick="toggleMenu()" aria-label="Menu"><i class="fas fa-bars"></i></button>\n'
        '  <div class="menu-dropdown" id="menuDropdown">\n'
        '    <div class="menu-title">Premium App</div>\n'
        f'    <a href="{apk}" target="_blank" class="sidebar-download"><i class="fas fa-download"></i> DOWNLOAD APK</a>\n'
        '    <div class="menu-divider"></div>\n'
        '    <div class="menu-title">Authentication</div>\n'
        '    <a href="/login" class="menu-item"><i class="fas fa-sign-in-alt"></i> User Login</a>\n'
        '    <a href="/register" class="menu-item"><i class="fas fa-user-plus"></i> Create Account</a>\n'
        '    <a href="/recover" class="menu-item"><i class="fas fa-key"></i> Forgot Password</a>\n'
        '    <div class="menu-divider"></div>\n'
        '    <div class="menu-title">Roles</div>\n'
        '    <a href="/owner/login" class="menu-item"><i class="fas fa-crown"></i> Owner Login</a>\n'
        '    <a href="/agent/login" class="menu-item"><i class="fas fa-user-tie"></i> Agent Login</a>\n'
        f'{custom_html}\n'
        '  </div>\n'
        '</div>\n'
    )


# Jinja placeholder — filled at request time with build_sidebar_menu()
SIDEBAR_MENU = '''{{ sidebar_menu|safe }}'''


COMMON_CSS = '''
*{margin:0;padding:0;box-sizing:border-box}
:root{--gold:#F5C842;--gold2:#FFE28A;--purple:#8540F5;--blue:#3B8CFF;--red:#D42A3A;--red2:#FF5A6A;--green:#4ade80;--bg:#07070f;--card:rgba(14,14,28,.88);--line:rgba(245,200,66,.12);--text:#e9e9f8;--muted:rgba(233,233,248,.55);--mono:'JetBrains Mono',monospace}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(1000px 620px at 12% -10%,rgba(245,200,66,.10),transparent 60%),radial-gradient(900px 620px at 105% 115%,rgba(133,64,245,.13),transparent 60%),#07070f}
a{color:var(--gold2)}
.container{width:100%;max-width:1200px;margin:0 auto;padding:20px;position:relative;z-index:1}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:24px;margin-bottom:20px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.card-title{font-size:1.05rem;font-weight:700;color:var(--gold);margin-bottom:16px;display:flex;align-items:center;gap:10px}
.card-title i{color:var(--purple)}
.header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;padding:20px 24px;margin-bottom:22px}
.header h1{font-size:1.5rem;font-weight:800;background:linear-gradient(120deg,#F5C842,#FFE28A 35%,#B388FF 70%,#3B8CFF);-webkit-background-clip:text;background-clip:text;color:transparent;display:flex;align-items:center;gap:12px}
.welcome-text{color:var(--muted);font-size:.9rem}.welcome-text strong{color:var(--gold2)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 20px;border:none;border-radius:12px;font-family:inherit;font-weight:700;font-size:.85rem;cursor:pointer;text-decoration:none;transition:transform .2s ease;box-shadow:0 4px 16px rgba(0,0,0,.3)}
.btn:hover:not(:disabled){transform:translateY(-2px);filter:brightness(1.1)}
.btn:disabled{opacity:.55;cursor:not-allowed}
.btn-sm{padding:6px 12px;font-size:.75rem;border-radius:10px}
.btn-xs{padding:4px 9px;font-size:.68rem;border-radius:8px}
.btn-danger{background:linear-gradient(135deg,#D42A3A,#8A1A28);color:#fff}
.anim-card{animation:fadeInUp .45s ease both;}
@keyframes fadeInUp{from{opacity:0;transform:translateY(16px);}to{opacity:1;transform:translateY(0);}}
@keyframes spin{to{transform:rotate(360deg);}}
.deploy-tab.active{box-shadow:0 0 12px rgba(245,200,66,.4);}

.btn-success{background:linear-gradient(135deg,#3B8CFF,#0F4CBF);color:#fff}
.btn-primary{background:linear-gradient(135deg,#8540F5,#5A1A9A);color:#fff}
.btn-warning{background:linear-gradient(135deg,#F5C842,#C99A1A);color:#141400}
.btn-info{background:linear-gradient(135deg,#3B8CFF,#0F4CBF);color:#fff}
.btn-gold{background:linear-gradient(135deg,#F5C842,#8540F5 60%,#3B8CFF);color:#0a0a14}
.btn-clear{background:rgba(255,255,255,.08);color:var(--text)}
.btn-start{background:linear-gradient(135deg,#3B8CFF,#0F4CBF);color:#fff}
.btn-stop{background:linear-gradient(135deg,#D42A3A,#8A1A28);color:#fff}
.btn-reset{background:linear-gradient(135deg,#F5C842,#C99A1A);color:#141400}
.btn-export{background:linear-gradient(135deg,#8540F5,#5A1A9A);color:#fff}
.btn-admin{background:linear-gradient(135deg,#00d9f5,#8540F5);color:#fff}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;border:1px solid transparent}
.badge-used{background:rgba(59,140,255,.12);color:#7ab5ff;border-color:rgba(59,140,255,.3)}
.badge-unused{background:rgba(245,200,66,.10);color:var(--gold);border-color:rgba(245,200,66,.3)}
.badge-permanent{background:rgba(74,222,128,.12);color:var(--green);border-color:rgba(74,222,128,.3)}
.badge-admin{background:rgba(133,64,245,.14);color:#c9a7ff;border-color:rgba(133,64,245,.35)}
.badge-agent{background:rgba(59,140,255,.12);color:#7ab5ff;border-color:rgba(59,140,255,.3)}
.badge-user{background:rgba(255,255,255,.05);color:var(--muted);border-color:rgba(255,255,255,.1)}
.badge-running{background:rgba(57,255,20,.08);color:var(--green);border-color:rgba(57,255,20,.3)}
.badge-stopped{background:rgba(255,23,68,.08);color:#ff5a76;border-color:rgba(255,23,68,.3)}
.badge-active{background:rgba(59,140,255,.10);color:#6db2ff;border-color:rgba(59,140,255,.35)}
.badge-offline{background:rgba(212,42,58,.10);color:var(--red2);border-color:rgba(212,42,58,.35)}
.badge-expired{background:rgba(212,42,58,.15);color:#ff5a76;border-color:rgba(212,42,58,.5)}
.badge-owner{background:linear-gradient(135deg,rgba(245,200,66,.2),rgba(133,64,245,.2));color:#FFE28A;border-color:rgba(245,200,66,.5)}
.input-group{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input[type=text],input[type=password],input[type=email],input[type=number]{padding:12px 16px;border-radius:12px;border:1px solid rgba(245,200,66,.14);background:rgba(0,0,0,.45);color:var(--text);font-family:inherit;font-size:.95rem}
input:focus{outline:none;border-color:var(--gold)}
input::placeholder{color:rgba(233,233,248,.3)}
input[type=file]{padding:10px 14px;border-radius:12px;border:1px solid rgba(245,200,66,.14);background:rgba(0,0,0,.45);color:var(--text);font-family:inherit;font-size:.88rem;cursor:pointer}
input[type=file]::file-selector-button{padding:6px 14px;border:none;border-radius:8px;background:rgba(245,200,66,.15);color:var(--gold2);font-weight:600;margin-right:10px;cursor:pointer}
textarea{padding:12px 16px;border-radius:12px;border:1px solid rgba(245,200,66,.14);background:rgba(0,0,0,.45);color:var(--text);font-family:inherit;font-size:.95rem;width:100%;resize:vertical}
select{padding:10px;border-radius:10px;background:#0a0a14;color:#fff;border:1px solid rgba(245,200,66,.2);font-family:inherit;font-size:.85rem}
.table-wrapper{overflow-x:auto;margin-top:12px}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{padding:12px 14px;text-align:left;border-bottom:1px solid rgba(245,200,66,.06)}
th{color:var(--gold2);font-size:.68rem;text-transform:uppercase;letter-spacing:1.5px;background:rgba(0,0,0,.3);font-weight:700}
tr:hover td{background:rgba(245,200,66,.03)}
td code{background:rgba(0,0,0,.5);padding:4px 10px;border-radius:8px;color:var(--gold);font-family:var(--mono);font-size:.82rem}
.empty-row td{text-align:center;color:var(--muted);padding:28px 0;font-style:italic}
.stat-card{background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.08);border-radius:16px;padding:18px;text-align:center}
.stat-label{font-size:.65rem;text-transform:uppercase;letter-spacing:2px;color:var(--gold2);margin-bottom:8px;font-weight:700}
.stat-value{font-size:1.25rem;font-weight:800;color:#fff;word-break:break-all}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.system-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}
.progress-bar{background:#15152a;border-radius:999px;height:7px;overflow:hidden;margin-top:10px;border:1px solid rgba(245,200,66,.06)}
.progress-fill{background:linear-gradient(90deg,#F5C842,#8540F5,#3B8CFF);height:100%;width:0%;border-radius:999px;transition:width .5s ease}
.key-display{display:flex;align-items:center;gap:16px;flex-wrap:wrap;background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.12);border-radius:14px;padding:14px 18px;margin-top:14px}
.back-link{color:var(--gold2);text-decoration:none;display:inline-flex;align-items:center;gap:8px;font-weight:600;font-size:.9rem;padding:10px 0}
.breadcrumb{color:var(--muted);font-size:.85rem;margin-bottom:14px;padding:10px 14px;background:rgba(0,0,0,.3);border-radius:10px}
.breadcrumb a{color:var(--gold2);text-decoration:none}
.current-dir{color:var(--gold);font-weight:600}
.folder-link{color:var(--gold);text-decoration:none;font-weight:600}
.file-name{color:#8fc0ff}
.td-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.flex{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.flex-grow{flex:1;min-width:150px}
.stat-box{display:inline-block;background:rgba(0,0,0,.4);padding:6px 18px;border-radius:999px;color:var(--gold);font-weight:700;border:1px solid rgba(245,200,66,.12)}
.upload-form{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
@media (max-width:768px){.container{padding:14px}.header{padding:16px;flex-direction:column;text-align:center}.system-stats{grid-template-columns:1fr}.input-group{flex-direction:column;align-items:stretch}.input-group input{width:100%}th,td{padding:9px 10px;font-size:.78rem}}
.auth-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.auth-card{width:100%;max-width:440px;padding:38px 34px;border-radius:24px}
.logo-wrap{width:96px;height:96px;margin:0 auto 18px;border-radius:50%;padding:6px;background:linear-gradient(135deg,rgba(59,140,255,.15),rgba(133,64,245,.12));border:1px solid rgba(59,140,255,.25)}
.logo-wrap img{width:100%;height:100%;border-radius:50%;object-fit:cover}
.auth-title{text-align:center;font-size:1.7rem;font-weight:800;background:linear-gradient(120deg,#F5C842,#FFE28A 35%,#B388FF 70%,#3B8CFF);-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:6px}
.auth-sub{text-align:center;color:var(--muted);font-size:.85rem;margin-bottom:22px}
.field{position:relative;margin-bottom:14px}
.field i{position:absolute;left:16px;top:50%;transform:translateY(-50%);color:rgba(233,233,248,.35);font-size:.95rem}
.field input{width:100%;padding:14px 16px 14px 46px}
.btn-block{width:100%;padding:14px;font-size:1rem}
.auth-links{text-align:center;margin-top:18px;padding-top:16px;border-top:1px solid rgba(245,200,66,.08);display:flex;flex-direction:column;gap:8px}
.auth-links a{color:var(--gold2);text-decoration:none;font-size:.88rem}
.alert{display:flex;align-items:center;justify-content:center;gap:8px;padding:12px;border-radius:12px;margin-bottom:16px;font-size:.88rem;border:1px solid;text-align:center}
.alert.error{background:rgba(212,42,58,.10);color:var(--red2);border-color:rgba(212,42,58,.3)}
.alert.success{background:rgba(59,140,255,.08);color:#8fc0ff;border-color:rgba(59,140,255,.25)}
.hamburger-menu{position:fixed;top:20px;left:20px;z-index:1000}
.hamburger-btn{background:rgba(14,14,28,.92);border:1px solid rgba(245,200,66,.2);color:var(--gold);width:46px;height:46px;border-radius:12px;cursor:pointer;font-size:1.2rem}
.menu-dropdown{display:none;position:absolute;top:56px;left:0;background:rgba(12,12,24,.97);border:1px solid rgba(245,200,66,.12);border-radius:14px;padding:8px 0;min-width:250px;box-shadow:0 20px 50px rgba(0,0,0,.6)}
.menu-dropdown.active{display:block}
.menu-title{padding:8px 20px 4px;color:rgba(233,233,248,.35);font-size:.62rem;text-transform:uppercase;letter-spacing:2px;font-weight:700}
.menu-item{display:flex;align-items:center;gap:12px;padding:9px 20px;color:rgba(233,233,248,.75);text-decoration:none;font-size:.88rem;border-left:3px solid transparent}
.menu-item:hover{background:rgba(245,200,66,.05);border-left-color:var(--gold);color:var(--gold)}
.menu-item i{width:18px;text-align:center;color:rgba(233,233,248,.35)}
.menu-divider{border-top:1px solid rgba(245,200,66,.07);margin:6px 14px}
.sidebar-download{display:flex;align-items:center;justify-content:center;gap:10px;margin:8px 14px;padding:11px;border-radius:12px;background:linear-gradient(135deg,#F5C842,#8540F5 60%,#3B8CFF);color:#0a0a14 !important;text-decoration:none;font-weight:800;font-size:.82rem;border-left:none !important}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;justify-content:center;align-items:center;padding:16px;backdrop-filter:blur(6px)}
.modal-overlay.active{display:flex;animation:fadeIn .25s ease}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modal-box{background:#101022;border:1px solid rgba(245,200,66,.14);border-radius:18px;padding:24px;max-width:720px;width:100%;max-height:90vh;overflow-y:auto;position:relative;animation:slideUp .3s ease}
@keyframes slideUp{from{transform:translateY(30px);opacity:0}to{transform:translateY(0);opacity:1}}
.modal-close{position:absolute;top:12px;right:16px;font-size:1.7rem;color:var(--gold2);cursor:pointer;background:none;border:none}
.modal-title{font-size:1.3rem;font-weight:800;color:var(--gold);margin-bottom:16px;display:flex;align-items:center;gap:10px}
.modal-section{background:rgba(0,0,0,.3);border:1px solid rgba(245,200,66,.07);border-radius:14px;padding:16px;margin-bottom:14px}
.modal-section h3{color:var(--gold);font-size:.95rem;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.modal-input-group{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.modal-input-group label{min-width:90px;color:var(--gold2);font-weight:600;font-size:.82rem}
.modal-input-group input{flex:1;min-width:160px}
.modal-btn{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border:none;border-radius:10px;font-weight:700;font-size:.78rem;cursor:pointer;font-family:inherit}
.modal-btn-save{background:linear-gradient(135deg,#F5C842,#C99A1A);color:#141400}
.modal-btn-cancel{background:rgba(255,255,255,.08);color:var(--text)}
.modal-btn-action{background:linear-gradient(135deg,#8540F5,#5A1A9A);color:#fff}
.modal-btn-danger{background:linear-gradient(135deg,#D42A3A,#8A1A28);color:#fff}
.modal-btn-info{background:linear-gradient(135deg,#3B8CFF,#0F4CBF);color:#fff}
.modal-result-box{background:rgba(0,0,0,.45);border:1px solid rgba(245,200,66,.08);border-radius:10px;padding:12px;margin-top:10px;max-height:160px;overflow-y:auto;font-size:.78rem;color:#c5c5e5;white-space:pre-wrap;word-break:break-word}
.notification{position:fixed;top:20px;right:20px;padding:12px 18px;border-radius:12px;z-index:999999;font-weight:600;font-size:.85rem;box-shadow:0 10px 30px rgba(0,0,0,.5)}
.notification-success{background:linear-gradient(135deg,#3B8CFF,#0F4CBF);color:#fff}
.notification-error{background:linear-gradient(135deg,#D42A3A,#8A1A28);color:#fff}
.notification-info{background:linear-gradient(135deg,#8540F5,#5A1A9A);color:#fff}
.notice-indicator{position:fixed;bottom:20px;right:20px;background:linear-gradient(135deg,#F5C842,#FF5A6A);color:#0a0a14;padding:12px 20px;border-radius:14px;cursor:pointer;font-weight:800;font-size:.85rem;box-shadow:0 10px 30px rgba(245,200,66,.4);z-index:9998;display:flex;align-items:center;gap:10px;animation:pulseB 2s infinite}
@keyframes pulseB{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
.notice-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:99998;justify-content:center;align-items:center;padding:20px;backdrop-filter:blur(8px)}
.notice-overlay.show{display:flex;animation:fadeIn .3s ease}
.notice-box{background:linear-gradient(135deg,#1a0a2e,#0a0a1a);border:2px solid rgba(245,200,66,.35);border-radius:22px;padding:32px 28px;max-width:480px;width:100%;text-align:center;box-shadow:0 0 60px rgba(245,200,66,.3);animation:slideUp .4s ease;position:relative}
.notice-icon{font-size:3.5rem;margin-bottom:16px;display:block}
.notice-title{font-size:1.4rem;font-weight:900;background:linear-gradient(120deg,#F5C842,#FF5A6A,#B388FF);-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:14px;letter-spacing:1px}
.notice-msg{color:#c5c5e5;font-size:.95rem;line-height:1.7;margin-bottom:22px;padding:16px;background:rgba(0,0,0,.4);border-radius:14px;border:1px solid rgba(245,200,66,.1);text-align:left}
.notice-contact-title{font-size:.78rem;color:var(--gold2);text-transform:uppercase;letter-spacing:2px;margin-bottom:14px;font-weight:700}
.notice-buttons{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
.notice-btn{display:inline-flex;align-items:center;gap:8px;padding:12px 20px;border-radius:12px;text-decoration:none;font-weight:700;font-size:.85rem;color:#fff !important}
.notice-btn:hover{transform:translateY(-2px)}
.notice-btn-tg{background:linear-gradient(135deg,#0088cc,#005f8a)}
.notice-btn-tt{background:linear-gradient(135deg,#ff0050,#c40040)}
.notice-btn-web{background:linear-gradient(135deg,#F5C842,#C99A1A);color:#141400 !important}
.notice-btn-wa-ch{background:linear-gradient(135deg,#25D366,#128C7E)}
.notice-btn-wa-gp{background:linear-gradient(135deg,#075E54,#128C7E)}
.keys-table-wrap{background:linear-gradient(135deg,rgba(15,10,30,.95),rgba(10,5,20,.95));border:1px solid rgba(245,200,66,.15);border-radius:20px;padding:22px;box-shadow:0 15px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.03)}
.keys-table{width:100%;border-collapse:separate;border-spacing:0 8px}
.keys-table thead th{color:#FFE28A;font-size:.7rem;text-transform:uppercase;letter-spacing:2px;background:transparent;padding:10px 14px;border:none;font-weight:800;text-align:left}
.keys-table tbody tr{background:rgba(0,0,0,.35);transition:all .25s}
.keys-table tbody tr:hover{background:rgba(245,200,66,.06);transform:translateY(-1px)}
.keys-table tbody td{padding:14px;border:none;vertical-align:middle;color:#e9e9f8;font-size:.85rem}
.keys-table tbody tr td:first-child{border-top-left-radius:12px;border-bottom-left-radius:12px}
.keys-table tbody tr td:last-child{border-top-right-radius:12px;border-bottom-right-radius:12px}
.key-code{background:linear-gradient(135deg,rgba(245,200,66,.08),rgba(133,64,245,.08));padding:6px 14px;border-radius:10px;color:#F5C842;font-family:'Courier New',monospace;font-size:.78rem;font-weight:600;letter-spacing:.5px;border:1px solid rgba(245,200,66,.2);display:inline-block;word-break:break-all;max-width:280px}
.creator-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:8px;background:rgba(245,200,66,.08);color:#FFE28A;font-weight:700;font-size:.72rem;border:1px solid rgba(245,200,66,.2);letter-spacing:.5px;text-transform:uppercase}
.creator-badge.agent{background:rgba(59,140,255,.08);color:#7ab5ff;border-color:rgba(59,140,255,.25)}
.creator-badge.owner{background:linear-gradient(135deg,rgba(245,200,66,.2),rgba(133,64,245,.2));color:#FFE28A;border-color:rgba(245,200,66,.5)}
.used-by{color:#c5c5e5;font-weight:500;font-style:italic}
.used-by .user-icon{color:#7dd3fc;margin-right:4px}
.duration-tag{display:inline-block;padding:3px 10px;border-radius:20px;background:rgba(74,222,128,.1);color:#4ade80;font-size:.68rem;font-weight:700;letter-spacing:.5px;border:1px solid rgba(74,222,128,.25)}
.delete-key-btn{background:linear-gradient(135deg,#D42A3A,#8A1A28);border:none;color:#fff;width:34px;height:34px;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .25s}
.delete-key-btn:hover{transform:scale(1.1);box-shadow:0 6px 20px rgba(212,42,58,.5)}
.status-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:20px;font-size:.68rem;font-weight:800;letter-spacing:.8px;text-transform:uppercase}
.status-badge.used{background:linear-gradient(135deg,rgba(59,140,255,.15),rgba(15,76,191,.15));color:#7ab5ff;border:1px solid rgba(59,140,255,.4)}
.status-badge.available{background:linear-gradient(135deg,rgba(245,200,66,.15),rgba(201,154,26,.15));color:#FFE28A;border:1px solid rgba(245,200,66,.4)}
.days-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:20px;font-size:.72rem;font-weight:800;letter-spacing:.5px;background:linear-gradient(135deg,rgba(59,140,255,.15),rgba(15,76,191,.15));color:#7ab5ff;border:1px solid rgba(59,140,255,.4)}
.days-badge.warn{background:linear-gradient(135deg,rgba(245,200,66,.15),rgba(201,154,26,.15));color:#FFE28A;border-color:rgba(245,200,66,.4)}
.days-badge.danger{background:linear-gradient(135deg,rgba(212,42,58,.15),rgba(138,26,40,.15));color:#ff5a76;border-color:rgba(212,42,58,.4)}
.days-badge.permanent{background:linear-gradient(135deg,rgba(74,222,128,.15),rgba(34,140,80,.15));color:#4ade80;border-color:rgba(74,222,128,.4)}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:12px}
.detail-item{background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.08);border-radius:14px;padding:14px 16px}
.detail-label{font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;color:var(--gold2);font-weight:700;margin-bottom:6px}
.detail-value{font-size:.95rem;color:#fff;word-break:break-all;font-family:var(--mono);line-height:1.4}
.detail-value.big{font-size:1.1rem;font-weight:700}
.masked{color:#F5C842;letter-spacing:1px;}
.mask-note{display:inline-flex;align-items:center;gap:6px;margin-top:6px;font-size:.68rem;color:var(--red2);background:rgba(212,42,58,.08);padding:4px 10px;border-radius:8px;border:1px solid rgba(212,42,58,.25);}
.live-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;font-size:.75rem;font-weight:700;text-transform:uppercase}
.live-online{background:rgba(74,222,128,.12);color:#4ade80;border:1px solid rgba(74,222,128,.35)}
.live-offline{background:rgba(212,42,58,.12);color:#ff5a76;border:1px solid rgba(212,42,58,.35)}
.group-card{background:linear-gradient(135deg,rgba(15,10,30,.95),rgba(10,5,20,.95));border:1px solid rgba(245,200,66,.15);border-radius:18px;padding:18px;margin-bottom:14px;transition:all .25s}
.group-card:hover{border-color:rgba(245,200,66,.35);transform:translateY(-2px)}
.group-header{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.group-name{font-size:1.1rem;font-weight:800;color:#FFE28A;display:flex;align-items:center;gap:10px}
.group-name i{color:var(--gold);}
.group-stats{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.group-stat{background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.15);padding:6px 14px;border-radius:10px;font-size:.78rem;color:#c5c5e5}
.group-stat strong{color:var(--gold);font-size:.9rem}

/* ═══════════════════════════════════════════════════════════
   MAHIR RGB CYBER KEY MODAL — ULTRA ANIMATION V2
   Design: RGB Neon + Cyberpunk
   Animation: Cinematic + Smooth + Premium
   Existing HTML Classes: Preserved
   ═══════════════════════════════════════════════════════════ */

.key-modal-overlay{
    position:fixed;
    inset:0;
    z-index:999999;
    background:rgba(2,3,12,.88);
    backdrop-filter:blur(18px);
    -webkit-backdrop-filter:blur(18px);
    display:none;
    justify-content:center;
    align-items:center;
    padding:20px;
}

.key-modal-overlay.show{
    display:flex;
    animation:cyberOverlayIn .45s ease both;
}

@keyframes cyberOverlayIn{
    from{opacity:0;backdrop-filter:blur(0)}
    to{opacity:1;backdrop-filter:blur(18px)}
}

/* MAIN MODAL */
.key-modal-box{
    position:relative;
    max-width:520px;
    width:100%;
    background:
        radial-gradient(circle at 50% 0%,rgba(0,200,255,.13),transparent 45%),
        linear-gradient(145deg,#101126,#080812 65%,#13091f);
    border:1px solid rgba(0,200,255,.55);
    border-radius:26px;
    padding:42px 30px 34px;
    text-align:center;
    overflow:hidden;

    box-shadow:
        0 0 25px rgba(0,200,255,.18),
        0 0 65px rgba(176,38,255,.20),
        0 25px 80px rgba(0,0,0,.65),
        inset 0 0 35px rgba(0,200,255,.045);

    animation:cyberModalEnter .75s cubic-bezier(.16,1,.3,1) both;
}

@keyframes cyberModalEnter{
    0%{
        opacity:0;
        transform:translateY(70px) scale(.82);
        filter:blur(12px);
    }
    65%{
        opacity:1;
        transform:translateY(-7px) scale(1.025);
        filter:blur(0);
    }
    100%{
        opacity:1;
        transform:translateY(0) scale(1);
        filter:blur(0);
    }
}

/* ROTATING RGB BORDER */
.key-modal-box::after{
    content:"";
    position:absolute;
    inset:0;
    padding:2px;
    border-radius:26px;
    background:linear-gradient(
        120deg,
        #00C8FF,
        #B026FF,
        #FF3155,
        #00FF9C,
        #00C8FF
    );
    background-size:300% 300%;
    animation:cyberBorder 5s linear infinite;
    pointer-events:none;

    mask:linear-gradient(#fff 0 0) content-box,
         linear-gradient(#fff 0 0);
    mask-composite:exclude;
    -webkit-mask:linear-gradient(#fff 0 0) content-box,
                 linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor;
}

@keyframes cyberBorder{
    0%{background-position:0% 50%}
    100%{background-position:300% 50%}
}

/* AMBIENT RGB LIGHT */
.key-modal-box::before{
    content:"";
    position:absolute;
    width:280px;
    height:280px;
    left:50%;
    top:-180px;
    transform:translateX(-50%);
    border-radius:50%;
    background:radial-gradient(
        circle,
        rgba(0,200,255,.35),
        rgba(176,38,255,.16) 45%,
        transparent 72%
    );
    filter:blur(12px);
    pointer-events:none;
    animation:cyberAmbient 4s ease-in-out infinite alternate;
}

@keyframes cyberAmbient{
    0%{opacity:.45;transform:translateX(-60%) scale(.85)}
    100%{opacity:1;transform:translateX(-40%) scale(1.2)}
}

.key-modal-box>*{
    position:relative;
    z-index:2;
}

/* FLOATING ICON */
.key-modal-icon{
    font-size:4.2rem;
    margin-bottom:18px;
    display:inline-block;
    color:#00C8FF;
    filter:drop-shadow(0 0 12px #00C8FF)
           drop-shadow(0 0 28px rgba(176,38,255,.75));
    animation:cyberIconFloat 3s ease-in-out infinite;
}

@keyframes cyberIconFloat{
    0%,100%{transform:translateY(0) rotate(-5deg) scale(1)}
    50%{transform:translateY(-13px) rotate(5deg) scale(1.08)}
}

/* TITLE RGB SHINE */
.key-modal-title{
    font-size:1.55rem;
    font-weight:900;
    margin-bottom:8px;
    background:linear-gradient(
        100deg,
        #00C8FF,
        #B026FF,
        #FF6680,
        #00FF9C,
        #00C8FF
    );
    background-size:300% auto;
    -webkit-background-clip:text;
    background-clip:text;
    -webkit-text-fill-color:transparent;
    animation:cyberTitleShine 4s linear infinite;
    letter-spacing:.8px;
}

@keyframes cyberTitleShine{
    to{background-position:300% center}
}

.key-modal-sub{
    color:rgba(233,239,255,.7);
    font-size:.88rem;
    margin-bottom:22px;
}

/* DAYS BADGE */
.key-days-badge{
    display:inline-block;
    margin-bottom:16px;
    padding:8px 20px;
    border-radius:999px;
    background:rgba(0,255,156,.09);
    color:#00FF9C;
    font-size:.75rem;
    font-weight:800;
    letter-spacing:1.5px;
    border:1px solid rgba(0,255,156,.45);
    box-shadow:0 0 16px rgba(0,255,156,.12);
    animation:cyberBadgePulse 2.5s ease-in-out infinite;
}

.key-days-badge.permanent{
    background:rgba(0,200,255,.10);
    color:#00C8FF;
    border-color:rgba(0,200,255,.5);
    box-shadow:0 0 16px rgba(0,200,255,.15);
}

@keyframes cyberBadgePulse{
    0%,100%{box-shadow:0 0 8px rgba(0,255,156,.08)}
    50%{box-shadow:0 0 22px rgba(0,255,156,.3)}
}

/* KEY DISPLAY */
.animated-key{
    position:relative;
    display:block;
    width:100%;
    background:linear-gradient(
        135deg,
        rgba(0,200,255,.12),
        rgba(176,38,255,.15),
        rgba(255,49,85,.08)
    );
    border:1px solid rgba(0,200,255,.65);
    border-radius:16px;
    padding:22px;
    margin:0 0 14px;
    font-family:'JetBrains Mono','Courier New',monospace;
    font-size:1.05rem;
    color:#8CEBFF;
    font-weight:700;
    letter-spacing:1.6px;
    cursor:pointer;
    overflow:hidden;
    word-break:break-all;
    line-height:1.45;
    transition:transform .3s,box-shadow .3s,border-color .3s;
    box-shadow:
        0 0 18px rgba(0,200,255,.18),
        inset 0 0 22px rgba(176,38,255,.08);
    user-select:none;
}

.animated-key:hover{
    transform:translateY(-4px) scale(1.015);
    border-color:#00C8FF;
    box-shadow:
        0 0 28px rgba(0,200,255,.45),
        0 0 45px rgba(176,38,255,.20),
        inset 0 0 25px rgba(0,200,255,.12);
}

.animated-key:active{
    transform:scale(.98);
}

/* MOVING LIGHT SCAN */
.animated-key::before{
    content:"";
    position:absolute;
    top:0;
    left:-120%;
    width:65%;
    height:100%;
    pointer-events:none;
    background:linear-gradient(
        90deg,
        transparent,
        rgba(255,255,255,.32),
        rgba(0,200,255,.25),
        transparent
    );
    transform:skewX(-22deg);
    animation:cyberKeyScan 3s ease-in-out infinite;
}

@keyframes cyberKeyScan{
    0%,15%{left:-120%}
    65%,100%{left:160%}
}

/* COPIED STATE */
.animated-key.copied{
    background:linear-gradient(
        135deg,
        rgba(0,255,156,.22),
        rgba(0,180,110,.12)
    );
    border-color:#00FF9C;
    color:#00FF9C;
    box-shadow:
        0 0 25px rgba(0,255,156,.45),
        inset 0 0 25px rgba(0,255,156,.12);
}

/* COPY HINT */
.key-copy-hint{
    font-size:.8rem;
    color:rgba(233,239,255,.6);
    margin-bottom:22px;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:8px;
}

.key-copy-hint i{
    color:#00C8FF;
    animation:cyberHint 1.8s ease-in-out infinite;
}

@keyframes cyberHint{
    0%,100%{transform:translateY(0);opacity:.7}
    50%{transform:translateY(-4px);opacity:1}
}

/* ACTION BUTTONS */
.key-modal-actions{
    display:flex;
    gap:10px;
    justify-content:center;
    flex-wrap:wrap;
}

.key-modal-btn{
    padding:12px 24px;
    border:none;
    border-radius:12px;
    font-family:inherit;
    font-weight:700;
    font-size:.9rem;
    cursor:pointer;
    transition:all .25s ease;
    display:inline-flex;
    align-items:center;
    gap:8px;
}

.key-modal-btn:hover{
    transform:translateY(-3px);
    filter:brightness(1.2);
}

.key-modal-btn-primary{
    background:linear-gradient(120deg,#00C8FF,#087DFF,#B026FF);
    color:#fff;
    box-shadow:0 5px 20px rgba(0,200,255,.25);
}

.key-modal-btn-secondary{
    background:rgba(255,255,255,.06);
    color:#E9E9F8;
    border:1px solid rgba(0,200,255,.3);
}

/* FLOATING PARTICLES */
.key-sparkles{
    position:absolute;
    inset:0;
    pointer-events:none;
    overflow:hidden;
    border-radius:24px;
    z-index:1;
}

.key-sparkle{
    position:absolute;
    width:5px;
    height:5px;
    background:#00C8FF;
    border-radius:50%;
    box-shadow:0 0 12px #00C8FF,0 0 25px rgba(0,200,255,.7);
    animation:cyberParticle 3s ease-out infinite;
}

.key-sparkle.purple{
    background:#B026FF;
    box-shadow:0 0 12px #B026FF,0 0 25px rgba(176,38,255,.7);
}

.key-sparkle.blue{
    background:#00FF9C;
    box-shadow:0 0 12px #00FF9C,0 0 25px rgba(0,255,156,.7);
}

@keyframes cyberParticle{
    0%{
        transform:translate(0,20px) scale(0);
        opacity:0;
    }
    25%{opacity:1}
    100%{
        transform:translate(var(--tx,60px),var(--ty,-100px)) scale(1.8);
        opacity:0;
    }
}

/* MOBILE RESPONSIVE */
@media(max-width:500px){
    .key-modal-box{
        padding:32px 20px 26px;
        border-radius:20px;
    }

    .key-modal-icon{font-size:3.2rem}
    .key-modal-title{font-size:1.3rem}

    .animated-key{
        font-size:.9rem;
        padding:18px 14px;
        letter-spacing:1.2px;
    }

    .key-modal-btn{
        padding:10px 18px;
        font-size:.85rem;
    }
}

/* ACCESSIBILITY */
@media(prefers-reduced-motion:reduce){
    .key-modal-overlay,
    .key-modal-box,
    .key-modal-box::before,
    .key-modal-box::after,
    .key-modal-icon,
    .key-modal-title,
    .key-days-badge,
    .animated-key::before,
    .key-copy-hint i,
    .key-sparkle{
        animation:none!important;
    }
}

/* ==========================================================
   MAHIR RGB NEON — COLOR + ANIMATION UPGRADE
   Color: Black + RGB Neon
   Animation: Ultra Neon
   Existing Classes & Functionality: Preserved
========================================================== */

:root{
    --gold:#FFD700;
    --gold2:#FFF0A6;
    --purple:#B026FF;
    --blue:#00C8FF;
    --red:#FF3155;
    --red2:#FF6680;
    --green:#00FF9C;
    --bg:#050509;
    --card:rgba(12,12,25,.92);
    --line:rgba(0,200,255,.20);
    --text:#F4F5FF;
    --muted:rgba(230,235,255,.58);
}

/* RGB BACKGROUND */
body::before{
    background:
        radial-gradient(900px 600px at 5% 0%,rgba(0,200,255,.13),transparent 65%),
        radial-gradient(900px 600px at 100% 100%,rgba(176,38,255,.14),transparent 65%),
        radial-gradient(700px 500px at 50% 50%,rgba(255,0,85,.045),transparent 70%),
        #050509;
    animation:rgbBackground 12s ease-in-out infinite alternate;
}

@keyframes rgbBackground{
    0%{filter:hue-rotate(0deg)}
    100%{filter:hue-rotate(45deg)}
}

/* RGB CARD GLOW */
.card,.auth-card,.group-card,.keys-table-wrap{
    border-color:rgba(0,200,255,.22);
    box-shadow:
        0 10px 35px rgba(0,0,0,.45),
        0 0 18px rgba(0,200,255,.06);
    transition:border-color .3s,box-shadow .3s,transform .3s;
}

.card:hover,.group-card:hover{
    border-color:rgba(176,38,255,.55);
    box-shadow:
        0 12px 35px rgba(0,0,0,.5),
        0 0 22px rgba(0,200,255,.15),
        0 0 35px rgba(176,38,255,.12);
}

/* RGB HEADINGS */
.header h1,.auth-title{
    background:linear-gradient(
        100deg,
        #00C8FF,
        #B026FF,
        #FF3155,
        #00FF9C,
        #00C8FF
    );
    background-size:300% auto;
    -webkit-background-clip:text;
    background-clip:text;
    color:transparent;
    animation:rgbText 6s linear infinite;
}

@keyframes rgbText{
    to{background-position:300% center}
}

/* BUTTON NEON EFFECT */
.btn,.modal-btn,.key-modal-btn,.notice-btn{
    transition:all .25s ease;
}

.btn:hover:not(:disabled),
.modal-btn:hover,
.key-modal-btn:hover,
.notice-btn:hover{
    transform:translateY(-3px);
    filter:brightness(1.2);
    box-shadow:
        0 0 12px rgba(0,200,255,.25),
        0 0 25px rgba(176,38,255,.18);
}

/* RGB INPUT FOCUS */
input:focus,textarea:focus,select:focus{
    outline:none;
    border-color:#00C8FF;
    box-shadow:
        0 0 0 2px rgba(0,200,255,.12),
        0 0 18px rgba(0,200,255,.18);
}

/* RGB CARD TITLE */
.card-title,.modal-title,.group-name{
    color:#00C8FF;
    text-shadow:0 0 12px rgba(0,200,255,.25);
}

/* RGB BADGES */
.badge-running,.live-online{
    color:#00FF9C;
    border-color:rgba(0,255,156,.45);
    box-shadow:0 0 12px rgba(0,255,156,.10);
}

.badge-admin,.badge-agent{
    color:#D5A0FF;
    border-color:rgba(176,38,255,.45);
}

.badge-active,.badge-used{
    color:#65DFFF;
    border-color:rgba(0,200,255,.45);
}

/* RGB TABLE */
th{
    color:#00C8FF;
}

tr:hover td{
    background:rgba(0,200,255,.045);
}

/* RGB PROGRESS */
.progress-fill{
    background:linear-gradient(
        90deg,
        #00C8FF,
        #B026FF,
        #FF3155,
        #00FF9C
    );
    background-size:250% 100%;
    animation:rgbProgress 4s linear infinite;
}

@keyframes rgbProgress{
    to{background-position:250% 0}
}

/* RGB SPINNER */
.spinner{
    border-color:rgba(0,200,255,.2);
    border-top-color:#00C8FF;
    border-right-color:#B026FF;
}

/* RGB KEY MODAL */
.key-modal-box{
    border-color:rgba(0,200,255,.65);
    box-shadow:
        0 0 35px rgba(0,200,255,.25),
        0 0 75px rgba(176,38,255,.22),
        0 0 120px rgba(255,49,85,.12);
}

.key-modal-box::before{
    background:radial-gradient(
        circle,
        rgba(0,200,255,.3),
        rgba(176,38,255,.18) 40%,
        transparent 70%
    );
}

.key-modal-icon{
    color:#00C8FF;
    filter:drop-shadow(0 0 22px rgba(0,200,255,.9));
}

.animated-key{
    border-color:rgba(0,200,255,.7);
    color:#75E8FF;
    background:linear-gradient(
        135deg,
        rgba(0,200,255,.12),
        rgba(176,38,255,.15),
        rgba(255,49,85,.08)
    );
    box-shadow:
        0 0 20px rgba(0,200,255,.22),
        inset 0 0 20px rgba(176,38,255,.08);
}

.animated-key:hover{
    border-color:#00C8FF;
    box-shadow:
        0 0 30px rgba(0,200,255,.55),
        0 0 55px rgba(176,38,255,.25);
}

/* RGB SPARKLES */
.key-sparkle{
    background:#00C8FF;
    box-shadow:0 0 12px #00C8FF,0 0 25px rgba(0,200,255,.7);
}

.key-sparkle.purple{
    background:#B026FF;
    box-shadow:0 0 12px #B026FF,0 0 25px rgba(176,38,255,.7);
}

.key-sparkle.blue{
    background:#00FF9C;
    box-shadow:0 0 12px #00FF9C,0 0 25px rgba(0,255,156,.7);
}

/* SMOOTH ENTRY */
.anim-card{
    animation:fadeInUp .55s cubic-bezier(.2,.8,.2,1) both;
}

/* RGB NOTICE */
.notice-indicator{
    background:linear-gradient(120deg,#00C8FF,#B026FF,#FF3155);
    background-size:250% 250%;
    animation:pulseB 2s infinite,rgbNotice 5s ease infinite;
}

@keyframes rgbNotice{
    0%,100%{background-position:0% 50%}
    50%{background-position:100% 50%}
}

/* REDUCED MOTION ACCESSIBILITY */
@media(prefers-reduced-motion:reduce){
    *,*::before,*::after{
        animation-duration:.01ms!important;
        animation-iteration-count:1!important;
        scroll-behavior:auto!important;
    }
}
'''

SIDEBAR_JS = '''
<script>
function toggleMenu(){document.getElementById('menuDropdown').classList.toggle('active');}
document.addEventListener('click',function(e){var m=document.querySelector('.hamburger-menu');if(m&&!m.contains(e.target)){var d=document.getElementById('menuDropdown');if(d)d.classList.remove('active');}});
/* Live-refresh social links + APK from /api/sidebar_links so owner changes appear without full page reload */
(function(){
  function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
  function applySidebarData(data){
    if(!data) return;
    var dd = document.getElementById('menuDropdown');
    if(!dd) return;
    if(data.apk_url){
      var apk = dd.querySelector('.sidebar-download');
      if(apk) apk.setAttribute('href', data.apk_url);
    }
    if(!Array.isArray(data.links)) return;
    /* Remove everything after Roles block (custom sections) */
    var titles = dd.querySelectorAll('.menu-title');
    var rolesTitle = null;
    for(var i=0;i<titles.length;i++){
      if((titles[i].textContent||'').trim().toLowerCase()==='roles'){ rolesTitle=titles[i]; break; }
    }
    if(!rolesTitle) return;
    /* Find end of roles items: after roles title, skip menu-items until divider or end */
    var node = rolesTitle.nextSibling;
    while(node){
      var next = node.nextSibling;
      if(node.nodeType===1){
        var cls = node.classList;
        if(cls && cls.contains('menu-title') && (node.textContent||'').trim().toLowerCase()==='roles'){ node=next; continue; }
        /* Keep Role login links that are direct menu-items after Roles until first divider after both role links */
        if(cls && cls.contains('menu-item')){
          var t=(node.textContent||'').toLowerCase();
          if(t.indexOf('owner login')>=0 || t.indexOf('agent login')>=0){ node=next; continue; }
        }
        /* Remove remaining dividers, titles, links (custom area) */
        if(cls && (cls.contains('menu-divider') || cls.contains('menu-title') || cls.contains('menu-item'))){
          node.remove();
        }
      }
      node = next;
    }
    /* Group by section preserving order */
    var order=[], groups={};
    data.links.forEach(function(L){
      var sec=(L.section||'Social').trim()||'Social';
      if(!groups[sec]){ groups[sec]=[]; order.push(sec); }
      groups[sec].push(L);
    });
    order.forEach(function(sec){
      var div=document.createElement('div'); div.className='menu-divider'; dd.appendChild(div);
      var tit=document.createElement('div'); tit.className='menu-title'; tit.textContent=sec; dd.appendChild(tit);
      groups[sec].forEach(function(L){
        var a=document.createElement('a');
        a.href=L.url||'#'; a.target='_blank'; a.className='menu-item';
        var icon=L.icon||'fas fa-link';
        var style=(icon.toLowerCase().indexOf('whatsapp')>=0)?' style="color:#25D366;"':'';
        a.innerHTML='<i class="'+esc(icon)+'"'+style+'></i> '+esc(L.name||'Link');
        dd.appendChild(a);
      });
    });
  }
  try{
    fetch('/api/sidebar_links').then(function(r){return r.json();}).then(applySidebarData).catch(function(){});
  }catch(e){}
})();
</script>
'''

# Browser voice helper — used across panels
VOICE_HELPER_JS = '''
<script>
window.mahirSpeak = function(text, lang){
  try{
    if(!window.speechSynthesis || !text) return;
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(String(text));
    u.lang = lang || 'bn-BD';
    u.rate = 0.95;
    u.pitch = 1;
    try{
      var voices = window.speechSynthesis.getVoices() || [];
      var bn = voices.find(function(v){ return (v.lang||'').toLowerCase().indexOf('bn')===0; });
      if(bn) u.voice = bn;
    }catch(e){}
    window.speechSynthesis.speak(u);
  }catch(e){}
};
try{ if(window.speechSynthesis){ window.speechSynthesis.getVoices(); window.speechSynthesis.onvoiceschanged=function(){window.speechSynthesis.getVoices();}; } }catch(e){}

/* Auto voice for file uploads + flash messages */
(function(){
  function msgForUploadForm(form){
    try{
      var action = (form.getAttribute('action')||'').toLowerCase();
      var id = (form.id||'').toLowerCase();
      if(action.indexOf('upload_photo')>=0 || id.indexOf('photo')>=0) return 'ছবি আপলোড শুরু হয়েছে';
      if(action.indexOf('upload_mahir')>=0 || id.indexOf('mahir')>=0) return 'মাহির ফাইল আপলোড শুরু হয়েছে';
      if(action.indexOf('upload_users_db')>=0 || action.indexOf('upload')>=0 && id.indexOf('db')>=0) return 'ডাটাবেস আপলোড শুরু হয়েছে';
      if(action.indexOf('recreate')>=0) return 'বট ফাইল রিক্রিয়েট শুরু হয়েছে';
      if(action.indexOf('upload_file')>=0 || id.indexOf('upload')>=0) return 'ফাইল আপলোড শুরু হয়েছে';
      if((form.getAttribute('enctype')||'').toLowerCase().indexOf('multipart')>=0) return 'ফাইল আপলোড শুরু হয়েছে';
    }catch(e){}
    return 'ফাইল আপলোড শুরু হয়েছে';
  }
  function bindUploadForms(){
    try{
      var forms = document.querySelectorAll('form');
      for(var i=0;i<forms.length;i++){
        (function(form){
          var enc = (form.getAttribute('enctype')||'').toLowerCase();
          var act = (form.getAttribute('action')||'').toLowerCase();
          var isUpload = enc.indexOf('multipart')>=0 || act.indexOf('upload')>=0 || act.indexOf('recreate')>=0;
          if(!isUpload) return;
          if(form.__mahirVoiceBound) return;
          form.__mahirVoiceBound = true;
          form.addEventListener('submit', function(){
            if(window.mahirSpeak) window.mahirSpeak(msgForUploadForm(form));
          });
        })(forms[i]);
      }
    }catch(e){}
  }
  function speakFlashMessages(){
    try{
      var alerts = document.querySelectorAll('.alert');
      if(!alerts || !alerts.length) return;
      var texts = [];
      for(var i=0;i<alerts.length;i++){
        var t = (alerts[i].textContent||'').replace(/\\s+/g,' ').trim();
        if(!t) continue;
        var low = t.toLowerCase();
        var isErr = (alerts[i].className||'').indexOf('error')>=0 || low.indexOf('❌')>=0 || low.indexOf('failed')>=0 || low.indexOf('error')>=0;
        if(low.indexOf('upload')>=0 || low.indexOf('photo')>=0 || low.indexOf('db ')>=0 || low.indexOf('mahir')>=0 || low.indexOf('file')>=0 || low.indexOf('recreate')>=0 || low.indexOf('আপলোড')>=0){
          if(isErr) texts.push('আপলোড ব্যর্থ হয়েছে');
          else texts.push('ফাইল আপলোড সফল হয়েছে');
        } else if(low.indexOf('key')>=0 && (low.indexOf('generat')>=0 || low.indexOf('created')>=0 || low.indexOf('নতুন')>=0)){
          texts.push('নতুন কী তৈরি হয়েছে');
        } else if(isErr){
          texts.push('সমস্যা হয়েছে');
        } else if((alerts[i].className||'').indexOf('success')>=0){
          texts.push('সফল হয়েছে');
        }
      }
      if(texts.length && window.mahirSpeak){
        // Speak first relevant message only
        setTimeout(function(){ window.mahirSpeak(texts[0]); }, 450);
      }
    }catch(e){}
  }
  function init(){
    bindUploadForms();
    speakFlashMessages();
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
</script>
'''


# ============================================================
#  LOGIN PAGES
# ============================================================
LOGIN_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Welcome Back - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
''' + SIDEBAR_MENU + '''
<div class="auth-wrap"><div class="card auth-card"><div class="logo-wrap"><img src="{{ logo_url }}" alt="MAHIR"/></div><div class="auth-title">Welcome Back</div><div class="auth-sub">Sign in to your account</div>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST" id="loginForm">
  <div class="field"><i class="fas fa-user"></i><input type="text" name="username" placeholder="Username" required/></div>
  <div class="field"><i class="fas fa-lock"></i><input type="password" name="password" placeholder="Password" required/></div>
  <button type="submit" class="btn btn-gold btn-block" id="loginBtn"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<script>document.getElementById('loginForm').addEventListener('submit',function(){var b=document.getElementById('loginBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Authenticating...';});</script>
<div class="auth-links"><a href="/register"><i class="fas fa-user-plus"></i> Don't have an account? Register</a><a href="/recover"><i class="fas fa-key"></i> Forgot Password?</a></div></div></div>
''' + SIDEBAR_JS + '''</body></html>'''

REGISTER_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Create Account - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
''' + SIDEBAR_MENU + '''
<div class="auth-wrap"><div class="card auth-card"><div class="logo-wrap"><img src="{{ logo_url }}" alt="MAHIR"/></div><div class="auth-title">Create Account</div><div class="auth-sub">Join the MAHIR network</div>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST" id="registerForm">
  <div class="field"><i class="fas fa-user"></i><input type="text" name="username" placeholder="Username" required/></div>
  <div class="field"><i class="fas fa-lock"></i><input type="password" name="password" placeholder="Password" required/></div>
  <div class="field"><i class="fas fa-envelope"></i><input type="email" name="email" placeholder="Email (optional)"/></div>
  <div class="field"><i class="fas fa-key"></i><input type="text" name="registration_key" placeholder="Registration Key" required/></div>
  <button type="submit" class="btn btn-gold btn-block" id="registerBtn"><i class="fas fa-paper-plane"></i> Register</button>
</form>
<script>document.getElementById('registerForm').addEventListener('submit',function(){var b=document.getElementById('registerBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Processing...';});</script>
<div class="auth-links"><a href="/login"><i class="fas fa-arrow-left"></i> Already have an account? Login</a></div></div></div>
''' + SIDEBAR_JS + '''</body></html>'''

RECOVER_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Recover Password - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
''' + SIDEBAR_MENU + '''
<div class="auth-wrap"><div class="card auth-card"><div class="logo-wrap" style="display:flex;align-items:center;justify-content:center;"><i class="fas fa-key" style="font-size:2rem;color:var(--gold);"></i></div><div class="auth-title">Recover Password</div><div class="auth-sub">Reset your password</div>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST" id="recoverForm">
  <div class="field"><i class="fas fa-user"></i><input type="text" name="username" placeholder="Username" required/></div>
  <div class="field"><i class="fas fa-envelope"></i><input type="email" name="email" placeholder="Email Address" required/></div>
  <button type="submit" class="btn btn-gold btn-block" id="recoverBtn"><i class="fas fa-paper-plane"></i> Recover</button>
</form>
<script>document.getElementById('recoverForm').addEventListener('submit',function(){var b=document.getElementById('recoverBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Processing...';});</script>
<div class="auth-links"><a href="/login"><i class="fas fa-arrow-left"></i> Back to Login</a></div></div></div>
''' + SIDEBAR_JS + '''</body></html>'''

OWNER_LOGIN_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Owner Access - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
''' + SIDEBAR_MENU + '''
<div class="auth-wrap"><div class="card auth-card"><div class="logo-wrap"><img src="{{ logo_url }}" alt="MAHIR"/></div><div class="auth-title">👑 Owner Access</div><div class="auth-sub">Master control panel</div>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST" id="ownerLoginForm">
  <div class="field"><i class="fas fa-crown"></i><input type="text" name="username" placeholder="Owner Username" required/></div>
  <div class="field"><i class="fas fa-lock"></i><input type="password" name="password" placeholder="Password" required/></div>
  <button type="submit" class="btn btn-gold btn-block" id="loginBtn"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<script>document.getElementById('ownerLoginForm').addEventListener('submit',function(){var b=document.getElementById('loginBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Authenticating...';});</script>
<div class="auth-links"><a href="/login"><i class="fas fa-arrow-left"></i> Back to Main</a></div></div></div>
''' + SIDEBAR_JS + '''</body></html>'''

AGENT_LOGIN_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Agent Login - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
''' + SIDEBAR_MENU + '''
<div class="auth-wrap"><div class="card auth-card"><div class="logo-wrap"><img src="{{ logo_url }}" alt="MAHIR"/></div><div class="auth-title">Agent Login</div><div class="auth-sub">Agent panel access</div>
{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
<form method="POST" id="agentLoginForm">
  <div class="field"><i class="fas fa-user-tie"></i><input type="text" name="username" placeholder="Agent Username" required/></div>
  <div class="field"><i class="fas fa-lock"></i><input type="password" name="password" placeholder="Password" required/></div>
  <button type="submit" class="btn btn-gold btn-block" id="loginBtn"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<script>document.getElementById('agentLoginForm').addEventListener('submit',function(){var b=document.getElementById('loginBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Authenticating...';});</script>
<div class="auth-links"><a href="/login"><i class="fas fa-arrow-left"></i> Back to Main</a></div></div></div>
''' + SIDEBAR_JS + '''</body></html>'''


# ============================================================
#  AGENT DASHBOARD
# ============================================================
AGENT_DASHBOARD_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Agent Dashboard - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-user-tie"></i> Agent Dashboard</h1>
    <div class="flex">
      <a href="/agent/subscription" class="btn btn-gold btn-sm"><i class="fas fa-clock-rotate-left"></i> Subscription Management</a>
      <button type="button" class="btn btn-info btn-sm" onclick="openDbDownloadModal()"><i class="fas fa-database"></i> Download DB</button>
      <span class="welcome-text">Welcome, <strong>{{ session.username }}</strong></span>
      <a href="/agent/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-chart-simple"></i> Stats</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Keys Created</div><div class="stat-value">{{ key_count }}</div></div>
      <div class="stat-card"><div class="stat-label">My Customers</div><div class="stat-value">{{ my_users|length }}</div></div>
      <div class="stat-card"><div class="stat-label">Key Limit</div><div class="stat-value">{% if key_limit >= 0 %}{{ key_limit }}{% else %}∞{% endif %}</div></div>
      <div class="stat-card"><div class="stat-label">Server Bots</div><div class="stat-value">{% if max_running_bots >= 0 %}{{ running_bots_count }} / {{ max_running_bots }}{% else %}{{ running_bots_count }} / ∞{% endif %}</div></div>
    </div>
  </div>

  {% if bot_limit_full %}
  <div class="card" style="background:rgba(212,42,58,.12);border-color:rgba(212,42,58,.45);">
    <div style="display:flex;align-items:flex-start;gap:14px;color:var(--red2);">
      <i class="fas fa-exclamation-triangle" style="font-size:1.6rem;margin-top:2px;"></i>
      <div>
        <div style="font-weight:800;font-size:1.05rem;margin-bottom:6px;">বট লিমিট পূর্ণ হয়ে গিয়েছে</div>
        <div style="font-size:.9rem;line-height:1.55;color:#ffb4bc;">
          সার্ভারে একসাথে চলমান বটের লিমিট পূর্ণ ({{ running_bots_count }} / {{ max_running_bots }})।
          এখন নতুন বট চালু হবে না এবং <strong>নতুন Registration Key তৈরি করা যাবে না</strong>।
          Owner লিমিট বাড়ালে বা কোনো বট বন্ধ হলে আবার Key তৈরি করতে পারবেন।
        </div>
      </div>
    </div>
  </div>
  {% endif %}

  <div class="card">
    <div class="card-title"><i class="fas fa-key"></i> Generate Registration Key</div>
    {% if bot_limit_full %}
    <div style="padding:14px;background:rgba(212,42,58,.1);border-radius:12px;color:var(--red2);">
      <i class="fas fa-ban"></i> বট লিমিট পূর্ণ — নতুন Key তৈরি বন্ধ আছে ({{ running_bots_count }}/{{ max_running_bots }})।
    </div>
    {% elif key_limit >= 0 and key_count >= key_limit %}
    <div style="padding:14px;background:rgba(212,42,58,.1);border-radius:12px;color:var(--red2);"><i class="fas fa-exclamation-triangle"></i> Max {{ key_limit }} keys.</div>
    {% else %}
    <form method="POST" action="/agent/create_key" class="input-group">
      <label>Days (0=Permanent):</label>
      <input type="number" name="days_valid" value="30" min="0" style="width:110px;"/>
      <button type="submit" class="btn btn-gold"><i class="fas fa-plus-circle"></i> Generate</button>
    </form>
    {% endif %}
    {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-users"></i> My Customers ({{ my_users|length }})</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:12px;"><i class="fas fa-info-circle"></i> আপনার তৈরি key দিয়ে যারা register হয়েছে। Renew / Extend করতে পারবেন।</p>
    <div class="table-wrapper">
      <table>
        <thead><tr><th>ID</th><th>Username</th><th>Bot UID</th><th>Status</th><th>Days Left</th><th>Time Left</th><th>Expiry</th><th>Renewals</th><th style="text-align:right;">Actions</th></tr></thead>
        <tbody>
          {% for u in my_users %}
          <tr>
            <td>{{ u.id }}</td>
            <td><strong>{{ u.username }}</strong><br><small style="color:var(--muted);font-size:.7rem;">{{ u.email or '—' }}</small></td>
            <td>{{ u.bot_uid or '—' }}</td>
            <td>
              {% if u.sub_status == 'expired' %}<span class="badge badge-expired">Expired</span>
              {% elif u.sub_status == 'unlimited' %}<span class="badge badge-permanent">∞</span>
              {% else %}<span class="badge badge-active">Active</span>{% endif %}
            </td>
            <td>
              {% if u.sub_status == 'unlimited' %}
                <span class="days-badge permanent"><i class="fas fa-infinity"></i> Unlimited</span>
              {% elif u.sub_status == 'expired' %}
                <span class="days-badge danger"><i class="fas fa-times-circle"></i> 0 days</span>
              {% elif u.sub_days <= 3 %}
                <span class="days-badge danger"><i class="fas fa-exclamation-triangle"></i> {{ u.sub_days }} days</span>
              {% elif u.sub_days <= 7 %}
                <span class="days-badge warn"><i class="fas fa-clock"></i> {{ u.sub_days }} days</span>
              {% else %}
                <span class="days-badge"><i class="fas fa-check-circle"></i> {{ u.sub_days }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--gold2);">{{ u.sub_time_left }}</small></td>
            <td><small style="color:var(--muted);">{{ u.sub_expiry or '—' }}</small></td>
            <td>{% if u.renew_count > 0 %}<span class="days-badge"><i class="fas fa-redo"></i> {{ u.renew_count }}x (+{{ u.renew_days }}d)</span>{% else %}<small style="color:var(--muted);">—</small>{% endif %}</td>
            <td>
              <form method="POST" action="/agent/renew_subscription/{{ u.id }}" style="display:flex;gap:4px;justify-content:flex-end;">
                <input type="number" name="days" value="30" min="1" style="width:70px;padding:4px;font-size:.72rem;"/>
                <select name="mode" style="padding:4px;font-size:.72rem;border-radius:6px;background:#000;color:#fff;border:1px solid rgba(245,200,66,.2);">
                  <option value="extend">Extend</option>
                  <option value="reset">New</option>
                </select>
                <button type="submit" class="btn btn-gold btn-sm" style="padding:4px 8px;font-size:.65rem;"><i class="fas fa-sync"></i></button>
              </form>
              <div style="text-align:right;margin-top:4px;">
                <a href="/agent/customer_history/{{ u.id }}" class="btn btn-info btn-xs" style="font-size:.62rem;"><i class="fas fa-eye"></i> Details</a>
              </div>
            </td>
          </tr>
          {% else %}<tr class="empty-row"><td colspan="9">No customers yet.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-key" style="color:var(--purple);"></i> Recent Keys (Mine)</div>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>KEY</th>
            <th>CREATED</th>
            <th>USER DAYS LEFT</th>
            <th>USED BY</th>
            <th>STATUS</th>
            <th style="text-align:right;">ACTION</th>
          </tr>
        </thead>
        <tbody>
          {% for key in keys %}
          <tr>
            <td><span class="key-code">{{ key.key }}</span></td>
            <td style="color:var(--muted);font-size:.78rem;">{{ key.created_at[:16] if key.created_at else '—' }}</td>
            <td>
              {% if key.user_sub_status == 'unlimited' %}
                <span class="days-badge permanent"><i class="fas fa-infinity"></i> Unlimited</span>
              {% elif key.user_sub_status == 'expired' %}
                <span class="days-badge danger"><i class="fas fa-times-circle"></i> Expired</span>
              {% elif key.user_sub_days is not none and key.user_sub_days >= 0 %}
                {% if key.user_sub_days <= 3 %}
                  <span class="days-badge danger"><i class="fas fa-exclamation-triangle"></i> {{ key.user_sub_days }} days left</span>
                {% elif key.user_sub_days <= 7 %}
                  <span class="days-badge warn"><i class="fas fa-clock"></i> {{ key.user_sub_days }} days left</span>
                {% else %}
                  <span class="days-badge"><i class="fas fa-check-circle"></i> {{ key.user_sub_days }} days left</span>
                {% endif %}
              {% else %}
                <span style="color:var(--muted);font-size:.75rem;">— (unused)</span>
              {% endif %}
            </td>
            <td>{% if key.used_by %}<span class="used-by"><i class="fas fa-user user-icon"></i>{{ key.used_by }}</span>{% else %}<span style="color:var(--muted);">—</span>{% endif %}</td>
            <td>{% if key.is_used %}<span class="status-badge used"><i class="fas fa-check-circle"></i> USED</span>{% else %}<span class="status-badge available"><i class="fas fa-clock"></i> AVAILABLE</span>{% endif %}</td>
            <td style="text-align:right;">
              {% if key.used_user_id %}
                <a href="/agent/customer_history/{{ key.used_user_id }}" class="btn btn-info btn-xs" style="font-size:.7rem;"><i class="fas fa-eye"></i> Details</a>
              {% else %}
                <span style="color:var(--muted);font-size:.72rem;">—</span>
              {% endif %}
            </td>
          </tr>
          {% else %}<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:30px;">No keys yet. Generate one above.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/login" class="back-link"><i class="fas fa-arrow-left"></i> Back</a>
</div>

<div class="modal-overlay" id="dbDownloadModal">
  <div class="modal-box" style="max-width:420px;">
    <button class="modal-close" onclick="closeDbDownloadModal()">&times;</button>
    <div class="modal-title"><i class="fas fa-database" style="color:var(--gold);"></i> Database Download</div>
    <p style="color:var(--muted);font-size:.85rem;margin-bottom:14px;">
      <i class="fas fa-lock" style="color:var(--red2);"></i> DB download করতে password দিন।
    </p>
    <form method="POST" action="/agent/download_db" id="dbDownloadForm">
      <input type="password" name="db_password" placeholder="Enter DB Password" required style="width:100%;margin-bottom:12px;"/>
      <div style="text-align:right;display:flex;gap:8px;justify-content:flex-end;">
        <button type="button" onclick="closeDbDownloadModal()" class="btn btn-clear btn-sm">Cancel</button>
        <button type="submit" class="btn btn-gold btn-sm" id="dbDownloadBtn"><i class="fas fa-download"></i> Download</button>
      </div>
    </form>
  </div>
</div>

<!-- ═══════ ANIMATED NEW KEY MODAL ═══════ -->
<div class="key-modal-overlay" id="newKeyModal">
    <div class="key-modal-box">
        <div class="key-sparkles" id="keySparkles"></div>
        <button class="modal-close" onclick="closeKeyModal()"
                style="position:absolute;top:14px;right:18px;background:none;border:none;color:#FFE28A;font-size:1.8rem;cursor:pointer;z-index:10;line-height:1;padding:0;">&times;</button>
        <div class="key-modal-icon"><i class="fas fa-key"></i></div>
        <div class="key-modal-title">🎉 Key Generated!</div>
        <div class="key-modal-sub">নিচের key টি সংরক্ষণ করুন — এটি আর দেখানো হবে না!</div>
        <div id="newKeyDays" class="key-days-badge">30 Days Valid</div>
        <div class="animated-key" id="newKeyValue" onclick="copyNewKey(this)" data-key=""></div>
        <div class="key-copy-hint"><i class="fas fa-hand-pointer"></i> Click the key to copy</div>
        <div class="key-modal-actions">
            <button type="button" class="key-modal-btn key-modal-btn-primary"
                    onclick="copyNewKey(document.getElementById('newKeyValue'))">
                <i class="fas fa-copy"></i> Copy Key
            </button>
            <button type="button" class="key-modal-btn key-modal-btn-secondary" onclick="closeKeyModal()">
                <i class="fas fa-times"></i> Close
            </button>
        </div>
    </div>
</div>

<script>
function openDbDownloadModal(){document.getElementById('dbDownloadModal').classList.add('active');}
function closeDbDownloadModal(){document.getElementById('dbDownloadModal').classList.remove('active');}
document.getElementById('dbDownloadModal').addEventListener('click', function(e){if(e.target===this)closeDbDownloadModal();});
document.getElementById('dbDownloadForm').addEventListener('submit', function(){
  var b=document.getElementById('dbDownloadBtn'); b.disabled=true; b.innerHTML='<span class="spinner"></span> Downloading...';
});
</script>
''' + VOICE_HELPER_JS + '''
<script>
/* ═══════════ NEW KEY ANIMATED MODAL JS ═══════════ */
(function () {
    window.showKeyModal = function (key, durationText, isPermanent) {
        var modal = document.getElementById('newKeyModal');
        if (!modal) return;
        var keyEl = document.getElementById('newKeyValue');
        if (keyEl) { keyEl.textContent = key; keyEl.setAttribute('data-key', key); keyEl.classList.remove('copied'); }
        var daysEl = document.getElementById('newKeyDays');
        if (daysEl) { daysEl.textContent = durationText; daysEl.className = 'key-days-badge' + (isPermanent ? ' permanent' : ''); }
        var sc = document.getElementById('keySparkles');
        if (sc) {
            sc.innerHTML = '';
            for (var i = 0; i < 22; i++) {
                var s = document.createElement('div');
                s.className = 'key-sparkle' + (i % 3 === 1 ? ' purple' : i % 3 === 2 ? ' blue' : '');
                s.style.left = (Math.random() * 100) + '%';
                s.style.top = (Math.random() * 100) + '%';
                s.style.setProperty('--tx', (Math.random() * 140 - 70) + 'px');
                s.style.setProperty('--ty', (-Math.random() * 140 - 30) + 'px');
                s.style.animationDelay = (Math.random() * 1.8) + 's';
                sc.appendChild(s);
            }
        }
        modal.classList.add('show');
        var box = modal.querySelector('.key-modal-box');
        if (box) { box.style.animation = 'none'; void box.offsetWidth; box.style.animation = ''; }
        if (window.mahirSpeak) window.mahirSpeak('নতুন কী তৈরি হয়েছে');
    };
    window.closeKeyModal = function () {
        var modal = document.getElementById('newKeyModal');
        if (modal) modal.classList.remove('show');
    };
    window.copyNewKey = function (el) {
        if (!el) return;
        var key = el.getAttribute('data-key') || el.textContent;
        var original = el.textContent;
        function markCopied() {
            el.classList.add('copied');
            el.textContent = '✅ COPIED TO CLIPBOARD';
            if (window.mahirSpeak) window.mahirSpeak('কী কপি হয়েছে');
            setTimeout(function () { el.classList.remove('copied'); el.textContent = original; }, 1600);
        }
        function fallback() {
            var ta = document.createElement('textarea');
            ta.value = key; ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); markCopied(); } catch(e) { window.prompt('Copy this key manually:', key); }
            document.body.removeChild(ta);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(key).then(markCopied).catch(fallback);
        } else { fallback(); }
    };
    document.addEventListener('DOMContentLoaded', function () {
        var modal = document.getElementById('newKeyModal');
        if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) window.closeKeyModal(); });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') window.closeKeyModal(); });
})();
</script>
{% if new_key_data %}
<script>
document.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
        if (typeof window.showKeyModal === 'function') {
            window.showKeyModal(
                {{ new_key_data.key | tojson }},
                {{ new_key_data.duration_text | tojson }},
                {{ 'true' if new_key_data.is_permanent else 'false' }}
            );
        }
    }, 400);
});
</script>
{% endif %}
</body></html>'''


# ============================================================
#  AGENT SUBSCRIPTION MANAGEMENT PAGE
# ============================================================
AGENT_SUBSCRIPTION_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Subscription Management - Agent</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-clock-rotate-left"></i> Subscription Management</h1>
    <div class="flex">
      <a href="/agent/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <span class="welcome-text">Agent: <strong>{{ session.username }}</strong></span>
      <a href="/agent/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-chart-simple"></i> Subscription Overview</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Total Customers</div><div class="stat-value">{{ my_users|length }}</div></div>
      <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value" style="color:#4ade80;">{{ active_count }}</div></div>
      <div class="stat-card"><div class="stat-label">Expiring Soon (≤7d)</div><div class="stat-value" style="color:#F5C842;">{{ expiring_count }}</div></div>
      <div class="stat-card"><div class="stat-label">Expired</div><div class="stat-value" style="color:#ff5a76;">{{ expired_count }}</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-users"></i> All Customers — Extend Subscription</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:12px;"><i class="fas fa-info-circle"></i> আপনি যেকোনো customer-এর মেয়াদ extend বা reset করতে পারবেন। Extend = current expiry-র সাথে যোগ হবে, Reset = আজ থেকে নতুন করে শুরু হবে।</p>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>USERNAME</th>
            <th>STATUS</th>
            <th>DAYS LEFT</th>
            <th>TIME LEFT</th>
            <th>EXPIRY</th>
            <th>RENEWALS</th>
            <th style="text-align:right;">ACTIONS</th>
          </tr>
        </thead>
        <tbody>
          {% for u in my_users %}
          <tr>
            <td>
              <strong style="color:#FFE28A;">{{ u.username }}</strong>
              <br><small style="color:var(--muted);font-size:.7rem;">ID #{{ u.id }} · {{ u.email or '—' }}</small>
            </td>
            <td>
              {% if u.sub_status == 'expired' %}<span class="badge badge-expired">Expired</span>
              {% elif u.sub_status == 'unlimited' %}<span class="badge badge-permanent">∞ Unlimited</span>
              {% elif u.sub_days <= 3 %}<span class="badge badge-expired">Expiring</span>
              {% else %}<span class="badge badge-running">Active</span>{% endif %}
            </td>
            <td>
              {% if u.sub_status == 'unlimited' %}
                <span class="days-badge permanent"><i class="fas fa-infinity"></i> ∞</span>
              {% elif u.sub_status == 'expired' %}
                <span class="days-badge danger"><i class="fas fa-times-circle"></i> 0d</span>
              {% elif u.sub_days <= 3 %}
                <span class="days-badge danger"><i class="fas fa-exclamation-triangle"></i> {{ u.sub_days }}d</span>
              {% elif u.sub_days <= 7 %}
                <span class="days-badge warn"><i class="fas fa-clock"></i> {{ u.sub_days }}d</span>
              {% else %}
                <span class="days-badge"><i class="fas fa-check-circle"></i> {{ u.sub_days }}d</span>
              {% endif %}
            </td>
            <td><small style="color:var(--gold2);">{{ u.sub_time_left }}</small></td>
            <td><small style="color:var(--muted);">{{ u.sub_expiry or '—' }}</small></td>
            <td>
              {% if u.renew_count > 0 %}
                <span class="days-badge"><i class="fas fa-redo"></i> {{ u.renew_count }}x (+{{ u.renew_days }}d)</span>
              {% else %}
                <small style="color:var(--muted);">—</small>
              {% endif %}
            </td>
            <td>
              <form method="POST" action="/agent/renew_subscription/{{ u.id }}" style="display:flex;gap:4px;justify-content:flex-end;align-items:center;">
                <input type="number" name="days" value="30" min="1" style="width:70px;padding:6px;font-size:.75rem;"/>
                <select name="mode" style="padding:6px;font-size:.75rem;border-radius:8px;background:#000;color:#fff;border:1px solid rgba(245,200,66,.2);">
                  <option value="extend">Extend</option>
                  <option value="reset">Reset</option>
                </select>
                <button type="submit" class="btn btn-gold btn-sm" style="padding:5px 10px;font-size:.7rem;"><i class="fas fa-sync"></i> Apply</button>
              </form>
              <div style="text-align:right;margin-top:4px;">
                <a href="/agent/customer_history/{{ u.id }}" class="btn btn-info btn-xs" style="font-size:.65rem;"><i class="fas fa-eye"></i> View Details</a>
              </div>
            </td>
          </tr>
          {% else %}<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:30px;">No customers yet.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-list-alt" style="color:var(--purple);"></i> My Recent Renewal History (Latest 100)</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:12px;"><i class="fas fa-info-circle"></i> আপনার করা renewal-এর সব লগ।</p>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>USERNAME</th>
            <th>DAYS ADDED</th>
            <th>MODE</th>
            <th>OLD EXPIRY</th>
            <th>NEW EXPIRY</th>
            <th>WHEN</th>
          </tr>
        </thead>
        <tbody>
          {% for h in my_history %}
          <tr>
            <td><strong style="color:#FFE28A;">{{ h.username }}</strong></td>
            <td>
              {% if h.mode == 'reset' %}
                <span class="days-badge warn"><i class="fas fa-sync"></i> Reset +{{ h.days_added }}d</span>
              {% else %}
                <span class="days-badge permanent"><i class="fas fa-plus-circle"></i> +{{ h.days_added }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.mode }}</small></td>
            <td><small style="color:var(--muted);">{{ h.old_expiry[:16] if h.old_expiry else '—' }}</small></td>
            <td><small style="color:#7dd3fc;">{{ h.new_expiry[:16] if h.new_expiry else '—' }}</small></td>
            <td><small style="color:var(--muted);">{{ h.created_at[:16] if h.created_at else '—' }}</small></td>
          </tr>
          {% else %}<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:30px;">No renewal history yet.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/agent/dashboard" class="back-link"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
</div></body></html>'''


# ============================================================
#  AGENT CUSTOMER HISTORY / DETAILS PAGE (MASKED)
# ============================================================
AGENT_CUSTOMER_HISTORY_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Customer Details - Agent</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-user-circle"></i> {{ user.username }}</h1>
    <div class="flex">
      <a href="/agent/subscription" class="btn btn-gold btn-sm"><i class="fas fa-arrow-left"></i> Subscription</a>
      <a href="/agent/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-th-large"></i> Dashboard</a>
      <a href="/agent/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-id-card"></i> Account Information</div>
    <div style="text-align:center;margin-bottom:16px;">
      {% if user.bot_disabled_by_admin %}<span class="live-badge live-offline"><i class="fas fa-hand-paper"></i> OWNER DISABLED</span>
      {% elif user.sub_status == 'expired' %}<span class="live-badge live-offline"><i class="fas fa-clock"></i> EXPIRED</span>
      {% elif live and live.is_running %}<span class="live-badge live-online"><i class="fas fa-circle"></i> LIVE · RUNNING</span>
      {% else %}<span class="live-badge live-offline"><i class="fas fa-circle"></i> OFFLINE</span>{% endif %}
    </div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">User ID</div><div class="detail-value big">#{{ user.id }}</div></div>
      <div class="detail-item"><div class="detail-label">Username</div><div class="detail-value big">{{ user.username }}</div></div>
      <div class="detail-item">
        <div class="detail-label">Email</div>
        <div class="detail-value masked">{{ user.email_masked }}</div>
        <span class="mask-note"><i class="fas fa-lock"></i> Masked for privacy</span>
      </div>
      <div class="detail-item">
        <div class="detail-label">Account Password</div>
        <div class="detail-value masked">{{ user.password_masked }}</div>
        <span class="mask-note"><i class="fas fa-lock"></i> Masked for privacy</span>
      </div>
      <div class="detail-item"><div class="detail-label">Role</div><div class="detail-value">USER</div></div>
      <div class="detail-item"><div class="detail-label">Created</div><div class="detail-value">{{ user.created_at }}</div></div>
      <div class="detail-item">
        <div class="detail-label">Subscription</div>
        <div class="detail-value">
          {% if user.sub_status == 'unlimited' %}<span style="color:#4ade80;">∞ Unlimited</span>
          {% elif user.sub_status == 'expired' %}<span style="color:#ff5a76;">Expired</span>
          {% else %}<span style="color:#4ade80;">{{ user.sub_days }} days left</span>{% endif %}
          <br><small style="color:var(--muted);">Time: {{ user.sub_time_left }}</small>
          {% if user.sub_expiry %}<br><small style="color:var(--muted);">Expires: {{ user.sub_expiry }}</small>{% endif %}
        </div>
      </div>
      <div class="detail-item"><div class="detail-label">Renew Count</div><div class="detail-value big">{{ user.renew_count }}x <small style="color:#4ade80;">(+{{ user.renew_days }}d)</small></div></div>
      <div class="detail-item"><div class="detail-label">Registration Key</div><div class="detail-value">{{ user.registration_key }}</div></div>
      <div class="detail-item"><div class="detail-label">Created By</div><div class="detail-value">{% if not user.created_by_agent or user.created_by_agent in ['Owner','OWNER','admin','system','MAHIR TCP'] %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER MAHIR</span>{% else %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT {{ user.created_by_agent }}</span>{% endif %}</div></div>
    </div>
  </div>

  {% if user.bot_uid != '—' %}
  <div class="card">
    <div class="card-title"><i class="fas fa-robot"></i> Bot Information</div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">Bot UID</div><div class="detail-value big">{{ user.bot_uid }}</div></div>
      <div class="detail-item">
        <div class="detail-label">Bot Password</div>
        <div class="detail-value masked">{{ user.bot_pw_masked }}</div>
        <span class="mask-note"><i class="fas fa-lock"></i> Masked for privacy</span>
      </div>
      <div class="detail-item"><div class="detail-label">Bot File</div><div class="detail-value">{{ user.bot_file }}</div></div>
      <div class="detail-item"><div class="detail-label">Owner UIDs</div><div class="detail-value">{{ user.admin_uid }}</div></div>
      <div class="detail-item"><div class="detail-label">Bot Status</div><div class="detail-value">{{ user.bot_status }}</div></div>
      <div class="detail-item"><div class="detail-label">Force Active</div><div class="detail-value">{% if user.bot_force_active %}<span style="color:#4ade80;">YES</span>{% else %}<span style="color:var(--muted);">NO</span>{% endif %}</div></div>
    </div>
  </div>
  {% endif %}

  {% if live %}
  <div class="card">
    <div class="card-title"><i class="fas fa-satellite-dish"></i> Live Bot Status</div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">Live Bot Name</div><div class="detail-value big">{{ live.bot_name }}</div></div>
      <div class="detail-item"><div class="detail-label">Region</div><div class="detail-value">{{ live.bot_region }}</div></div>
      <div class="detail-item"><div class="detail-label">Uptime</div><div class="detail-value">{{ live.uptime }}</div></div>
      <div class="detail-item"><div class="detail-label">CPU</div><div class="detail-value">{{ live.cpu }}%</div></div>
      <div class="detail-item"><div class="detail-label">RAM</div><div class="detail-value">{{ live.ram }}%</div></div>
      <div class="detail-item"><div class="detail-label">Last Message</div><div class="detail-value">{{ live.last_message }}</div></div>
    </div>
  </div>
  {% endif %}

  <div class="card">
    <div class="card-title"><i class="fas fa-sync"></i> Quick Renew / Extend</div>
    <form method="POST" action="/agent/renew_subscription/{{ user.id }}" class="flex">
      <label style="color:var(--gold2);font-weight:600;">Mode:</label>
      <select name="mode">
        <option value="extend">Extend from current</option>
        <option value="reset">New package (reset)</option>
      </select>
      <label style="color:var(--gold2);font-weight:600;">Days:</label>
      <input type="number" name="days" value="30" min="1" style="width:120px;"/>
      <button type="submit" class="btn btn-gold"><i class="fas fa-save"></i> Apply</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-history" style="color:var(--purple);"></i> Renewal History ({{ sub_history|length }})</div>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>#</th>
            <th>DAYS ADDED</th>
            <th>MODE</th>
            <th>OLD EXPIRY</th>
            <th>NEW EXPIRY</th>
            <th>EXTENDED BY</th>
            <th>ROLE</th>
            <th>WHEN</th>
          </tr>
        </thead>
        <tbody>
          {% for h in sub_history %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>
              {% if h.mode == 'reset' %}
                <span class="days-badge warn"><i class="fas fa-sync"></i> Reset +{{ h.days_added }}d</span>
              {% else %}
                <span class="days-badge permanent"><i class="fas fa-plus-circle"></i> +{{ h.days_added }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.mode }}</small></td>
            <td><small style="color:var(--muted);">{{ h.old_expiry[:16] if h.old_expiry else '—' }}</small></td>
            <td><small style="color:#7dd3fc;">{{ h.new_expiry[:16] if h.new_expiry else '—' }}</small></td>
            <td><strong style="color:#FFE28A;">{{ h.extended_by or '—' }}</strong></td>
            <td>
              {% if h.extended_by_role == 'owner' %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER</span>
              {% elif h.extended_by_role == 'agent' %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT</span>
              {% else %}<small style="color:var(--muted);">—</small>{% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.created_at[:16] if h.created_at else '—' }}</small></td>
          </tr>
          {% else %}<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:30px;">No renewal history yet.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/agent/subscription" class="back-link"><i class="fas fa-arrow-left"></i> Back to Subscription</a>
</div></body></html>'''


# ============================================================
#  AUTO BIO MANAGER HTML
# ============================================================
OWNER_BIO_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Auto Bio - MAHIR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-pen"></i> Auto Bio Settings</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-clear btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/links" class="btn btn-success btn-sm"><i class="fas fa-link"></i> Links &amp; App</a>
      <a href="/owner/modules" class="btn btn-primary btn-sm"><i class="fas fa-puzzle-piece"></i> Modules</a>
      <a href="/owner/photos" class="btn btn-info btn-sm"><i class="fas fa-images"></i> Photos</a>
    </div>
  </div>
  {% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for cat, msg in messages %}
  <div class="alert {{ cat }}"><i class="fas fa-{{ 'check-circle' if cat=='success' else 'exclamation-circle' }}"></i> {{ msg }}</div>
  {% endfor %}{% endif %}{% endwith %}

  <div class="card anim-card">
    <div class="card-title"><i class="fas fa-pen"></i> Default Auto Bio</div>
    <form method="POST" action="/owner/set_auto_bio">
      <label style="color:var(--gold2);font-weight:600;">Bio text used when creating / updating bots</label>
      <textarea name="auto_bio" rows="4" style="width:100%;margin:8px 0;padding:12px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);font-family:var(--mono);">{{ auto_bio_text }}</textarea>
      <button type="submit" class="btn btn-gold"><i class="fas fa-save"></i> Save Bio</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-bolt"></i> Bulk Change All Bots Bio</div>
    <p style="color:var(--muted);font-size:.85rem;margin-bottom:12px;">Runs in background. Leave empty to apply the Default Auto Bio above.</p>
    <form method="POST" action="/owner/bulk_change_bio" onsubmit="return confirm('All bots bio change will start in background. Continue?');">
      <input type="text" name="bulk_bio" placeholder="Optional custom bio for all bots" style="width:100%;margin:8px 0;padding:12px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);"/>
      <button type="submit" class="btn btn-danger"><i class="fas fa-bolt"></i> 1-Click Change ALL Bots Bio</button>
    </form>
  </div>
</div>
</body></html>'''


# ============================================================
#  LINKS & APP SETTINGS HTML
# ============================================================
OWNER_LINKS_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Links &amp; App - MAHIR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>''' + COMMON_CSS + '''
#linksTbody tr.link-row{cursor:grab;transition:background .15s,opacity .15s,box-shadow .15s}
#linksTbody tr.link-row:active{cursor:grabbing}
#linksTbody tr.link-row.dragging{opacity:.45;background:rgba(245,200,66,.08)}
#linksTbody tr.link-row.drag-over{box-shadow:inset 0 3px 0 0 var(--gold)}
.drag-handle{cursor:grab;color:var(--muted);padding:6px 10px;font-size:1.1rem;user-select:none;-webkit-user-select:none;touch-action:none}
.drag-handle:hover{color:var(--gold)}
.drag-handle:active{cursor:grabbing}
</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-link"></i> Links &amp; App Settings</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-clear btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/bio" class="btn btn-warning btn-sm"><i class="fas fa-pen"></i> Auto Bio</a>
      <a href="/owner/modules" class="btn btn-primary btn-sm"><i class="fas fa-puzzle-piece"></i> Modules</a>
      <a href="/owner/photos" class="btn btn-info btn-sm"><i class="fas fa-images"></i> Photos</a>
    </div>
  </div>
  {% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for cat, msg in messages %}
  <div class="alert {{ cat }}"><i class="fas fa-{{ 'check-circle' if cat=='success' else 'exclamation-circle' }}"></i> {{ msg }}</div>
  {% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-download"></i> App Download Link &amp; Region</div>
    <form method="POST" action="/owner/set_links" style="margin-top:14px;">
      <label style="color:var(--gold2);font-weight:600;">App Download Link</label>
      <input type="text" name="app_download_link" value="{{ app_download_link }}" style="width:100%;margin:8px 0;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);"/>
      <label style="color:var(--gold2);font-weight:600;">Default FF Region</label>
      <input type="text" name="default_ff_region" value="{{ default_ff_region }}" style="width:100%;margin:8px 0;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);"/>
      <button type="submit" class="btn btn-gold btn-sm"><i class="fas fa-save"></i> Save App &amp; Region</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-share-alt"></i> Social Links &amp; Sidebar Links</div>
    <div class="table-wrapper">
      <table>
        <thead><tr><th style="width:90px;">Order</th><th>Icon</th><th>Name</th><th>Section</th><th>URL</th><th>Action</th></tr></thead>
        <tbody id="linksTbody">
          {% for link in custom_links %}
          <tr class="link-row" draggable="true" data-id="{{ link.id }}">
            <td style="white-space:nowrap;">
              <span class="drag-handle" title="Drag to reorder"><i class="fas fa-grip-vertical"></i></span>
              <form method="POST" action="/owner/move_link/{{ link.id }}/up" style="display:inline;"><button type="submit" class="btn btn-sm" style="padding:4px 8px;background:rgba(245,200,66,.15);color:var(--gold);border:1px solid rgba(245,200,66,.3);"><i class="fas fa-arrow-up"></i></button></form>
              <form method="POST" action="/owner/move_link/{{ link.id }}/down" style="display:inline;"><button type="submit" class="btn btn-sm" style="padding:4px 8px;background:rgba(59,140,255,.15);color:#7dd3fc;border:1px solid rgba(59,140,255,.3);"><i class="fas fa-arrow-down"></i></button></form>
            </td>
            <td><i class="{{ link.icon }}" style="font-size:1.2rem;color:var(--gold);"></i></td>
            <td><strong>{{ link.name }}</strong></td>
            <td>
              <form method="POST" action="/owner/update_link_section/{{ link.id }}" style="display:flex;gap:4px;align-items:center;">
                <input type="text" name="section" value="{{ link.section or 'Social' }}" style="width:110px;padding:6px 8px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.25);font-size:.78rem;"/>
                <button type="submit" class="btn btn-sm" style="padding:4px 8px;background:rgba(133,64,245,.2);color:#c4b5fd;border:1px solid rgba(133,64,245,.35);"><i class="fas fa-check"></i></button>
              </form>
            </td>
            <td><a href="{{ link.url }}" target="_blank" style="color:#7dd3fc;text-decoration:none;">{{ link.url[:36] }}{% if link.url|length > 36 %}...{% endif %}</a></td>
            <td>
              <form method="POST" action="/owner/delete_link/{{ link.id }}" onsubmit="return confirm('Delete this link?');" style="display:inline;">
                <button type="submit" class="btn btn-danger btn-sm" style="padding:4px 8px;"><i class="fas fa-trash"></i></button>
              </form>
            </td>
          </tr>
          {% else %}<tr><td colspan="6" style="text-align:center;color:var(--muted);">No links added yet.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
    <div id="dragSaveStatus" style="display:none;margin-top:8px;font-size:.82rem;color:var(--gold2);"></div>
    <form method="POST" action="/owner/add_link" class="flex" style="margin-top:16px;background:rgba(0,0,0,.3);padding:12px;border-radius:12px;flex-wrap:wrap;gap:8px;">
      <input type="text" name="name" placeholder="Name" required style="flex:1;min-width:120px;"/>
      <input type="text" name="url" placeholder="URL" required style="flex:2;min-width:180px;"/>
      <input type="text" name="section" list="section-suggestions" placeholder="Section" value="Social" style="flex:1;min-width:110px;"/>
      <datalist id="section-suggestions"><option value="Social"></option><option value="Community"></option><option value="Extra"></option><option value="Support"></option></datalist>
      <select name="icon" required style="flex:1;min-width:120px;">
        <option value="fab fa-telegram">Telegram</option>
        <option value="fab fa-tiktok">TikTok</option>
        <option value="fab fa-whatsapp">WhatsApp</option>
        <option value="fab fa-youtube">YouTube</option>
        <option value="fab fa-facebook">Facebook</option>
        <option value="fab fa-instagram">Instagram</option>
        <option value="fas fa-globe">Website</option>
        <option value="fas fa-link">Custom</option>
      </select>
      <button type="submit" class="btn btn-success btn-sm"><i class="fas fa-plus"></i> Add Link</button>
    </form>
  </div>
</div>
<script>
(function(){
  var tbody = document.getElementById('linksTbody');
  if(!tbody) return;
  var dragRow = null;
  var statusEl = document.getElementById('dragSaveStatus');
  function showStatus(msg, ok){
    if(!statusEl) return;
    statusEl.style.display = 'block';
    statusEl.style.color = ok ? '#4ade80' : '#FF5A6A';
    statusEl.textContent = msg;
    if(ok) setTimeout(function(){ statusEl.style.display='none'; }, 1800);
  }
  function saveOrder(){
    var ids = [];
    tbody.querySelectorAll('tr.link-row').forEach(function(r){var id=r.getAttribute('data-id');if(id)ids.push(parseInt(id,10));});
    if(!ids.length) return;
    showStatus('💾 Saving order...', true);
    fetch('/owner/reorder_links', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:ids})})
      .then(function(r){return r.json();})
      .then(function(d){ if(d&&d.status==='success') showStatus('✅ Order saved',true); else showStatus('❌ ' + ((d&&d.message)||'Save failed'),false); })
      .catch(function(){ showStatus('❌ Network error',false); });
  }
  tbody.querySelectorAll('tr.link-row').forEach(function(row){
    row.addEventListener('dragstart', function(e){
      if(e.target.closest('input,button,a,form,select')){ e.preventDefault(); return; }
      dragRow = row; row.classList.add('dragging');
      try { e.dataTransfer.effectAllowed='move'; e.dataTransfer.setData('text/plain', row.getAttribute('data-id')); } catch(_){}
    });
    row.addEventListener('dragend', function(){ row.classList.remove('dragging'); tbody.querySelectorAll('.drag-over').forEach(function(r){r.classList.remove('drag-over');}); dragRow=null; saveOrder(); });
    row.addEventListener('dragover', function(e){ e.preventDefault(); if(!dragRow||dragRow===row)return; row.classList.add('drag-over'); var rect=row.getBoundingClientRect(); var before=(e.clientY-rect.top)<rect.height/2; if(before)tbody.insertBefore(dragRow,row); else tbody.insertBefore(dragRow,row.nextSibling); });
    row.addEventListener('dragleave', function(){ row.classList.remove('drag-over'); });
    row.addEventListener('drop', function(e){ e.preventDefault(); row.classList.remove('drag-over'); });
  });
  var touchRow=null,touchY=0,moved=false;
  tbody.querySelectorAll('.drag-handle').forEach(function(handle){
    handle.addEventListener('touchstart', function(e){ touchRow=handle.closest('tr.link-row'); if(!touchRow)return; touchY=e.touches[0].clientY; moved=false; touchRow.classList.add('dragging'); }, {passive:true});
  });
  document.addEventListener('touchmove', function(e){ if(!touchRow)return; var y=e.touches[0].clientY; if(Math.abs(y-touchY)<6&&!moved)return; moved=true; e.preventDefault(); var el=document.elementFromPoint(e.touches[0].clientX,y); var over=el&&el.closest?el.closest('tr.link-row'):null; if(over&&over!==touchRow&&over.parentNode===tbody){ var rect=over.getBoundingClientRect(); if(y<rect.top+rect.height/2)tbody.insertBefore(touchRow,over); else tbody.insertBefore(touchRow,over.nextSibling); } }, {passive:false});
  document.addEventListener('touchend', function(){ if(!touchRow)return; touchRow.classList.remove('dragging'); if(moved)saveOrder(); touchRow=null;moved=false; });
})();
</script>
</body></html>'''


# ============================================================
#  PHOTO MANAGER HTML
# ============================================================
PHOTO_MANAGER_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Photo Manager - MAHIR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>''' + COMMON_CSS + '''
.photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-top:16px}
.photo-card{background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.12);border-radius:14px;padding:10px;text-align:center}
.photo-card img{width:100%;height:120px;object-fit:cover;border-radius:10px;margin-bottom:8px}
.photo-card .name{font-size:.72rem;color:var(--muted);word-break:break-all;margin-bottom:8px}
.role-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.65rem;font-weight:700;margin:2px}
.role-logo{background:rgba(245,200,66,.15);color:var(--gold)}
.role-cover{background:rgba(133,64,245,.15);color:#c9a7ff}
</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-images"></i> Photo Manager</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-clear btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/modules" class="btn btn-primary btn-sm"><i class="fas fa-puzzle-piece"></i> Modules</a>
      <a href="/owner/bio" class="btn btn-warning btn-sm"><i class="fas fa-pen"></i> Auto Bio</a>
      <a href="/owner/links" class="btn btn-success btn-sm"><i class="fas fa-link"></i> Links &amp; App</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-upload"></i> Upload Photos (Multiple)</div>
    <form method="POST" action="/owner/upload_photo" enctype="multipart/form-data" class="upload-form">
      <input type="file" name="photo" accept="image/*" multiple required>
      <button type="submit" class="btn btn-gold"><i class="fas fa-cloud-upload-alt"></i> Upload All</button>
    </form>
    <p style="color:var(--muted);font-size:.8rem;margin-top:10px;">
      Multiple images supported. PNG, JPG, WEBP, GIF, SVG. Saved to <code>photo/</code> folder.
      Same-name files get a timestamp suffix so they are not overwritten.
    </p>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-star"></i> Current Roles</div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Logo</div>
        <img src="{{ logo_url }}" style="width:80px;height:80px;border-radius:50%;object-fit:cover;margin:10px auto;display:block;border:2px solid var(--gold)"/>
        <div class="stat-value" style="font-size:.85rem">{{ logo_image or 'Auto' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Cover</div>
        <img src="{{ cover_url }}" style="width:100%;max-height:80px;object-fit:cover;border-radius:10px;margin:10px 0;border:1px solid rgba(245,200,66,.2)"/>
        <div class="stat-value" style="font-size:.85rem">{{ cover_image or 'Auto' }}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-folder-open"></i> Photo Library ({{ photos|length }})</div>
    {% if photos %}
    <div class="photo-grid">
      {% for p in photos %}
      <div class="photo-card">
        <img src="{{ p.url }}" alt="{{ p.name }}"/>
        <div class="name">{{ p.name }} <br><small>{{ p.size_str }}</small></div>
        {% if logo_image == p.name %}<span class="role-badge role-logo">LOGO</span>{% endif %}
        {% if cover_image == p.name %}<span class="role-badge role-cover">COVER</span>{% endif %}
        <div class="flex" style="justify-content:center;margin-top:8px;gap:4px;flex-wrap:wrap">
          <form method="POST" action="/owner/set_photo_role" style="display:inline">
            <input type="hidden" name="role" value="logo"/>
            <input type="hidden" name="filename" value="{{ p.name }}"/>
            <button type="submit" class="btn btn-xs btn-warning">Set Logo</button>
          </form>
          <form method="POST" action="/owner/set_photo_role" style="display:inline">
            <input type="hidden" name="role" value="cover"/>
            <input type="hidden" name="filename" value="{{ p.name }}"/>
            <button type="submit" class="btn btn-xs btn-primary">Set Cover</button>
          </form>
          <form method="POST" action="/owner/delete_photo/{{ p.name }}" style="display:inline" onsubmit="return confirm('Delete?')">
            <button type="submit" class="btn btn-xs btn-danger"><i class="fas fa-trash"></i></button>
          </form>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p class="empty-row" style="text-align:center;color:var(--muted);padding:30px">No photos yet. Upload some PNG/JPG files.</p>
    {% endif %}
  </div>
</div>
''' + VOICE_HELPER_JS + '''
</body></html>'''


# ============================================================
#  MODULE MANAGER HTML
# ============================================================
MODULE_MANAGER_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Module Manager - MAHIR</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>''' + COMMON_CSS + '''
.mod-ok{color:#4ade80}.mod-missing{color:#ff5a76}
.pkg-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:10px;background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.12);margin:4px;font-size:.8rem}
</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-puzzle-piece"></i> Module / Pip Manager</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-clear btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/photos" class="btn btn-info btn-sm"><i class="fas fa-images"></i> Photos</a>
      <a href="/owner/bio" class="btn btn-warning btn-sm"><i class="fas fa-pen"></i> Auto Bio</a>
      <a href="/owner/links" class="btn btn-success btn-sm"><i class="fas fa-link"></i> Links &amp; App</a>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for cat, msg in messages %}
  <div class="alert {{ cat }}"><i class="fas fa-{{ 'check-circle' if cat=='success' else 'exclamation-circle' }}"></i> {{ msg }}</div>
  {% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-magic"></i> Auto Detect & Fix Missing Modules</div>
    <p style="color:var(--muted);font-size:.85rem;margin-bottom:12px">
      Scans running bot logs for <code>ModuleNotFoundError</code> (e.g. <code>edge_tts</code>) and installs them automatically.
    </p>
    {% if missing_detected %}
    <div style="margin-bottom:12px">
      <strong style="color:var(--red2)">Detected missing:</strong>
      {% for m in missing_detected %}<span class="pkg-chip mod-missing"><i class="fas fa-times-circle"></i> {{ m }}</span>{% endfor %}
    </div>
    {% else %}
    <p style="color:var(--green);margin-bottom:12px"><i class="fas fa-check-circle"></i> No missing modules detected in current logs.</p>
    {% endif %}
    <form method="POST" action="/owner/modules/auto_fix" onsubmit="return confirm('Install all detected missing packages?')">
      <button type="submit" class="btn btn-gold"><i class="fas fa-bolt"></i> Auto Fix Detected Modules</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-terminal"></i> Custom Pip Install</div>
    <form method="POST" action="/owner/modules/install">
      <div class="input-group" style="margin-bottom:12px">
        <input type="text" name="packages" placeholder="e.g. edge-tts PyJWT google-play-scraper" style="flex:1;min-width:220px" required>
        <label style="display:flex;align-items:center;gap:6px;color:var(--muted);font-size:.85rem">
          <input type="checkbox" name="upgrade" value="1"> Upgrade
        </label>
        <button type="submit" class="btn btn-success"><i class="fas fa-download"></i> Install</button>
      </div>
    </form>
    <div class="flex" style="gap:10px;flex-wrap:wrap;margin-top:8px">
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="action" value="upgrade_pip"/>
        <button type="submit" class="btn btn-sm btn-warning"><i class="fas fa-arrow-up"></i> Upgrade pip + setuptools + wheel</button>
      </form>
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="from_requirements" value="1"/>
        <button type="submit" class="btn btn-sm btn-primary"><i class="fas fa-file-alt"></i> pip install -r requirements.txt</button>
      </form>
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="packages" value="edge-tts"/>
        <button type="submit" class="btn btn-sm btn-info">edge-tts</button>
      </form>
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="packages" value="PyJWT"/>
        <button type="submit" class="btn btn-sm btn-info">PyJWT</button>
      </form>
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="packages" value="google-play-scraper"/>
        <button type="submit" class="btn btn-sm btn-info">google-play-scraper</button>
      </form>
      <form method="POST" action="/owner/modules/install" style="display:inline">
        <input type="hidden" name="packages" value="pycryptodome"/>
        <button type="submit" class="btn btn-sm btn-info">pycryptodome</button>
      </form>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-list"></i> Common Bot Packages Status</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      {% for p in common_status %}
      <span class="pkg-chip {{ 'mod-ok' if p.installed else 'mod-missing' }}">
        <i class="fas fa-{{ 'check' if p.installed else 'times' }}"></i>
        {{ p.name }}
      </span>
      {% endfor %}
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-box"></i> Installed (tracked)</div>
    {% if installed %}
    <div class="table-wrapper">
      <table>
        <thead><tr><th>Package</th><th>Version</th></tr></thead>
        <tbody>
        {% for p in installed %}
        <tr><td><code>{{ p.name }}</code></td><td>{{ p.version }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <p style="color:var(--muted)">No tracked packages found.</p>
    {% endif %}
  </div>
</div>
</body></html>'''


# ============================================================
#  OWNER DASHBOARD
# ============================================================
OWNER_DASHBOARD_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Owner Dashboard - MAHIR PREMIUM</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-crown"></i> Owner Dashboard</h1>
    <div class="flex">
      <a href="/owner/modules" class="btn btn-primary btn-sm"><i class="fas fa-puzzle-piece"></i> Modules</a>
      <a href="/owner/photos" class="btn btn-info btn-sm"><i class="fas fa-images"></i> Photos</a>
      <a href="/owner/bio" class="btn btn-warning btn-sm"><i class="fas fa-pen"></i> Auto Bio</a>
      <a href="/owner/links" class="btn btn-success btn-sm"><i class="fas fa-link"></i> Links &amp; App</a>
      <form method="POST" action="/owner/reset_all_bots" onsubmit="return confirm('⚠️ Reset All?');" style="display:inline;"><button type="submit" class="btn btn-reset btn-sm"><i class="fas fa-sync-alt"></i> Reset All</button></form>
      {% if global_stop %}
        <form method="POST" action="/owner/start_all_bots" style="display:inline;"><button type="submit" class="btn btn-success btn-sm"><i class="fas fa-play"></i> Resume All</button></form>
      {% else %}
        <form method="POST" action="/owner/stop_all_bots" onsubmit="return confirm('Stop all bots globally?');" style="display:inline;"><button type="submit" class="btn btn-danger btn-sm"><i class="fas fa-hand-paper"></i> Stop All (Lock)</button></form>
      {% endif %}
      <span class="welcome-text">Welcome, <strong>{{ session.username }}</strong></span>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  {% if global_stop %}
  <div class="card" style="background:rgba(212,42,58,.1);border-color:rgba(212,42,58,.4);">
    <div style="display:flex;align-items:center;gap:12px;color:var(--red2);font-weight:700;"><i class="fas fa-exclamation-triangle" style="font-size:1.5rem;"></i> <span>Global Bot Stop চালু! সব user bot বন্ধ (force-active বাদে)।</span></div>
  </div>
  {% endif %}

  <div class="card">
    <div class="card-title"><i class="fas fa-tachometer-alt"></i> Concurrent Bot Limit</div>
    <p style="color:var(--muted);font-size:.85rem;margin-bottom:12px;">
      একসাথে কতগুলো বট চলতে পারবে সেট করুন। লিমিট পূর্ণ হলে নতুন বট স্টার্ট হবে না (অটো-রিস্টার্টও না)।
      <strong>-1 = Unlimited</strong>
    </p>
    <form method="POST" action="/owner/set_max_bots" class="input-group">
      <input type="number" name="max_running_bots" value="{{ max_running_bots }}" min="-1" max="5000" style="width:140px;" required/>
      <button type="submit" class="btn btn-gold btn-sm"><i class="fas fa-save"></i> Save Limit</button>
      <span class="stat-box">Running now: <strong>{{ running_bots_count }}</strong>
        {% if max_running_bots >= 0 %} / {{ max_running_bots }}{% else %} / ∞{% endif %}
      </span>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-server"></i> Server Resources</div>
    <div class="system-stats">
      <div class="stat-card"><div class="stat-label">CPU</div><div class="stat-value">{{ cpu }}%</div><div class="progress-bar"><div class="progress-fill" style="width:{{ cpu }}%;"></div></div></div>
      <div class="stat-card"><div class="stat-label">RAM</div><div class="stat-value">{{ ram_percent }}%</div><div class="progress-bar"><div class="progress-fill" style="width:{{ ram_percent }}%;"></div></div></div>
      <div class="stat-card"><div class="stat-label">Disk</div><div class="stat-value">{{ disk_percent }}%</div><div class="progress-bar"><div class="progress-fill" style="width:{{ disk_percent }}%;"></div></div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-bullhorn"></i> Global Notice Settings</div>
    <form method="POST" action="/owner/set_global_notice">
      <textarea name="notice_text" rows="3">{{ global_notice }}</textarea>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <button type="submit" class="btn btn-gold btn-sm"><i class="fas fa-save"></i> Save Notice</button>
        <a href="/owner/preview_global_notice" target="_blank" class="btn btn-info btn-sm"><i class="fas fa-eye"></i> Preview</a>
      </div>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-bell"></i> User Login Notice (Popup)</div>
    <form method="POST" action="/owner/set_user_login_notice">
      <div class="flex" style="margin-bottom:12px;">
        <label style="color:var(--gold2);font-weight:600;">Status:</label>
        {% if login_notice_enabled %}<span class="badge badge-running">🟢 ENABLED</span>
        {% else %}<span class="badge badge-stopped">🔴 DISABLED</span>{% endif %}
      </div>
      <textarea name="notice_text" rows="4" placeholder="Type notice text here...">{{ login_notice_text }}</textarea>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <button type="submit" name="action" value="save" class="btn btn-gold btn-sm"><i class="fas fa-save"></i> Save</button>
        {% if login_notice_enabled %}<button type="submit" name="action" value="disable" class="btn btn-danger btn-sm"><i class="fas fa-toggle-off"></i> Disable Notice</button>
        {% else %}<button type="submit" name="action" value="enable" class="btn btn-success btn-sm"><i class="fas fa-toggle-on"></i> Enable Notice</button>{% endif %}
      </div>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-upload"></i> Owner Actions</div>
    <div class="flex"><a href="/owner/files" class="btn btn-gold"><i class="fas fa-folder"></i> File Manager</a></div>
    <div style="margin-top:14px;">
      <form method="POST" action="/owner/upload_mahir" enctype="multipart/form-data" class="upload-form" id="uploadMahirForm">
        <input type="file" name="mahir_file" accept=".py" required style="flex:1;min-width:200px;" id="mahirFileInput"/>
        <button type="submit" class="btn btn-warning btn-sm" id="uploadMahirBtn"><i class="fas fa-cloud-upload-alt"></i> Upload mahir.py</button>
      </form>
    </div>
    <div style="margin-top:14px;">
      <form method="POST" action="/owner/upload_users_db" enctype="multipart/form-data" class="upload-form" id="uploadDbForm">
        <input type="file" name="db_file" accept=".db" required style="flex:1;min-width:200px;"/>
        <button type="submit" class="btn btn-warning btn-sm" id="uploadDbBtn" onclick="return confirm('⚠️ Replace DB?');"><i class="fas fa-upload"></i> Upload DB</button>
      </form>
    </div>
    {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-user-tie"></i> Agent Management</div>
    <form method="POST" action="/owner/create_agent" class="flex" id="createAgentForm">
      <input type="text" name="username" placeholder="Username" required class="flex-grow"/>
      <input type="email" name="email" placeholder="Email" required class="flex-grow"/>
      <input type="password" name="password" placeholder="Password" required class="flex-grow"/>
      <button type="submit" class="btn btn-success btn-sm" id="createAgentBtn"><i class="fas fa-user-plus"></i> Create</button>
    </form>
    <div class="table-wrapper">
      <table>
        <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Keys/Limit</th><th>Action</th></tr></thead>
        <tbody>
          {% for agent in agents %}
          <tr>
            <td>{{ agent.id }}</td>
            <td><strong>{{ agent.username }}</strong></td>
            <td>{{ agent.email or '-' }}</td>
            <td>
              <span class="badge badge-admin">{{ agent.key_count }}{% if agent.key_limit >= 0 %} / {{ agent.key_limit }}{% else %} / ∞{% endif %}</span>
              <form method="POST" action="/owner/set_key_limit/{{ agent.id }}" style="margin-top:4px;display:flex;gap:4px;">
                <input type="number" name="key_limit" value="{{ agent.key_limit }}" min="-1" style="width:70px;padding:4px;font-size:.72rem;"/>
                <button type="submit" class="btn btn-gold btn-xs"><i class="fas fa-save"></i></button>
              </form>
            </td>
            <td>
              <div class="td-actions">
                <a href="/owner/login_as/{{ agent.id }}" class="btn btn-warning btn-sm"><i class="fas fa-sign-in-alt"></i> User Panel</a>
                <a href="/owner/user_details/{{ agent.id }}" class="btn btn-info btn-sm"><i class="fas fa-eye"></i></a>
                <form method="POST" action="/owner/delete_agent/{{ agent.id }}" onsubmit="return confirm('Delete?');" style="display:inline;"><button type="submit" class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></button></form>
              </div>
            </td>
          </tr>
          {% else %}<tr class="empty-row"><td colspan="5">No agents</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-key"></i> Generate Key (Owner)</div>
    <form method="POST" action="/owner/create_key" class="flex">
      <div class="input-group"><label>Days (0=Permanent):</label><input type="number" name="days_valid" value="30" min="0" style="width:110px;"/></div>
      <button type="submit" class="btn btn-gold"><i class="fas fa-plus-circle"></i> Generate</button>
    </form>
    <form method="POST" action="/owner/create_key" class="flex" style="margin-top:10px;">
      <input type="hidden" name="trial_3h" value="1"/>
      <button type="submit" class="btn btn-warning" style="background:linear-gradient(135deg,#f59e0b,#ef4444);"><i class="fas fa-hourglass-half"></i> Generate TRIAL Key (3 Hours)</button>
    </form>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-layer-group" style="color:var(--purple);"></i> Groups Overview — Keys &amp; Users</div>
    {% for gk in grouped_keys %}
      {% set gu = grouped_users | selectattr('slug','equalto', gk.slug) | first | default(none) %}
      <div class="group-card">
        <div class="group-header">
          <div class="group-name">
            {% if gk.is_owner %}<i class="fas fa-crown" style="color:#F5C842;"></i> {{ gk.name }}
            {% else %}<i class="fas fa-user-tie" style="color:#7ab5ff;"></i> AGENT {{ gk.name }}{% endif %}
          </div>
          <div class="group-stats" style="flex-wrap:wrap;gap:6px;">
            <span class="group-stat"><i class="fas fa-key" style="color:#F5C842;font-size:.7rem;"></i>&nbsp;<strong>{{ gk.total_keys }}</strong> Keys</span>
            <span class="group-stat">✅ <strong>{{ gk.used_keys }}</strong> Used</span>
            <span class="group-stat">⏳ <strong>{{ gk.unused_keys }}</strong> Unused</span>
            {% if gu %}
            <span class="group-stat"><i class="fas fa-users" style="color:#4ade80;font-size:.7rem;"></i>&nbsp;<strong>{{ gu.total_users }}</strong> Users</span>
            <span class="group-stat">🟢 <strong>{{ gu.active_users }}</strong> Active</span>
            <span class="group-stat">🔴 <strong>{{ gu.expired_users }}</strong> Expired</span>
            {% endif %}
            <a href="/owner/group_keys/{{ gk.slug }}" class="btn btn-gold btn-sm" style="font-size:.7rem;"><i class="fas fa-key"></i> Keys</a>
            {% if gu %}<a href="/owner/group_users/{{ gu.slug }}" class="btn btn-primary btn-sm" style="font-size:.7rem;"><i class="fas fa-users"></i> Users</a>{% endif %}
          </div>
        </div>
      </div>
    {% endfor %}
    {% if not grouped_keys %}<div style="text-align:center;color:var(--muted);padding:30px;">No groups yet.</div>{% endif %}
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-history" style="color:var(--purple);"></i> Subscription History (Grouped)</div>
    {% for group in grouped_history %}
    <div class="group-card">
      <div class="group-header">
        <div class="group-name">
          {% if group.is_owner %}<i class="fas fa-crown" style="color:#F5C842;"></i> {{ group.name }}
          {% else %}<i class="fas fa-user-tie" style="color:#7ab5ff;"></i> AGENT {{ group.name }}{% endif %}
        </div>
        <div class="group-stats">
          <span class="group-stat"><strong>{{ group.total_entries }}</strong> Records</span>
          <span class="group-stat">📅 <strong>{{ group.total_days }}</strong> Days added</span>
          <a href="/owner/group_history/{{ group.slug }}" class="btn btn-gold btn-sm"><i class="fas fa-eye"></i> View History</a>
        </div>
      </div>
    </div>
    {% else %}<div style="text-align:center;color:var(--muted);padding:30px;">No history yet.</div>{% endfor %}
  </div>

  <a href="/logout" class="back-link"><i class="fas fa-arrow-left"></i> Back</a>
</div>

<!-- ═══════ ANIMATED NEW KEY MODAL ═══════ -->
<div class="key-modal-overlay" id="newKeyModal">
    <div class="key-modal-box">
        <div class="key-sparkles" id="keySparkles"></div>
        <button class="modal-close" onclick="closeKeyModal()"
                style="position:absolute;top:14px;right:18px;background:none;border:none;color:#FFE28A;font-size:1.8rem;cursor:pointer;z-index:10;line-height:1;padding:0;">&times;</button>
        <div class="key-modal-icon"><i class="fas fa-key"></i></div>
        <div class="key-modal-title">🎉 Key Generated!</div>
        <div class="key-modal-sub">নিচের key টি সংরক্ষণ করুন — এটি আর দেখানো হবে না!</div>
        <div id="newKeyDays" class="key-days-badge">30 Days Valid</div>
        <div class="animated-key" id="newKeyValue" onclick="copyNewKey(this)" data-key=""></div>
        <div class="key-copy-hint"><i class="fas fa-hand-pointer"></i> Click the key to copy</div>
        <div class="key-modal-actions">
            <button type="button" class="key-modal-btn key-modal-btn-primary"
                    onclick="copyNewKey(document.getElementById('newKeyValue'))">
                <i class="fas fa-copy"></i> Copy Key
            </button>
            <button type="button" class="key-modal-btn key-modal-btn-secondary" onclick="closeKeyModal()">
                <i class="fas fa-times"></i> Close
            </button>
        </div>
    </div>
</div>

<script>
document.getElementById('uploadMahirForm').addEventListener('submit',function(e){var f=document.getElementById('mahirFileInput').files[0];if(f && f.name.toLowerCase()!=='mahir.py'){e.preventDefault();alert('❌ Only "mahir.py"!');return false;}var b=document.getElementById('uploadMahirBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Rebuilding...';if(window.mahirSpeak)window.mahirSpeak('মাহির ফাইল আপলোড শুরু');});
document.getElementById('uploadDbForm').addEventListener('submit',function(){var b=document.getElementById('uploadDbBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Processing...';if(window.mahirSpeak)window.mahirSpeak('ডাটাবেস আপলোড শুরু');});
document.getElementById('createAgentForm').addEventListener('submit',function(){var b=document.getElementById('createAgentBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Creating...';if(window.mahirSpeak)window.mahirSpeak('এজেন্ট তৈরি হচ্ছে');});

/* ═══════════ NEW KEY ANIMATED MODAL JS ═══════════ */
(function () {
    window.showKeyModal = function (key, durationText, isPermanent) {
        var modal = document.getElementById('newKeyModal');
        if (!modal) return;
        var keyEl = document.getElementById('newKeyValue');
        if (keyEl) { keyEl.textContent = key; keyEl.setAttribute('data-key', key); keyEl.classList.remove('copied'); }
        var daysEl = document.getElementById('newKeyDays');
        if (daysEl) { daysEl.textContent = durationText; daysEl.className = 'key-days-badge' + (isPermanent ? ' permanent' : ''); }
        var sc = document.getElementById('keySparkles');
        if (sc) {
            sc.innerHTML = '';
            for (var i = 0; i < 22; i++) {
                var s = document.createElement('div');
                s.className = 'key-sparkle' + (i % 3 === 1 ? ' purple' : i % 3 === 2 ? ' blue' : '');
                s.style.left = (Math.random() * 100) + '%';
                s.style.top = (Math.random() * 100) + '%';
                s.style.setProperty('--tx', (Math.random() * 140 - 70) + 'px');
                s.style.setProperty('--ty', (-Math.random() * 140 - 30) + 'px');
                s.style.animationDelay = (Math.random() * 1.8) + 's';
                sc.appendChild(s);
            }
        }
        modal.classList.add('show');
        var box = modal.querySelector('.key-modal-box');
        if (box) { box.style.animation = 'none'; void box.offsetWidth; box.style.animation = ''; }
        if (window.mahirSpeak) window.mahirSpeak('নতুন কী তৈরি হয়েছে');
    };
    window.closeKeyModal = function () {
        var modal = document.getElementById('newKeyModal');
        if (modal) modal.classList.remove('show');
    };
    window.copyNewKey = function (el) {
        if (!el) return;
        var key = el.getAttribute('data-key') || el.textContent;
        var original = el.textContent;
        function markCopied() {
            el.classList.add('copied');
            el.textContent = '✅ COPIED TO CLIPBOARD';
            if (window.mahirSpeak) window.mahirSpeak('কী কপি হয়েছে');
            setTimeout(function () { el.classList.remove('copied'); el.textContent = original; }, 1600);
        }
        function fallback() {
            var ta = document.createElement('textarea');
            ta.value = key; ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); markCopied(); } catch(e) { window.prompt('Copy this key manually:', key); }
            document.body.removeChild(ta);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(key).then(markCopied).catch(fallback);
        } else { fallback(); }
    };
    document.addEventListener('DOMContentLoaded', function () {
        var modal = document.getElementById('newKeyModal');
        if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) window.closeKeyModal(); });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') window.closeKeyModal(); });
})();
</script>
{% if new_key_data %}
<script>
document.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
        if (typeof window.showKeyModal === 'function') {
            window.showKeyModal(
                {{ new_key_data.key | tojson }},
                {{ new_key_data.duration_text | tojson }},
                {{ 'true' if new_key_data.is_permanent else 'false' }}
            );
        }
    }, 400);
});
</script>
{% endif %}
''' + VOICE_HELPER_JS + '''
<script>
// Voice greeting + soft click sounds
(function(){
  function speak(text){
    try{
      if(!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = 'en-US';
      u.rate = 0.95;
      u.pitch = 1.05;
      window.speechSynthesis.speak(u);
    }catch(e){}
  }
  function playBeep(){
    try{
      var ctx = new (window.AudioContext||window.webkitAudioContext)();
      var o = ctx.createOscillator();
      var g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = 880; o.type = 'sine';
      g.gain.setValueAtTime(0.08, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime+0.25);
      o.start(); o.stop(ctx.currentTime+0.25);
    }catch(e){}
  }
  document.addEventListener('DOMContentLoaded', function(){
    {% if just_logged_in %}
    setTimeout(function(){
      playBeep();
      speak("Welcome {{ voice_name or 'Owner' }}. Mahir TCP Panel is ready.");
    }, 600);
    {% endif %}
    document.querySelectorAll('button, .btn').forEach(function(b){
      b.addEventListener('click', function(){ playBeep(); }, {passive:true});
    });
  });
})();
</script>
</body></html>'''


# ============================================================
#  OWNER GROUP DETAIL PAGES
# ============================================================
OWNER_GROUP_KEYS_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>{{ group_name }} - Keys</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1>{% if is_owner %}<i class="fas fa-crown" style="color:#F5C842;"></i> {{ group_name }}{% else %}<i class="fas fa-user-tie" style="color:#7ab5ff;"></i> AGENT {{ group_name }}{% endif %}</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-chart-simple"></i> Key Statistics</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Total Keys</div><div class="stat-value">{{ keys|length }}</div></div>
      <div class="stat-card"><div class="stat-label">Used</div><div class="stat-value" style="color:#7ab5ff;">{{ used_count }}</div></div>
      <div class="stat-card"><div class="stat-label">Unused</div><div class="stat-value" style="color:#F5C842;">{{ unused_count }}</div></div>
      <div class="stat-card"><div class="stat-label">Renewed Users</div><div class="stat-value" style="color:#4ade80;">{{ renewed_count }}</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-key"></i> Keys List — Click key to view details</div>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>KEY</th>
            <th>CREATED</th>
            <th>DURATION</th>
            <th>USED BY</th>
            <th>RENEWALS</th>
            <th>STATUS</th>
            <th style="text-align:right;">ACTION</th>
          </tr>
        </thead>
        <tbody>
          {% for key in keys %}
          <tr>
            <td>
              <a href="/owner/key_details/{{ key.id }}" style="text-decoration:none;">
                <span class="key-code" style="cursor:pointer;">{{ key.key }}</span>
              </a>
            </td>
            <td style="color:var(--muted);font-size:.78rem;">{{ key.created_at[:16] if key.created_at else '—' }}</td>
            <td>
              {% if key.duration_days == 0 %}
                <span class="duration-tag" style="background:rgba(74,222,128,.15);color:#4ade80;border-color:rgba(74,222,128,.4);">∞ Permanent</span>
              {% else %}
                <span class="duration-tag">{{ key.duration_days }}d</span>
              {% endif %}
            </td>
            <td>{% if key.used_by %}<span class="used-by"><i class="fas fa-user user-icon"></i>{{ key.used_by }}</span>{% else %}<span style="color:var(--muted);">—</span>{% endif %}</td>
            <td>
              {% if key.renew_count > 0 %}
                <span class="days-badge"><i class="fas fa-redo"></i> {{ key.renew_count }}x (+{{ key.renew_days }}d)</span>
              {% else %}
                <span style="color:var(--muted);font-size:.75rem;">—</span>
              {% endif %}
            </td>
            <td>{% if key.is_used %}<span class="status-badge used"><i class="fas fa-check-circle"></i> USED</span>{% else %}<span class="status-badge available"><i class="fas fa-clock"></i> AVAILABLE</span>{% endif %}</td>
            <td style="text-align:right;">
              <a href="/owner/key_details/{{ key.id }}" class="btn btn-info btn-sm" style="font-size:.7rem;"><i class="fas fa-eye"></i> Details</a>
              <form method="POST" action="/owner/delete_key/{{ key.id }}" onsubmit="return confirm('Delete this key AND its subscription history?');" style="display:inline;">
                <button type="submit" class="delete-key-btn" title="Delete" style="width:30px;height:30px;font-size:.72rem;"><i class="fas fa-trash"></i></button>
              </form>
            </td>
          </tr>
          {% else %}<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:30px;">No keys in this group.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/owner/dashboard" class="back-link"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
</div></body></html>'''


OWNER_KEY_DETAILS_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>Key Details</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-key"></i> Key Details</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/group_keys/{{ creator_slug }}" class="btn btn-gold btn-sm"><i class="fas fa-layer-group"></i> Back to Group</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}

  <div class="card">
    <div class="card-title"><i class="fas fa-info-circle"></i> Key Information</div>
    <div class="detail-grid">
      <div class="detail-item" style="grid-column:1/-1;">
        <div class="detail-label">Key</div>
        <div class="detail-value big" style="word-break:break-all;">{{ key.key }}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Created By</div>
        <div class="detail-value">
          {% if is_owner_group %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER</span>
          {% else %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> {{ key.created_by }}</span>{% endif %}
        </div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Created At</div>
        <div class="detail-value">{{ key.created_at or '—' }}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Duration</div>
        <div class="detail-value">
          {% if key.duration_days == 0 %}<span style="color:#4ade80;">∞ Permanent</span>
          {% else %}{{ key.duration_days }} days{% endif %}
        </div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Expiry Date</div>
        <div class="detail-value">{{ key.expiry_date[:16] if key.expiry_date else '∞ Never' }}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Status</div>
        <div class="detail-value">
          {% if key.is_used %}<span class="status-badge used"><i class="fas fa-check-circle"></i> USED</span>
          {% else %}<span class="status-badge available"><i class="fas fa-clock"></i> AVAILABLE</span>{% endif %}
        </div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Used By</div>
        <div class="detail-value">{{ key.used_by or '—' }}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Used At</div>
        <div class="detail-value">{{ key.used_at[:16] if key.used_at else '—' }}</div>
      </div>
    </div>
  </div>

  {% if user %}
  <div class="card">
    <div class="card-title"><i class="fas fa-user"></i> User Information (Who used this key)</div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">User ID</div><div class="detail-value big">#{{ user.id }}</div></div>
      <div class="detail-item"><div class="detail-label">Username</div><div class="detail-value big">{{ user.username }}</div></div>
      <div class="detail-item"><div class="detail-label">Email</div><div class="detail-value">{{ user.email or '—' }}</div></div>
      <div class="detail-item"><div class="detail-label">Bot UID</div><div class="detail-value">{{ user.bot_uid or '—' }}</div></div>
      <div class="detail-item"><div class="detail-label">Created By</div>
        <div class="detail-value">
          {% if not user.created_by_agent or user.created_by_agent in ['Owner','OWNER','admin','system','MAHIR TCP'] %}
            <span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER MAHIR</span>
          {% else %}
            <span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT {{ user.created_by_agent }}</span>
          {% endif %}
        </div>
      </div>
      <div class="detail-item"><div class="detail-label">Current Subscription</div>
        <div class="detail-value">
          {% if user.sub_status == 'unlimited' %}<span style="color:#4ade80;">∞ Unlimited</span>
          {% elif user.sub_status == 'expired' %}<span style="color:#ff5a76;">Expired</span>
          {% else %}<span style="color:#4ade80;">{{ user.sub_days }} days left</span>{% endif %}
        </div>
      </div>
      <div class="detail-item" style="grid-column:1/-1;">
        <a href="/owner/user_details/{{ user.id }}" class="btn btn-gold btn-sm"><i class="fas fa-eye"></i> View Full User Details</a>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-history" style="color:var(--purple);"></i> Renewal History for this User ({{ renewal_history|length }})</div>
    {% if renewal_history %}
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>#</th>
            <th>DAYS ADDED</th>
            <th>MODE</th>
            <th>OLD EXPIRY</th>
            <th>NEW EXPIRY</th>
            <th>EXTENDED BY</th>
            <th>ROLE</th>
            <th>WHEN</th>
          </tr>
        </thead>
        <tbody>
          {% for h in renewal_history %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>
              {% if h.mode == 'reset' %}
                <span class="days-badge warn"><i class="fas fa-sync"></i> Reset +{{ h.days_added }}d</span>
              {% else %}
                <span class="days-badge permanent"><i class="fas fa-plus-circle"></i> +{{ h.days_added }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.mode }}</small></td>
            <td><small style="color:var(--muted);">{{ h.old_expiry[:16] if h.old_expiry else '—' }}</small></td>
            <td><small style="color:#7dd3fc;">{{ h.new_expiry[:16] if h.new_expiry else '—' }}</small></td>
            <td><strong style="color:#FFE28A;">{{ h.extended_by or '—' }}</strong></td>
            <td>
              {% if h.extended_by_role == 'owner' %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER</span>
              {% elif h.extended_by_role == 'agent' %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT</span>
              {% else %}<small style="color:var(--muted);">—</small>{% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.created_at[:16] if h.created_at else '—' }}</small></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div style="text-align:center;color:var(--muted);padding:24px;">No renewal history for this user yet.</div>
    {% endif %}
  </div>
  {% else %}
  <div class="card">
    <div class="card-title"><i class="fas fa-info-circle"></i> Status</div>
    <div style="text-align:center;color:var(--muted);padding:24px;">
      <i class="fas fa-clock" style="font-size:2rem;margin-bottom:12px;display:block;color:var(--gold);"></i>
      This key is not used yet — no user associated.
    </div>
  </div>
  {% endif %}

  <div class="card">
    <div class="card-title"><i class="fas fa-tools"></i> Actions</div>
    <div class="flex">
      <form method="POST" action="/owner/delete_key/{{ key.id }}" onsubmit="return confirm('⚠️ Delete this key AND its subscription history?');">
        <button type="submit" class="btn btn-danger"><i class="fas fa-trash"></i> Delete Key & History</button>
      </form>
    </div>
  </div>

  <a href="/owner/group_keys/{{ creator_slug }}" class="back-link"><i class="fas fa-arrow-left"></i> Back to Group Keys</a>
</div></body></html>'''


OWNER_GROUP_USERS_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>{{ group_name }} - Users</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1>{% if is_owner %}<i class="fas fa-crown" style="color:#F5C842;"></i> {{ group_name }} — Users{% else %}<i class="fas fa-user-tie" style="color:#7ab5ff;"></i> AGENT {{ group_name }} — Users{% endif %}</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-users"></i> Users under {{ group_name }} ({{ users|length }})</div>
    <div class="table-wrapper">
      <table>
        <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Bot Status</th><th>Days Left</th><th>Renewals</th><th style="text-align:right;">Actions</th></tr></thead>
        <tbody>
          {% for user in users %}
          <tr>
            <td>{{ user.id }}</td>
            <td><strong>{{ user.username }}</strong></td>
            <td>{{ user.email or '—' }}</td>
            <td>
              {% if user.bot_status == 'running' %}<span class="badge badge-running">Running</span>
              {% elif user.bot_status == 'expired' %}<span class="badge badge-expired">Expired</span>
              {% else %}<span class="badge badge-unused">{{ user.bot_status or 'N/A' }}</span>{% endif %}
            </td>
            <td>
              {% if user.sub_status == 'unlimited' %}<span class="days-badge permanent"><i class="fas fa-infinity"></i> ∞</span>
              {% elif user.sub_status == 'expired' %}<span class="days-badge danger"><i class="fas fa-times-circle"></i> Expired</span>
              {% elif user.sub_days <= 3 %}<span class="days-badge danger"><i class="fas fa-exclamation-triangle"></i> {{ user.sub_days }}d</span>
              {% elif user.sub_days <= 7 %}<span class="days-badge warn"><i class="fas fa-clock"></i> {{ user.sub_days }}d</span>
              {% else %}<span class="days-badge"><i class="fas fa-check-circle"></i> {{ user.sub_days }}d</span>{% endif %}
            </td>
            <td>
              {% if user.renew_count > 0 %}<span class="days-badge"><i class="fas fa-redo"></i> {{ user.renew_count }}x (+{{ user.renew_days }}d)</span>
              {% else %}<span style="color:var(--muted);font-size:.75rem;">—</span>{% endif %}
            </td>
            <td>
              <div class="td-actions">
                <a href="/owner/user_details/{{ user.id }}" class="btn btn-info btn-sm"><i class="fas fa-eye"></i> Details</a>
                <a href="/owner/login_as/{{ user.id }}" class="btn btn-gold btn-sm" title="User Panel Login"><i class="fas fa-sign-in-alt"></i> Login</a>
              </div>
            </td>
          </tr>
          {% else %}<tr class="empty-row"><td colspan="7">No users in this group.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/owner/dashboard" class="back-link"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
</div></body></html>'''


OWNER_GROUP_HISTORY_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>{{ group_name }} - History</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''</style></head><body>
<div class="container">
  <div class="card header">
    <h1>{% if is_owner %}<i class="fas fa-crown" style="color:#F5C842;"></i> {{ group_name }} — History{% else %}<i class="fas fa-user-tie" style="color:#7ab5ff;"></i> AGENT {{ group_name }} — History{% endif %}</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-history" style="color:var(--purple);"></i> Subscription History ({{ history|length }} records)</div>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>#</th>
            <th>USERNAME</th>
            <th>DAYS ADDED</th>
            <th>MODE</th>
            <th>OLD EXPIRY</th>
            <th>NEW EXPIRY</th>
            <th>EXTENDED BY</th>
            <th>WHEN</th>
          </tr>
        </thead>
        <tbody>
          {% for h in history %}
          <tr>
            <td>{{ loop.index }}</td>
            <td><strong style="color:#FFE28A;">{{ h.username }}</strong></td>
            <td>
              {% if h.mode == 'reset' %}
                <span class="days-badge warn"><i class="fas fa-sync"></i> Reset +{{ h.days_added }}d</span>
              {% else %}
                <span class="days-badge permanent"><i class="fas fa-plus-circle"></i> +{{ h.days_added }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.mode }}</small></td>
            <td><small style="color:var(--muted);">{{ h.old_expiry[:16] if h.old_expiry else '—' }}</small></td>
            <td><small style="color:#7dd3fc;">{{ h.new_expiry[:16] if h.new_expiry else '—' }}</small></td>
            <td><strong style="color:#FFE28A;">{{ h.extended_by or '—' }}</strong></td>
            <td><small style="color:var(--muted);">{{ h.created_at[:16] if h.created_at else '—' }}</small></td>
          </tr>
          {% else %}<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:30px;">No history records.</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <a href="/owner/dashboard" class="back-link"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
</div></body></html>'''


# ============================================================
#  USER DETAILS (Owner view)
# ============================================================
USER_DETAILS_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>User Details - OWNER PANEL</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''
.copy-btn{background:rgba(245,200,66,.1);border:1px solid rgba(245,200,66,.25);color:var(--gold);padding:4px 10px;border-radius:8px;cursor:pointer;font-size:.7rem;margin-left:6px;font-weight:600}
</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-user-circle"></i> {{ user.username }}</h1>
    <div class="flex">
      {% if not user.is_admin %}
      <a href="/owner/login_as/{{ user.id }}" class="btn btn-gold btn-sm" style="font-weight:700;"><i class="fas fa-sign-in-alt"></i> User Panel Login</a>
      {% endif %}
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-arrow-left"></i> Dashboard</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-id-card"></i> Account Information</div>
    <div style="text-align:center;margin-bottom:16px;">
      {% if user.bot_disabled_by_admin %}<span class="live-badge live-offline"><i class="fas fa-hand-paper"></i> OWNER DISABLED</span>
      {% elif user.sub_status == 'expired' %}<span class="live-badge live-offline"><i class="fas fa-clock"></i> EXPIRED</span>
      {% elif live and live.is_running %}<span class="live-badge live-online"><i class="fas fa-circle"></i> LIVE · RUNNING</span>
      {% else %}<span class="live-badge live-offline"><i class="fas fa-circle"></i> OFFLINE</span>{% endif %}
    </div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">User ID</div><div class="detail-value big">#{{ user.id }}</div></div>
      <div class="detail-item"><div class="detail-label">Username</div><div class="detail-value big">{{ user.username }}<button class="copy-btn" onclick="copyT('{{ user.username }}')">Copy</button></div></div>
      <div class="detail-item"><div class="detail-label">Email</div><div class="detail-value">{{ user.email }}</div></div>
      <div class="detail-item"><div class="detail-label">Password</div><div class="detail-value">{{ user.password }}<button class="copy-btn" onclick="copyT('{{ user.password }}')">Copy</button></div></div>
      <div class="detail-item"><div class="detail-label">Role</div><div class="detail-value">{% if user.is_admin %}OWNER{% elif user.is_agent %}AGENT{% else %}USER{% endif %}</div></div>
      <div class="detail-item"><div class="detail-label">Created</div><div class="detail-value">{{ user.created_at }}</div></div>
      <div class="detail-item">
        <div class="detail-label">Subscription</div>
        <div class="detail-value">
          {% if user.sub_status == 'unlimited' %}<span style="color:#4ade80;">∞ Unlimited</span>
          {% elif user.sub_status == 'expired' %}<span style="color:#ff5a76;">Expired</span>
          {% else %}<span style="color:#4ade80;">{{ user.sub_days }} days left</span>{% endif %}
          <br><small style="color:var(--muted);">Time: {{ user.sub_time_left }}</small>
          {% if user.sub_expiry %}<br><small style="color:var(--muted);">Expires: {{ user.sub_expiry }}</small>{% endif %}
        </div>
      </div>
      <div class="detail-item"><div class="detail-label">Renew Count</div><div class="detail-value big">{{ user.renew_count }}x <small style="color:#4ade80;">(+{{ user.renew_days }}d)</small></div></div>
      <div class="detail-item"><div class="detail-label">Registration Key</div><div class="detail-value">{{ user.registration_key }}</div></div>
      <div class="detail-item"><div class="detail-label">Created By</div><div class="detail-value">{% if not user.created_by_agent or user.created_by_agent in ['Owner','OWNER','admin','system','MAHIR TCP'] %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER MAHIR</span>{% else %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT {{ user.created_by_agent }}</span>{% endif %}</div></div>
    </div>
  </div>

  {% if user.bot_uid != '—' and not user.is_agent %}
  <div class="card">
    <div class="card-title"><i class="fas fa-robot"></i> Bot Information</div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">Bot UID</div><div class="detail-value big">{{ user.bot_uid }}</div></div>
      <div class="detail-item"><div class="detail-label">Bot Password</div><div class="detail-value">{{ user.bot_pw }}</div></div>
      <div class="detail-item"><div class="detail-label">Bot File</div><div class="detail-value">{{ user.bot_file }}</div></div>
      <div class="detail-item"><div class="detail-label">Owner UIDs</div><div class="detail-value">{{ user.admin_uid }}</div></div>
      <div class="detail-item"><div class="detail-label">Bot Status</div><div class="detail-value">{{ user.bot_status }}</div></div>
      <div class="detail-item"><div class="detail-label">Force Active</div><div class="detail-value">{% if user.bot_force_active %}<span style="color:#4ade80;">YES</span>{% else %}<span style="color:var(--muted);">NO</span>{% endif %}</div></div>
    </div>
  </div>
  {% endif %}

  {% if live and not user.is_agent %}
  <div class="card">
    <div class="card-title"><i class="fas fa-satellite-dish"></i> Live Bot Status</div>
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">Live Bot Name</div><div class="detail-value big">{{ live.bot_name }}</div></div>
      <div class="detail-item"><div class="detail-label">UID</div><div class="detail-value">{{ live.bot_uid }}</div></div>
      <div class="detail-item"><div class="detail-label">Region</div><div class="detail-value">{{ live.bot_region }}</div></div>
      <div class="detail-item"><div class="detail-label">Clan ID</div><div class="detail-value">{{ live.bot_clan_id }}</div></div>
      <div class="detail-item"><div class="detail-label">Online Server</div><div class="detail-value">{{ live.bot_server }}</div></div>
      <div class="detail-item"><div class="detail-label">Chat Server</div><div class="detail-value">{{ live.bot_chat_server }}</div></div>
      <div class="detail-item"><div class="detail-label">Uptime</div><div class="detail-value">{{ live.uptime }}</div></div>
      <div class="detail-item"><div class="detail-label">CPU</div><div class="detail-value">{{ live.cpu }}%</div></div>
      <div class="detail-item"><div class="detail-label">RAM</div><div class="detail-value">{{ live.ram }}%</div></div>
      <div class="detail-item"><div class="detail-label">Last Message</div><div class="detail-value">{{ live.last_message }}</div></div>
    </div>
  </div>
  {% endif %}

  {% if not user.is_agent and not user.is_admin %}
  <div class="card">
    <div class="card-title"><i class="fas fa-sync"></i> Subscription Management</div>
    <form method="POST" action="/owner/renew_subscription/{{ user.id }}" class="flex">
      <label style="color:var(--gold2);font-weight:600;">Package:</label>
      <select name="mode">
        <option value="extend">Extend from current</option>
        <option value="reset">New package (reset)</option>
      </select>
      <label style="color:var(--gold2);font-weight:600;">Days:</label>
      <input type="number" name="days" value="30" min="1" style="width:120px;"/>
      <button type="submit" class="btn btn-gold"><i class="fas fa-save"></i> Apply</button>
    </form>
  </div>
  {% endif %}

  {% if sub_history %}
  <div class="card">
    <div class="card-title"><i class="fas fa-history"></i> Renewal History ({{ sub_history|length }})</div>
    <div class="keys-table-wrap">
      <table class="keys-table">
        <thead>
          <tr>
            <th>#</th>
            <th>DAYS ADDED</th>
            <th>MODE</th>
            <th>OLD EXPIRY</th>
            <th>NEW EXPIRY</th>
            <th>EXTENDED BY</th>
            <th>ROLE</th>
            <th>WHEN</th>
          </tr>
        </thead>
        <tbody>
          {% for h in sub_history %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>
              {% if h.mode == 'reset' %}
                <span class="days-badge warn"><i class="fas fa-sync"></i> Reset +{{ h.days_added }}d</span>
              {% else %}
                <span class="days-badge permanent"><i class="fas fa-plus-circle"></i> +{{ h.days_added }} days</span>
              {% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.mode }}</small></td>
            <td><small style="color:var(--muted);">{{ h.old_expiry[:16] if h.old_expiry else '—' }}</small></td>
            <td><small style="color:#7dd3fc;">{{ h.new_expiry[:16] if h.new_expiry else '—' }}</small></td>
            <td><strong style="color:#FFE28A;">{{ h.extended_by or '—' }}</strong></td>
            <td>
              {% if h.extended_by_role == 'owner' %}<span class="creator-badge owner"><i class="fas fa-crown"></i> OWNER</span>
              {% elif h.extended_by_role == 'agent' %}<span class="creator-badge agent"><i class="fas fa-user-tie"></i> AGENT</span>
              {% else %}<small style="color:var(--muted);">—</small>{% endif %}
            </td>
            <td><small style="color:var(--muted);">{{ h.created_at[:16] if h.created_at else '—' }}</small></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endif %}

  {% if not user.is_agent and not user.is_admin %}
  <div class="card">
    <div class="card-title"><i class="fas fa-cog"></i> Bot Controls</div>
    <div class="flex" style="gap:10px;">
      {% if user.bot_disabled_by_admin %}
      <form method="POST" action="/owner/toggle_user_bot/{{ user.id }}"><button type="submit" class="btn btn-success"><i class="fas fa-play"></i> Enable Bot</button></form>
      {% else %}
      <form method="POST" action="/owner/disable_user/{{ user.id }}"><button type="submit" class="btn btn-warning" onclick="return confirm('Disable this bot?');"><i class="fas fa-hand-paper"></i> Disable Bot</button></form>
      {% endif %}
      <form method="POST" action="/owner/force_start_bot/{{ user.id }}"><button type="submit" class="btn btn-gold"><i class="fas fa-bolt"></i> Force Start (Auto-recreate if missing)</button></form>
      <form method="POST" action="/owner/recreate_bot/{{ user.id }}"><button type="submit" class="btn btn-gold"><i class="fas fa-plus-circle"></i> Recreate Bot File</button></form>
    </div>
  </div>
  {% endif %}

  {% if user.is_agent %}
  <div class="card">
    <div class="card-title"><i class="fas fa-key"></i> Key Limit</div>
    <form method="POST" action="/owner/set_key_limit/{{ user.id }}" class="flex">
      <label style="color:var(--gold2);font-weight:600;">Key Limit (-1=∞):</label>
      <input type="number" name="key_limit" value="{{ user.key_limit }}" min="-1" style="width:140px;"/>
      <button type="submit" class="btn btn-gold btn-sm"><i class="fas fa-save"></i> Save</button>
    </form>
  </div>
  {% endif %}

  <a href="/owner/dashboard" class="back-link"><i class="fas fa-arrow-left"></i> Back</a>
</div>

<script>
function copyT(t){navigator.clipboard.writeText(t).then(function(){alert('Copied!');}).catch(function(){var x=document.createElement('textarea');x.value=t;document.body.appendChild(x);x.select();document.execCommand('copy');x.remove();alert('Copied!');});}
</script>
</body></html>'''


# ============================================================
#  FILE MANAGER
# ============================================================
FILE_MANAGER_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>File Manager - OWNER</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''
.modal-box.fullscreen{max-width:96vw !important;width:96vw;height:94vh;max-height:94vh}
.modal-box.fullscreen #editContent{height:calc(94vh - 200px) !important}
.fs-btn{position:absolute;top:12px;right:60px;background:rgba(59,140,255,.15);border:1px solid rgba(59,140,255,.35);color:#6db2ff;width:34px;height:34px;border-radius:8px;cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center}
</style></head><body>
<div class="container">
  <div class="card header">
    <h1><i class="fas fa-folder-open"></i> File Manager</h1>
    <div class="flex">
      <a href="/owner/dashboard" class="btn btn-primary btn-sm"><i class="fas fa-th-large"></i> Dashboard</a>
      <a href="/owner/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>
  </div>
  <div class="card">
    <div class="card-title"><i class="fas fa-upload"></i> Upload Files (Multiple • ZIP auto-extracted)</div>
    <form method="POST" action="/owner/upload_file" enctype="multipart/form-data" class="upload-form" id="uploadForm">
      <input type="hidden" name="current_path" value="{{ current_path if current_path != '/' else '' }}"/>
      <input type="file" name="uploaded_file" multiple required style="flex:1;min-width:200px;"/>
      <button type="submit" class="btn btn-gold" id="uploadBtn"><i class="fas fa-cloud-upload-alt"></i> Upload All</button>
    </form>
    <p style="color:var(--muted);font-size:.8rem;margin-top:8px;">Select multiple files at once. ZIP files are extracted automatically into the current folder.</p>
    {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
  </div>
  <div class="card">
    <div class="card-title"><i class="fas fa-folder"></i> Directory: <span class="current-dir">{{ current_path }}</span></div>
    <div class="breadcrumb"><a href="/owner/files">/</a>{% for part in breadcrumb_parts %} / <a href="/owner/files/{{ part }}">{{ part }}</a>{% endfor %}</div>
    <div class="table-wrapper">
      <table>
        <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th style="text-align:right;">Actions</th></tr></thead>
        <tbody>
          {% if parent_dir is not none %}<tr><td><a href="/owner/files/{{ parent_dir }}" class="folder-link"><i class="fas fa-arrow-up"></i> ..</a></td><td>—</td><td>—</td><td>—</td></tr>{% endif %}
          {% for item in files %}
          <tr>
            <td>{% if item.is_dir %}<a href="/owner/files/{{ item.path }}" class="folder-link"><i class="fas fa-folder"></i> {{ item.name }}</a>{% else %}<span class="file-name"><i class="fas fa-file"></i> {{ item.name }}</span>{% endif %}</td>
            <td>{{ item.size if not item.is_dir else '—' }}</td>
            <td>{{ item.modified }}</td>
            <td><div class="td-actions">{% if not item.is_dir %}<a href="/owner/download/{{ item.path }}" class="btn btn-info btn-sm"><i class="fas fa-download"></i></a><button onclick="editFile('{{ item.path }}')" class="btn btn-warning btn-sm"><i class="fas fa-edit"></i></button><button onclick="deleteFile('{{ item.path }}', this)" class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></button>{% endif %}</div></td>
          </tr>
          {% else %}<tr class="empty-row"><td colspan="4">Empty</td></tr>{% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
<div id="editModal" class="modal-overlay">
  <div class="modal-box" id="editModalBox" style="max-width:820px;">
    <button class="modal-close" onclick="closeEditModal()">&times;</button>
    <button class="fs-btn" onclick="toggleFullscreen()" id="fsBtn" title="Fullscreen"><i class="fas fa-expand"></i></button>
    <div class="modal-title"><i class="fas fa-pen-fancy"></i> Edit: <span id="editFileName" style="color:var(--gold2);font-size:1rem;"></span></div>
    <textarea id="editContent" spellcheck="false" style="width:100%;height:380px;background:#05050c;color:var(--text);border:1px solid rgba(245,200,66,.12);border-radius:12px;padding:14px;font-family:var(--mono);font-size:.85rem;resize:vertical;"></textarea>
    <div class="flex" style="justify-content:flex-end;margin-top:14px;">
      <button onclick="saveEdit()" class="btn btn-success btn-sm"><i class="fas fa-save"></i> Save</button>
      <button onclick="closeEditModal()" class="btn btn-clear btn-sm"><i class="fas fa-times"></i> Cancel</button>
    </div>
    <div id="editStatus" style="margin-top:10px;text-align:center;font-size:.85rem;color:var(--gold2);"></div>
  </div>
</div>
<script>
document.getElementById('uploadForm').addEventListener('submit',function(){var b=document.getElementById('uploadBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span> Uploading...';if(window.mahirSpeak)window.mahirSpeak('ফাইল আপলোড শুরু হয়েছে');});
var currentEditPath='';
function editFile(path){currentEditPath=path;document.getElementById('editFileName').textContent=path;document.getElementById('editContent').value='Loading...';document.getElementById('editStatus').textContent='';document.getElementById('editModal').classList.add('active');fetch('/owner/edit_file/'+encodeURIComponent(path)).then(function(r){return r.json();}).then(function(data){document.getElementById('editContent').value=data.error?('Error: '+data.error):data.content;});}
function closeEditModal(){document.getElementById('editModal').classList.remove('active');var box=document.getElementById('editModalBox');if(box)box.classList.remove('fullscreen');var fs=document.getElementById('fsBtn');if(fs)fs.innerHTML='<i class="fas fa-expand"></i>';}
function toggleFullscreen(){var box=document.getElementById('editModalBox');var btn=document.getElementById('fsBtn');box.classList.toggle('fullscreen');btn.innerHTML=box.classList.contains('fullscreen')?'<i class="fas fa-compress"></i>':'<i class="fas fa-expand"></i>';}
function saveEdit(){var c=document.getElementById('editContent').value;var s=document.getElementById('editStatus');s.textContent='Saving...';if(window.mahirSpeak)window.mahirSpeak('ফাইল সেভ হচ্ছে');fetch('/owner/edit_file/'+encodeURIComponent(currentEditPath),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:c})}).then(function(r){return r.json();}).then(function(data){if(data.success){s.textContent='Saved!';s.style.color='#4ade80';if(window.mahirSpeak)window.mahirSpeak('ফাইল সেভ হয়েছে');setTimeout(function(){location.reload();},800);}else{s.textContent='Error: '+(data.error||'');s.style.color='#ff5a76';if(window.mahirSpeak)window.mahirSpeak('সেভ ব্যর্থ হয়েছে');}});}
function deleteFile(path,btn){if(!confirm('Delete?'))return;if(btn)btn.disabled=true;if(window.mahirSpeak)window.mahirSpeak('ফাইল ডিলিট হচ্ছে');fetch('/owner/delete_file/'+encodeURIComponent(path),{method:'POST'}).then(function(r){return r.json();}).then(function(data){if(data.success){if(window.mahirSpeak)window.mahirSpeak('ফাইল ডিলিট হয়েছে');location.reload();}else{alert('Error');if(window.mahirSpeak)window.mahirSpeak('ডিলিট ব্যর্থ হয়েছে');if(btn)btn.disabled=false;}});}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var box=document.getElementById('editModalBox');if(box && box.classList.contains('fullscreen')){toggleFullscreen();return;}closeEditModal();}});
</script>
''' + VOICE_HELPER_JS + '''
</body></html>'''


# ============================================================
#  USER PANEL
# ============================================================
USER_PANEL_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/><title>MAHIR PREMIUM | Bot Controller</title><link rel="preconnect" href="https://fonts.googleapis.com"/><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/><style>''' + COMMON_CSS + '''
/* Padding bottom so fixed bar doesn't cover content */
.container{padding-bottom: 100px !important;}

.logout-btn{position:fixed;top:20px;right:20px;z-index:999}
.cover-section{position:relative;border-radius:22px;overflow:hidden;margin-bottom:24px;border:1px solid rgba(245,200,66,.15)}
.cover-section img.cover-image{width:100%;height:260px;object-fit:cover;display:block}
.cover-overlay{position:absolute;inset:0;background:linear-gradient(100deg,rgba(7,7,15,.92) 20%,rgba(7,7,15,.5) 60%,rgba(7,7,15,.25));display:flex;flex-direction:column;justify-content:center;padding:32px 40px}
.logo-row{display:flex;align-items:center;gap:18px}
.logo-row img{height:72px;width:72px;border-radius:16px;object-fit:cover;border:1px solid rgba(245,200,66,.25)}
.cover-title{font-size:2.2rem;font-weight:800;background:linear-gradient(120deg,#F5C842,#FFE28A 35%,#B388FF 70%,#3B8CFF);-webkit-background-clip:text;background-clip:text;color:transparent;line-height:1.1}
.cover-sub{color:rgba(233,233,248,.65);font-size:.85rem;letter-spacing:1.5px;margin-top:4px}
.cover-badge{position:absolute;top:18px;right:20px;background:rgba(7,7,15,.7);border:1px solid rgba(245,200,66,.25);padding:6px 16px;border-radius:999px;font-size:.66rem;font-weight:700;color:var(--gold);letter-spacing:2px;text-transform:uppercase}
.download-card{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.dc-left{display:flex;align-items:center;gap:16px}
.dc-icon{font-size:2rem;color:var(--gold);background:rgba(245,200,66,.07);width:60px;height:60px;border-radius:16px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(245,200,66,.12)}
.dc-title{font-size:1.05rem;font-weight:700}
.dc-desc{color:var(--muted);font-size:.8rem;margin:2px 0 6px}
.version-tag{display:inline-block;background:rgba(245,200,66,.08);color:var(--gold);padding:2px 10px;border-radius:999px;font-size:.62rem;font-weight:700;margin-right:6px;border:1px solid rgba(245,200,66,.12)}
.tab-container{display:flex;gap:8px;margin-bottom:14px;border-bottom:1px solid rgba(245,200,66,.08);padding-bottom:10px;flex-wrap:wrap}
.tab-btn{background:transparent;border:1px solid transparent;padding:8px 18px;border-radius:10px;color:var(--muted);cursor:pointer;font-weight:600;font-size:.82rem;font-family:inherit}
.tab-btn.active{background:rgba(245,200,66,.08);color:var(--gold);border-color:rgba(245,200,66,.25)}
.tab-content{display:none}.tab-content.active{display:block}

/* LOG BOX & FULLSCREEN STYLES */
.log-box{background:#05050c;border:1px solid rgba(245,200,66,.08);border-radius:14px;padding:14px;height:400px;overflow-y:auto;font-family:var(--mono);font-size:.78rem;transition:all .3s ease}
.log-box.fullscreen{position:fixed;top:0;left:0;right:0;bottom:0;z-index:999999;height:100vh !important;width:100vw !important;border-radius:0;padding:60px 20px 20px 20px;background:#05050c;margin:0}
.fs-controls{display:none;position:fixed;top:15px;right:15px;z-index:1000000;gap:10px;align-items:center}
.fs-controls button{border:1px solid rgba(255,255,255,0.2);padding:10px 18px;border-radius:10px;font-family:inherit;font-weight:700;font-size:0.85rem;cursor:pointer;box-shadow:0 5px 15px rgba(0,0,0,0.5);display:flex;align-items:center;gap:8px}
.fs-btn-pause{background:linear-gradient(135deg,#F5C842,#C99A1A);color:#0a0a14}
.fs-btn-exit{background:linear-gradient(135deg,#D42A3A,#8A1A28);color:#fff}
.log-line{padding:4px 8px;border-left:3px solid var(--gold);margin-bottom:2px;color:#c5c5e5;word-wrap:break-word;white-space:pre-wrap}
.error-line{border-left-color:var(--red);color:#fca5a5;background:rgba(212,42,58,.05)}
.message-card{background:rgba(245,200,66,.03);border:1px solid rgba(245,200,66,.08);border-radius:12px;padding:12px 14px;margin-bottom:10px;display:flex;gap:12px;align-items:flex-start}
.message-pfp{width:48px;height:48px;border-radius:50%;object-fit:cover;border:2px solid rgba(245,200,66,.3);flex-shrink:0;background:rgba(0,0,0,.4)}
.message-body{flex:1;min-width:0}
.message-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid rgba(245,200,66,.06)}
.message-sender{font-weight:800;color:var(--gold2)}
.message-time{font-size:.65rem;color:var(--muted)}
.message-meta{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:.8rem}
.message-label{color:var(--gold2);font-weight:600}
.message-value{color:#c5c5e5;word-break:break-all}
.fullscreen-btn{background:rgba(255,255,255,.06);border:1px solid rgba(245,200,66,.15);padding:7px 14px;border-radius:10px;color:var(--text);cursor:pointer;font-size:.78rem;font-family:inherit}
.fullscreen-btn:hover{background:rgba(245,200,66,.1);color:var(--gold)}
.control-bar{display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap}
.pause-btn{background:rgba(255,255,255,.06);border:1px solid rgba(245,200,66,.15);padding:7px 14px;border-radius:10px;color:var(--text);cursor:pointer;font-size:.78rem;font-family:inherit}
.chart-container{position:relative;height:250px}
.config-form{max-width:560px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.config-status{padding:13px 16px;background:rgba(245,200,66,.05);border:1px solid rgba(245,200,66,.12);border-left:4px solid var(--gold);border-radius:10px;color:var(--gold2);font-size:.85rem;margin-bottom:18px}
.subscription-hero{background:linear-gradient(135deg,rgba(15,10,30,.95),rgba(10,5,20,.95));border:1px solid rgba(245,200,66,.2);border-radius:20px;padding:22px;margin-bottom:20px;box-shadow:0 15px 40px rgba(0,0,0,.4)}
.sub-hero-title{font-size:.85rem;font-weight:700;color:var(--gold);text-transform:uppercase;letter-spacing:2px;margin-bottom:16px;display:flex;align-items:center;gap:10px}
.sub-hero-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.sub-hero-item{background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.08);border-radius:14px;padding:16px;text-align:center}
.sub-hero-label{font-size:.62rem;text-transform:uppercase;letter-spacing:2px;color:var(--gold2);font-weight:700;margin-bottom:8px}
.sub-hero-value{font-size:1.4rem;font-weight:800;color:#fff;word-break:break-word;line-height:1.2}
.sub-hero-value.small{font-size:1rem}
.sub-hero-value.green{color:#4ade80}
.sub-hero-value.red{color:#ff5a76}
.sub-hero-value.gold{color:#F5C842}

.fixed-control-bar{position:fixed;bottom:0;left:0;width:100%;background:rgba(10,10,20,0.95);backdrop-filter:blur(12px);border-top:1px solid rgba(245,200,66,0.25);padding:12px 15px;display:flex;justify-content:center;gap:10px;z-index:9999;box-shadow:0 -10px 30px rgba(0,0,0,0.6)}
.fixed-control-bar .btn{flex:1;max-width:130px;padding:12px 10px;font-size:0.8rem;border-radius:12px;display:flex;align-items:center;justify-content:center;gap:6px;font-weight:700;white-space:nowrap}
.fixed-control-bar .btn i{font-size:0.95rem}

@media(max-width:768px){
  .download-card{flex-direction:column}
  .chart-container{height:190px}
  .sub-hero-value{font-size:1.1rem}
  .cover-overlay{padding:20px}
  .cover-title{font-size:1.6rem}
  .logo-row img{height:50px;width:50px}
  .fixed-control-bar{padding:8px;gap:6px;}
  .fixed-control-bar .btn{font-size:0.68rem;padding:10px 4px;gap:3px;}
  .fixed-control-bar .btn i{font-size:0.85rem;}
  .notice-links-grid{grid-template-columns:repeat(2,1fr);}
  .notice-links-grid a{font-size:0.75rem;padding:8px;}
}

.notice-links-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;max-height:140px;overflow-y:auto;padding-right:4px;margin-top:10px}
.notice-links-grid::-webkit-scrollbar{width:4px}
.notice-links-grid::-webkit-scrollbar-thumb{background:rgba(245,200,66,.3);border-radius:4px}
.notice-links-grid a{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);padding:8px 10px;border-radius:8px;color:#fff;text-decoration:none;text-align:center;font-size:0.8rem;display:flex;align-items:center;justify-content:center;gap:6px;transition:0.2s}
.notice-links-grid a:hover{background:rgba(245,200,66,0.15);border-color:rgba(245,200,66,0.3);color:var(--gold)}

/* LIVE MONITOR STYLES */
.live-monitor-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:99999;justify-content:center;align-items:center;backdrop-filter:blur(8px);padding:16px}
.live-monitor-overlay.active{display:flex}
.live-monitor-box{background:#0a0a0f;border:1px solid rgba(139,92,246,0.4);border-radius:20px;width:100%;max-width:420px;padding:24px;box-shadow:0 0 40px rgba(139,92,246,0.2);position:relative;overflow:hidden;animation:slideUp .3s ease}
.live-monitor-header{font-size:0.9rem;font-weight:800;color:#c4b5fd;text-transform:uppercase;letter-spacing:1px;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.pulse-dot{width:10px;height:10px;background:#4ade80;border-radius:50%;box-shadow:0 0 10px #4ade80;animation:pulse-green 1.5s infinite}
@keyframes pulse-green{0%{box-shadow:0 0 0 0 rgba(74,222,128,0.7)}70%{box-shadow:0 0 0 10px rgba(74,222,128,0)}100%{box-shadow:0 0 0 0 rgba(74,222,128,0)}}
.lm-steps{display:flex;flex-direction:column;gap:14px;margin-bottom:24px}
.lm-step{display:flex;align-items:center;gap:14px;font-size:0.88rem;color:#888;transition:all 0.3s}
.lm-step.active{color:#fff;font-weight:600}
.lm-step.completed{color:#a78bfa}
.lm-icon{width:28px;height:28px;border-radius:50%;background:rgba(255,255,255,0.05);display:flex;justify-content:center;align-items:center;font-size:0.75rem;flex-shrink:0;transition:all 0.3s}
.lm-step.active .lm-icon{background:rgba(139,92,246,0.2);border:2px solid #8b5cf6;color:#8b5cf6}
.lm-step.active .lm-icon i{animation:spin 1s linear infinite}
.lm-step.completed .lm-icon{background:rgba(167,139,250,0.15);color:#a78bfa}
.lm-progress-container{width:100%;height:6px;background:rgba(255,255,255,0.08);border-radius:10px;overflow:hidden;position:relative;margin-bottom:10px}
.lm-progress-bar{height:100%;width:0%;background:linear-gradient(90deg,#ec4899,#8b5cf6);border-radius:10px;transition:width 0.4s ease}
.lm-percentage{text-align:right;font-size:0.75rem;color:#888;font-weight:600}
</style></head><body>

<div class="notice-indicator" id="noticeBtn" onclick="showNotice()" style="display:none;"><i class="fas fa-bullhorn"></i> Owner Notice</div>

<!-- GLOBAL NOTICE MODAL -->
<div class="notice-overlay" id="noticePopup">
  <div class="notice-box">
    <button class="modal-close" onclick="hideNotice()">&times;</button>
    <span class="notice-icon" id="noticeIcon">📢</span>
    <div class="notice-title" id="noticeTitle">OWNER NOTICE</div>
    <div class="notice-msg" id="noticeMsg"></div>
    <div class="notice-contact-title">Contact Owner</div>
    <div class="notice-links-grid">
      {% for link in custom_links %}
      <a href="{{ link.url }}" target="_blank"><i class="{{ link.icon }}"></i> {{ link.name }}</a>
      {% endfor %}
    </div>
  </div>
</div>

<!-- LOGIN NOTICE MODAL -->
<div class="notice-overlay" id="loginNoticePopup">
  <div class="notice-box" style="border-color:rgba(59,140,255,.5);">
    <button class="modal-close" onclick="document.getElementById('loginNoticePopup').classList.remove('show')">&times;</button>
    <span class="notice-icon" id="loginNoticeIcon">🔔</span>
    <div class="notice-title" id="loginNoticeTitle" style="background:linear-gradient(120deg,#3B8CFF,#00d9f5,#F5C842);-webkit-background-clip:text;background-clip:text;color:transparent;">IMPORTANT NOTICE</div>
    <div class="notice-msg" id="loginNoticeMsg"></div>
    <div class="notice-contact-title">Contact Owner</div>
    <div class="notice-links-grid">
      {% for link in custom_links %}
      <a href="{{ link.url }}" target="_blank"><i class="{{ link.icon }}"></i> {{ link.name }}</a>
      {% endfor %}
    </div>
  </div>
</div>

<!-- LIVE MONITOR OVERLAY -->
<div id="liveMonitorOverlay" class="live-monitor-overlay">
    <div class="live-monitor-box">
        <div class="live-monitor-header"><span class="pulse-dot"></span> LIVE MONITOR — Generating Accounts</div>
        <div class="lm-steps">
            <div class="lm-step" data-step="1"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Connecting to Garena servers</span></div>
            <div class="lm-step" data-step="2"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Registering guest accounts</span></div>
            <div class="lm-step" data-step="3"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Granting OAuth tokens</span></div>
            <div class="lm-step" data-step="4"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Major Register & Login</span></div>
            <div class="lm-step" data-step="5"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Setting region & bio</span></div>
            <div class="lm-step" data-step="6"><div class="lm-icon"><i class="fas fa-circle-notch"></i></div><span>Finalizing all accounts</span></div>
        </div>
        <div class="lm-progress-container"><div class="lm-progress-bar" id="lmProgressBar"></div></div>
        <div class="lm-percentage" id="lmPercentage">0%</div>
    </div>
</div>

<div class="container">
  {% if owner_mode %}
  <a href="/owner/return" class="btn btn-gold btn-sm" style="position:absolute;top:16px;right:100px;z-index:50;font-weight:700;"><i class="fas fa-crown"></i> Return to Owner</a>
  {% endif %}
  <button class="logout-btn btn btn-danger btn-sm" onclick="window.location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Logout</button>
  
  <div class="cover-section">
    <img class="cover-image" src="{{ cover_url }}" alt="Cover"/>
    <div class="cover-overlay">
      <div class="logo-row">
        <img src="{{ logo_url }}" alt="MAHIR"/>
        <div><div class="cover-title">MAHIR PREMIUM</div><div class="cover-sub">ELITE BOT CONTROLLER</div></div>
      </div>
      <div class="cover-badge"><i class="fas fa-crown"></i> {{ 'PREMIUM' if config_done else 'SETUP' }}</div>
    </div>
  </div>

  {% if sub_status == 'active' and sub_days <= 3 %}
  <div class="card" style="background:rgba(212,42,58,.1);border-color:rgba(212,42,58,.35);">
    <div style="color:var(--red2);font-weight:700;"><i class="fas fa-exclamation-triangle"></i> আপনার সাবস্ক্রিপশন {{ sub_days }} দিনের মধ্যে শেষ! এখনই renew করুন।</div>
  </div>
  {% endif %}

  {% if sub_status != 'expired' %}
  <div class="subscription-hero">
    <div class="sub-hero-title"><i class="fas fa-clock" style="color:#F5C842;"></i> Your Subscription Status</div>
    <div class="sub-hero-grid">
      <div class="sub-hero-item"><div class="sub-hero-label">Status</div><div class="sub-hero-value small {% if sub_status == 'unlimited' %}green{% elif sub_status == 'expired' %}red{% else %}green{% endif %}">{% if sub_status == 'unlimited' %}∞ UNLIMITED{% elif sub_status == 'expired' %}EXPIRED{% else %}ACTIVE{% endif %}</div></div>
      <div class="sub-hero-item"><div class="sub-hero-label">Days Left</div><div class="sub-hero-value {% if sub_days <= 3 %}red{% elif sub_days <= 7 %}gold{% else %}green{% endif %}">{% if sub_status == 'unlimited' %}∞{% else %}{{ sub_days }}{% endif %}</div></div>
      <div class="sub-hero-item"><div class="sub-hero-label">Time Remaining</div><div class="sub-hero-value small gold">{{ sub_time_left }}</div></div>
      <div class="sub-hero-item"><div class="sub-hero-label">Expires On</div><div class="sub-hero-value small" style="font-size:.85rem;">{{ sub_expiry_display }}</div></div>
      {% if renew_count > 0 %}<div class="sub-hero-item"><div class="sub-hero-label">Total Renewals</div><div class="sub-hero-value small gold">{{ renew_count }}x (+{{ renew_days }}d)</div></div>{% endif %}
    </div>
  </div>
  {% endif %}

  {% if not config_done %}
  <div class="card anim-card">
    <div class="card-title"><i class="fas fa-cog"></i> Bot Configuration</div>
    {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="alert {{ category }}"><i class="fas fa-{% if category == 'error' %}exclamation-circle{% else %}check-circle{% endif %}"></i> {{ message }}</div>{% endfor %}{% endif %}{% endwith %}
    <div class="config-status"><i class="fas fa-info-circle"></i> Manual credentials অথবা Auto Create দিয়ে deploy করুন।</div>
    <div class="deploy-mode-tabs" style="display:flex;gap:8px;margin-bottom:16px;">
      <button type="button" class="btn btn-sm deploy-tab active" data-mode="manual" onclick="switchDeployMode('manual')" style="flex:1;"><i class="fas fa-keyboard"></i> Manual</button>
      <button type="button" class="btn btn-sm deploy-tab" data-mode="auto" onclick="switchDeployMode('auto')" style="flex:1;background:linear-gradient(135deg,#8b5cf6,#ec4899);border:none;"><i class="fas fa-magic"></i> Auto Create</button>
    </div>
    <form method="POST" action="/configure" class="config-form" id="configForm" onsubmit="return onDeploySubmit()">
      <input type="hidden" name="deploy_mode" id="deploy_mode" value="manual"/>

      <!-- ✅ AUTO MODE: Bot Name comes FIRST -->
      <div id="field-bot-name" style="display:none;">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Bot Name (prefix)</label>
        <input type="text" name="bot_name" placeholder="e.g. MAHIR_TCP" value="{{ session.get('username','MAHIR') }}"/>
      </div>

      <!-- ✅ Admin UID (always shown) -->
      <div id="field-admin-uid">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Admin UID</label>
        <input type="text" name="admin_uid" placeholder="e.g. 1120167200" required/>
      </div>

      <!-- ✅ AUTO MODE: Guild ID -->
      <div id="field-guild-id" style="display:none;">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Guild ID</label>
        <input type="text" name="guild_id" placeholder="e.g. 3087207343 (optional)"/>
      </div>

      <!-- ✅ AUTO MODE: Server / Region -->
      <div id="field-region" style="display:none;">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Server / Region</label>
        <select name="region" style="width:100%;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);">
          <option value="BD">BD — Bangladesh</option>
          <option value="IND">IND — India</option>
          <option value="PK">PK — Pakistan</option>
        </select>
      </div>

      <!-- ✅ MANUAL MODE: Bot UID -->
      <div id="field-bot-uid">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Bot UID</label>
        <input type="text" name="bot_uid" id="bot_uid_input" placeholder="Bot UID"/>
      </div>

      <!-- ✅ MANUAL MODE: Bot Password -->
      <div id="field-bot-pw">
        <label style="color:var(--gold2);font-weight:600;margin-bottom:6px;display:block;">Bot Password</label>
        <input type="text" name="bot_pw" id="bot_pw_input" placeholder="Password"/>
      </div>

      <!-- ✅ AUTO MODE: Status hint -->
      <div id="field-auto-status" style="display:none;" class="config-status">
        <i class="fas fa-bolt"></i> Auto: Account create → Bio → Guild request → Bot file → Start
      </div>

      <button type="submit" class="btn btn-gold btn-block" id="deployBtn"><i class="fas fa-play"></i> Deploy Bot</button>
    </form>
  </div>

  <script>
  function switchDeployMode(m){
    var mode = (m || 'manual').toLowerCase();
    document.getElementById('deploy_mode').value = mode;

    /* show/hide each field based on mode */
    var show = function(id, visible){
      var el = document.getElementById(id);
      if(el) el.style.display = visible ? 'block' : 'none';
    };

    if(mode === 'auto'){
      show('field-bot-name', true);
      show('field-admin-uid', true);
      show('field-guild-id', true);
      show('field-region', true);
      show('field-auto-status', true);
      show('field-bot-uid', false);
      show('field-bot-pw', false);
    } else {
      show('field-bot-name', false);
      show('field-admin-uid', true);
      show('field-guild-id', false);
      show('field-region', false);
      show('field-auto-status', false);
      show('field-bot-uid', true);
      show('field-bot-pw', true);
    }

    /* required attributes */
    var uidEl = document.getElementById('bot_uid_input');
    var pwEl  = document.getElementById('bot_pw_input');
    if(uidEl) uidEl.required = (mode === 'manual');
    if(pwEl)  pwEl.required  = (mode === 'manual');

    document.querySelectorAll('.deploy-tab').forEach(function(b){
      b.classList.toggle('active', b.dataset.mode === mode);
    });
  }

  function onDeploySubmit(){
    var m = document.getElementById('deploy_mode').value;
    var form = document.getElementById('configForm');
    if(m === 'auto'){
      startLiveMonitor(form);
      return false;
    }
    return true;
  }

  function startLiveMonitor(form) {
    var overlay = document.getElementById('liveMonitorOverlay');
    var steps = document.querySelectorAll('.lm-step');
    var progressBar = document.getElementById('lmProgressBar');
    var percentage = document.getElementById('lmPercentage');

    overlay.classList.add('active');
    var currentStep = 0;
    var totalSteps = steps.length;

    steps.forEach(function(s, i){
      s.classList.remove('active','completed');
      s.querySelector('i').className = 'fas fa-circle-notch';
    });

    steps[0].classList.add('active');
    steps[0].querySelector('i').className = 'fas fa-spinner';
    progressBar.style.width = '5%';
    percentage.innerText = '5%';

    var stepInterval = setInterval(function() {
      if (currentStep < totalSteps - 1) {
        steps[currentStep].classList.remove('active');
        steps[currentStep].classList.add('completed');
        steps[currentStep].querySelector('i').className = 'fas fa-check';
        currentStep++;
        steps[currentStep].classList.add('active');
        steps[currentStep].querySelector('i').className = 'fas fa-spinner';
        var pct = Math.floor(((currentStep + 1) / totalSteps) * 90);
        progressBar.style.width = pct + '%';
        percentage.innerText = pct + '%';
      }
    }, 4500);

    var formData = new FormData(form);
    fetch('/configure', { method: 'POST', body: formData,
        headers: { 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' } })
    .then(function(response){
      clearInterval(stepInterval);
      steps.forEach(function(step){
        step.classList.remove('active');
        step.classList.add('completed');
        step.querySelector('i').className = 'fas fa-check';
      });
      progressBar.style.width = '100%';
      percentage.innerText = '100%';
      setTimeout(function(){ window.location.href = '/dashboard'; }, 1000);
    })
    .catch(function(error){
      clearInterval(stepInterval);
      alert('Error occurred during deployment. Please check logs.');
      overlay.classList.remove('active');
    });
  }
  </script>
  {% else %}

  <!-- Download Card -->
  <div class="card download-card">
    <div class="dc-left">
      <div class="dc-icon"><i class="fab fa-android"></i></div>
      <div>
        <div class="dc-title"><i class="fas fa-mobile-alt" style="color:var(--gold);margin-right:6px;"></i> MAHIR TCP Bot</div>
        <div class="dc-desc">Download the official Android app</div>
        <span class="version-tag"><i class="fas fa-tag"></i> v2.0.1</span>
      </div>
    </div>
    <a href="{{ app_download_link }}" target="_blank" class="btn btn-gold"><i class="fas fa-download"></i> Download APK</a>
  </div>

  <div class="card">
    <div class="card-title"><i class="fas fa-robot"></i> Bot Identity & Status</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">UID</div><div class="stat-value" id="botUid">---</div></div>
      <div class="stat-card"><div class="stat-label">Name</div><div class="stat-value" id="botName">---</div></div>
      <div class="stat-card"><div class="stat-label">Region</div><div class="stat-value" id="botRegion">---</div></div>
      <div class="stat-card"><div class="stat-label">Clan ID</div><div class="stat-value" id="botClanId">---</div></div>
      <div class="stat-card"><div class="stat-label">Status</div><div class="stat-value" id="botStatus">---</div></div>
      <div class="stat-card"><div class="stat-label">Online Server</div><div class="stat-value" id="botServer" style="font-size:.82rem;">---</div></div>
      <div class="stat-card"><div class="stat-label">Chat Server</div><div class="stat-value" id="botChatServer" style="font-size:.82rem;">---</div></div>
      <div class="stat-card"><div class="stat-label">BY</div><div class="stat-value" id="botBy">---</div></div>
      <div class="stat-card"><div class="stat-label">Created By</div><div class="stat-value" id="botCreatedBy">{{ creator_display|safe }}</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title"><i class="fas fa-chart-line"></i> System Performance</div>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Process</div><div class="stat-value" id="processStatus">---</div></div>
      <div class="stat-card"><div class="stat-label">Uptime</div><div class="stat-value" id="uptime">00:00:00</div></div>
      <div class="stat-card"><div class="stat-label">Restarts</div><div class="stat-value" id="restartCount">0</div></div>
      <div class="stat-card"><div class="stat-label">Errors</div><div class="stat-value" id="errorCount" style="color:var(--red2);">0</div></div>
    </div>
    <div class="system-stats">
      <div class="stat-card"><div class="stat-label">CPU</div><div class="stat-value" id="cpuValue">0%</div><div class="progress-bar"><div class="progress-fill" id="cpuBar"></div></div></div>
      <div class="stat-card"><div class="stat-label">RAM</div><div class="stat-value" id="ramValue">0%</div><div class="progress-bar"><div class="progress-fill" id="ramBar"></div></div></div>
      <div class="stat-card"><div class="stat-label">Disk</div><div class="stat-value" id="diskValue">0%</div><div class="progress-bar"><div class="progress-fill" id="diskBar"></div></div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title"><i class="fas fa-chart-area"></i> Performance Monitor</div>
    <div class="chart-container"><canvas id="performanceChart"></canvas></div>
  </div>
  <div class="card" style="margin-bottom: 0;">
    <div class="tab-container">
      <button class="tab-btn active" onclick="switchTab('logs')"><i class="fas fa-terminal"></i> Console</button>
      <button class="tab-btn" onclick="switchTab('messages')"><i class="fas fa-envelope"></i> Messages</button>
      <button class="tab-btn" onclick="switchTab('errors')"><i class="fas fa-exclamation-triangle"></i> Errors</button>
    </div>
    <div id="logsTab" class="tab-content active">
      <div class="control-bar">
        <button onclick="togglePause()" id="pauseBtn" class="pause-btn"><i class="fas fa-pause"></i> Pause</button>
        <button onclick="toggleColorMode()" id="colorModeBtn" class="pause-btn"><i class="fas fa-palette"></i> Color ON</button>
        <button onclick="toggleFullscreen('logBox')" class="fullscreen-btn" id="fsBtn"><i class="fas fa-expand"></i> Fullscreen</button>
        <button onclick="exportLogs()" class="btn btn-export btn-sm"><i class="fas fa-download"></i> Export</button>
        <span style="margin-left:auto;font-size:.72rem;color:var(--gold2);" id="logStatus">Auto-scroll: ON</span>
      </div>
      <div id="logBox" class="log-box"><div class="log-line">Waiting...</div></div>
      <div id="fsControls" class="fs-controls">
          <button id="fsPauseBtn" class="fs-btn-pause" onclick="togglePause()"><i class="fas fa-pause"></i> Pause</button>
          <button class="fs-btn-exit" onclick="toggleFullscreen('logBox')"><i class="fas fa-times"></i> Exit</button>
      </div>
    </div>
    <div id="messagesTab" class="tab-content">
      <div class="control-bar"><button onclick="clearMessages()" class="btn btn-clear btn-sm">Clear</button><button onclick="exportMessages()" class="btn btn-export btn-sm">Export</button></div>
      <div id="messageHistory" class="log-box" style="height:380px;"><div class="log-line">No messages...</div></div>
    </div>
    <div id="errorsTab" class="tab-content">
      <div class="control-bar"><button onclick="clearErrors()" class="btn btn-clear btn-sm">Clear</button><button onclick="exportErrors()" class="btn btn-export btn-sm">Export</button></div>
      <div id="errorBox" class="log-box"><div class="log-line">No errors</div></div>
    </div>
  </div>
  {% endif %}
</div>

{% if config_done %}
<div class="fixed-control-bar">
  <button onclick="sendAction('start')" id="btnStart" class="btn btn-start"><i class="fas fa-play"></i> Start</button>
  <button onclick="sendAction('stop')" id="btnStop" class="btn btn-stop"><i class="fas fa-stop"></i> Stop</button>
  <button onclick="sendAction('reset')" id="btnReset" class="btn btn-reset"><i class="fas fa-sync-alt"></i> Restart</button>
  <button onclick="openRecreateModal()" class="btn btn-primary" style="background:linear-gradient(135deg,#8540F5,#5A1A9A);"><i class="fas fa-magic"></i> Recreate</button>
  <button onclick="openAdminPanel()" id="btnAdmin" class="btn btn-admin" style="background:linear-gradient(135deg,#00d9f5,#8540F5);color:#fff;"><i class="fas fa-cog"></i> Admin</button>
</div>
{% endif %}

<!-- Recreate Bot Modal -->
<div class="modal-overlay" id="recreateModal">
  <div class="modal-box" style="max-width:420px;">
    <button class="modal-close" onclick="closeRecreateModal()">&times;</button>
    <div class="modal-title"><i class="fas fa-magic" style="color:var(--purple);"></i> Recreate Bot Account</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:15px;">নতুন FF account create → bio → guild request → bot file + DB update → restart</p>
    <form method="POST" action="/user/recreate_bot" onsubmit="var ok=confirm('নতুন account create হবে এবং bot restart হবে। Continue?'); if(ok){ if(window.mahirSpeak)window.mahirSpeak('বট ফাইল রিক্রিয়েট শুরু হয়েছে'); this.querySelector('button').disabled=true; document.getElementById('recreate-overlay').style.display='block'; } return ok;">
      <div style="margin-bottom:12px;">
        <label style="color:var(--gold2);font-weight:600;display:block;margin-bottom:6px;font-size:.85rem;">Bot Name Prefix</label>
        <input type="text" name="bot_name" value="MAHIR_TCP" placeholder="MAHIR_TCP" style="width:100%;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);"/>
      </div>
      <div style="margin-bottom:12px;">
        <label style="color:var(--gold2);font-weight:600;display:block;margin-bottom:6px;font-size:.85rem;">Guild ID (Optional)</label>
        <input type="text" name="guild_id" placeholder="e.g., 3087207343" style="width:100%;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);"/>
      </div>
      <div style="margin-bottom:20px;">
        <label style="color:var(--gold2);font-weight:600;display:block;margin-bottom:6px;font-size:.85rem;">Server / Region</label>
        <select name="region" style="width:100%;padding:10px;border-radius:8px;background:#0a0a0f;color:#fff;border:1px solid rgba(245,200,66,.3);">
          <option value="BD">BD — Bangladesh</option>
          <option value="IND">IND — India</option>
          <option value="PK">PK — Pakistan</option>
          <option value="ID">ID — Indonesia</option>
          <option value="VN">VN — Vietnam</option>
          <option value="TH">TH — Thailand</option>
          <option value="SG">SG — Singapore</option>
          <option value="BR">BR — Brazil</option>
          <option value="NA">NA — North America</option>
          <option value="US">US — United States</option>
        </select>
      </div>
      <button type="submit" class="btn btn-gold btn-block" style="padding:12px;"><i class="fas fa-check"></i> Confirm & Recreate</button>
    </form>
    <div id="recreate-overlay" style="display:none;margin-top:16px;padding:16px;border-radius:12px;background:rgba(139,92,246,.1);border:1px solid rgba(139,92,246,.4);text-align:center;">
      <div style="width:30px;height:30px;border:3px solid transparent;border-top-color:#8b5cf6;border-radius:50%;margin:0 auto 10px;animation:spin 1s linear infinite;"></div>
      <div style="font-weight:700;color:#c4b5fd;font-size:.85rem;">Creating account...</div>
      <div style="font-size:.75rem;color:#888;margin-top:4px;">This may take 30-90 seconds</div>
    </div>
  </div>
</div>

<div id="adminModal" class="modal-overlay">
  <div class="modal-box" style="max-width:820px;">
    <button class="modal-close" onclick="closeAdminPanel()">&times;</button>
    <div class="modal-title" style="margin-bottom:20px;"><i class="fas fa-cog"></i> Admin Control Panel</div>
    <div class="card" style="margin-bottom:16px;background:rgba(0,0,0,.35);border:1px solid rgba(245,200,66,.12);border-radius:16px;padding:16px;">
      <div class="card-title" style="margin-bottom:12px;"><i class="fas fa-robot"></i> Bot Identity (Live)</div>
      <div class="detail-grid">
        <div class="detail-item"><div class="detail-label">Bot UID</div><div class="detail-value big" id="adminLiveUid">---</div></div>
        <div class="detail-item"><div class="detail-label">Name</div><div class="detail-value" id="adminLiveName">---</div></div>
        <div class="detail-item"><div class="detail-label">Region</div><div class="detail-value" id="adminLiveRegion">---</div></div>
        <div class="detail-item"><div class="detail-label">Clan ID</div><div class="detail-value" id="adminLiveClanId">---</div></div>
        <div class="detail-item"><div class="detail-label">Status</div><div class="detail-value" id="adminLiveStatus">---</div></div>
        <div class="detail-item"><div class="detail-label">Online Server</div><div class="detail-value" id="adminLiveServer" style="font-size:.85rem;">---</div></div>
        <div class="detail-item"><div class="detail-label">Chat Server</div><div class="detail-value" id="adminLiveChat" style="font-size:.85rem;">---</div></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:16px;background:rgba(0,0,0,.35);border:1px solid rgba(245,200,66,.12);border-radius:16px;padding:16px;">
      <div class="card-title" style="margin-bottom:12px;"><i class="fas fa-user-shield"></i> Owner / Admin UIDs</div>
      <p style="color:var(--muted);font-size:.8rem;margin-bottom:10px;">Comma separated. Master UID is always kept.</p>
      <div class="modal-input-group"><label>UIDs:</label><input type="text" id="adminUidsInput" placeholder="1120167200, 3020431227" style="flex:1;"/></div>
      <button onclick="updateAdminUIDs()" id="adminUidsBtn" class="modal-btn modal-btn-save" style="margin-top:10px;"><i class="fas fa-save"></i> Save & Restart Bot</button>
    </div>
    <div class="card" style="margin-bottom:16px;background:rgba(0,0,0,.35);border:1px solid rgba(245,200,66,.12);border-radius:16px;padding:16px;">
      <div class="card-title" style="margin-bottom:12px;"><i class="fas fa-key"></i> Bot Credentials</div>
      <div class="detail-grid" style="margin-bottom:12px;">
        <div class="detail-item"><div class="detail-label">Bot UID</div><input type="text" id="botUidInput" style="width:100%;margin-top:6px;background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.2);color:#fff;padding:10px;border-radius:10px;"/></div>
        <div class="detail-item"><div class="detail-label">Password</div><input type="text" id="botPwInput" style="width:100%;margin-top:6px;background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.2);color:#fff;padding:10px;border-radius:10px;"/></div>
      </div>
      <button onclick="updateBotCreds()" id="botCredsBtn" class="modal-btn modal-btn-save"><i class="fas fa-save"></i> Save Credentials & Restart</button>
    </div>
    <div class="card" style="margin-bottom:16px;background:rgba(0,0,0,.35);border:1px solid rgba(245,200,66,.12);border-radius:16px;padding:16px;">
      <div class="card-title" style="margin-bottom:12px;"><i class="fas fa-user-friends"></i> Friend Management</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px;">
        <input type="text" id="friendUidInput" placeholder="Friend UID" style="flex:1;min-width:160px;background:rgba(0,0,0,.4);border:1px solid rgba(245,200,66,.2);color:#fff;padding:10px 12px;border-radius:10px;"/>
        <button onclick="friendAction('add')" id="friendAddBtn" class="modal-btn modal-btn-action"><i class="fas fa-user-plus"></i> Add</button>
        <button onclick="friendAction('remove')" id="friendRemoveBtn" class="modal-btn modal-btn-danger"><i class="fas fa-user-minus"></i> Remove</button>
        <button onclick="friendAction('list')" id="friendListBtn" class="modal-btn modal-btn-info"><i class="fas fa-list"></i> List Friends</button>
      </div>
      <div id="friendResult" class="modal-result-box" style="min-height:60px;max-height:180px;overflow-y:auto;">Result will appear here...</div>
    </div>
    <div style="text-align:right;margin-top:8px;">
      <button onclick="closeAdminPanel()" class="modal-btn modal-btn-cancel"><i class="fas fa-times"></i> Close Panel</button>
    </div>
  </div>
</div>

''' + VOICE_HELPER_JS + '''
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
var GLOBAL_NOTICE = {{ notice_json|safe }};
var IS_BLOCKED = {{ 'true' if blocked else 'false' }};
var BLOCK_TYPE = "{{ block_type or '' }}";
var BLOCK_MSG = {{ block_msg_json|safe }};
var LOGIN_NOTICE_ENABLED = {{ 'true' if login_notice_enabled else 'false' }};
var LOGIN_NOTICE_TEXT = {{ login_notice_json|safe }};
var PERSONAL_NOTICE_ENABLED = {{ 'true' if personal_notice_enabled else 'false' }};
var PERSONAL_NOTICE_TEXT = {{ personal_notice_json|safe }};

function showNotice(){document.getElementById('noticeMsg').innerHTML=GLOBAL_NOTICE;document.getElementById('noticeIcon').textContent='📢';document.getElementById('noticeTitle').textContent='OWNER NOTICE';document.getElementById('noticePopup').classList.add('show');}
function hideNotice(){document.getElementById('noticePopup').classList.remove('show');}
document.getElementById('noticePopup').addEventListener('click', function(e){if(e.target===this)hideNotice();});
document.getElementById('loginNoticePopup').addEventListener('click', function(e){if(e.target===this)this.classList.remove('show');});

document.addEventListener('DOMContentLoaded', function(){
  if (IS_BLOCKED) {
    document.getElementById('noticeMsg').innerHTML = BLOCK_MSG;
    if (BLOCK_TYPE === 'global') { document.getElementById('noticeIcon').textContent = '🛠️'; document.getElementById('noticeTitle').textContent = 'SYSTEM MAINTENANCE'; }
    else if (BLOCK_TYPE === 'expired') { document.getElementById('noticeIcon').textContent = '⏰'; document.getElementById('noticeTitle').textContent = 'SUBSCRIPTION EXPIRED'; }
    else if (BLOCK_TYPE === 'admin_disabled') { document.getElementById('noticeIcon').textContent = '🚫'; document.getElementById('noticeTitle').textContent = 'BOT DISABLED'; }
    document.getElementById('noticePopup').classList.add('show');
  } else {
    if (GLOBAL_NOTICE && GLOBAL_NOTICE.trim()) document.getElementById('noticeBtn').style.display = 'flex';
    if (PERSONAL_NOTICE_ENABLED && PERSONAL_NOTICE_TEXT && PERSONAL_NOTICE_TEXT.trim()) {
      document.getElementById('loginNoticeIcon').textContent = '📌';
      document.getElementById('loginNoticeTitle').textContent = 'PERSONAL NOTICE';
      document.getElementById('loginNoticeMsg').innerHTML = PERSONAL_NOTICE_TEXT;
      setTimeout(function(){document.getElementById('loginNoticePopup').classList.add('show');}, 500);
    } else if (LOGIN_NOTICE_ENABLED && LOGIN_NOTICE_TEXT && LOGIN_NOTICE_TEXT.trim()) {
      document.getElementById('loginNoticeIcon').textContent = '🔔';
      document.getElementById('loginNoticeTitle').textContent = 'IMPORTANT NOTICE';
      document.getElementById('loginNoticeMsg').innerHTML = LOGIN_NOTICE_TEXT;
      setTimeout(function(){document.getElementById('loginNoticePopup').classList.add('show');}, 800);
    }
  }
});

function getBtn(id){return document.getElementById(id);}
function setLoading(btn,loading){if(!btn)return;if(loading){btn._origHtml=btn.innerHTML;btn.disabled=true;btn.innerHTML='<span class="spinner"></span>';}else{btn.disabled=false;btn.innerHTML=btn._origHtml||btn.innerHTML;}}
function showNotification(message,type){var el=document.createElement('div');el.className='notification notification-'+type;var icon=type==='success'?'check-circle':(type==='error'?'exclamation-circle':'info-circle');el.innerHTML='<i class="fas fa-'+icon+'"></i> '+message;document.body.appendChild(el);setTimeout(function(){el.remove();},3000);}
/* voice already handled in specific actions; keep notification silent to avoid double-speak */
function escapeHtml(text){if(!text)return '';var d=document.createElement('div');d.textContent=text;return d.innerHTML;}
var performanceChart=null;
function initChart(){var ctx=document.getElementById('performanceChart');if(!ctx)return;performanceChart=new Chart(ctx.getContext('2d'),{type:'line',data:{labels:Array(20).fill(''),datasets:[{label:'CPU %',data:Array(20).fill(0),borderColor:'#F5C842',tension:.4,fill:true,borderWidth:2,pointRadius:0},{label:'RAM %',data:Array(20).fill(0),borderColor:'#8540F5',tension:.4,fill:true,borderWidth:2,pointRadius:0}]},options:{responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{labels:{color:'#c5c5e5'}}},scales:{y:{beginAtZero:true,max:100,grid:{color:'rgba(245,200,66,.05)'},ticks:{color:'#a78bfa'}},x:{grid:{color:'rgba(245,200,66,.05)'},ticks:{color:'#a78bfa'}}}}});}
if(typeof Chart!=='undefined')initChart();
var currentTab='logs';
var colorMode = localStorage.getItem('mahirColorMode') !== '0';
function switchTab(tab){currentTab=tab;var btns=document.querySelectorAll('.tab-btn');btns.forEach(function(b){b.classList.remove('active');});document.querySelectorAll('.tab-content').forEach(function(c){c.classList.remove('active');});if(tab==='logs'){btns[0].classList.add('active');document.getElementById('logsTab').classList.add('active');}else if(tab==='messages'){btns[1].classList.add('active');document.getElementById('messagesTab').classList.add('active');}else{btns[2].classList.add('active');document.getElementById('errorsTab').classList.add('active');}}
function toggleColorMode(){colorMode=!colorMode;localStorage.setItem('mahirColorMode',colorMode?'1':'0');var btn=document.getElementById('colorModeBtn');if(btn)btn.innerHTML=colorMode?'<i class="fas fa-palette"></i> Color ON':'<i class="fas fa-palette"></i> Color OFF';updateUI();}
function ansiToHtml(str){if(!str)return '';var s=escapeHtml(str);s=s.replace(/\\[92m/g,'<span style="color:#00e676">');s=s.replace(/\\[93m/g,'<span style="color:#ffeb3b">');s=s.replace(/\\[95m/g,'<span style="color:#e040fb">');s=s.replace(/\\[96m/g,'<span style="color:#00e5ff">');s=s.replace(/\\[91m/g,'<span style="color:#ff5252">');s=s.replace(/\\[94m/g,'<span style="color:#448aff">');s=s.replace(/\\[90m/g,'<span style="color:#9e9e9e">');s=s.replace(/\\[1m/g,'<span style="font-weight:700">');s=s.replace(/\\[0m|\\[m/g,'</span>');s=s.replace(/\\[[0-9;]*m/g,'');return s;}
function formatLogLine(l){if(colorMode) return '<div class="log-line">'+ansiToHtml(l)+'</div>';var plain=l.replace(/\\[[0-9;]*[mK]/g,'');return '<div class="log-line">'+escapeHtml(plain)+'</div>';}
var autoScroll=true;

function togglePause(){
    autoScroll=!autoScroll;
    var btn=document.getElementById('pauseBtn');var fsBtn=document.getElementById('fsPauseBtn');var status=document.getElementById('logStatus');
    if(autoScroll){if(btn)btn.innerHTML='<i class="fas fa-pause"></i> Pause';if(fsBtn)fsBtn.innerHTML='<i class="fas fa-pause"></i> Pause';if(status)status.innerHTML='Auto-scroll: ON';}
    else{if(btn)btn.innerHTML='<i class="fas fa-play"></i> Resume';if(fsBtn)fsBtn.innerHTML='<i class="fas fa-play"></i> Resume';if(status)status.innerHTML='Auto-scroll: OFF';}
}

function toggleFullscreen(boxId){
    var box=document.getElementById(boxId);var fsControls=document.getElementById('fsControls');
    if(!box)return;
    if(box.classList.contains('fullscreen')){box.classList.remove('fullscreen');if(fsControls)fsControls.style.display='none';document.body.style.overflow='';if(history.state&&history.state.isFullscreen){history.back();}}
    else{box.classList.add('fullscreen');if(fsControls)fsControls.style.display='flex';document.body.style.overflow='hidden';history.pushState({isFullscreen:true},'');}
}
window.addEventListener('popstate',function(e){var box=document.getElementById('logBox');if(box&&box.classList.contains('fullscreen'))toggleFullscreen('logBox');});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var box=document.getElementById('logBox');if(box&&box.classList.contains('fullscreen'))toggleFullscreen('logBox');}});

function clearErrors(){fetch('/api/clear_errors',{method:'POST'}).then(function(){updateUI();showNotification('Cleared!','success');});}
function clearMessages(){fetch('/api/clear_messages',{method:'POST'}).then(function(){updateUI();showNotification('Cleared!','success');});}
function downloadText(text,filename){var blob=new Blob([text],{type:'text/plain'});var url=URL.createObjectURL(blob);var a=document.createElement('a');a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);}
function exportLogs(){fetch('/api/export_logs').then(function(r){return r.json();}).then(function(d){if(d.logs&&d.logs.length){downloadText(d.logs.join('\\n'),'logs.txt');showNotification('Exported!','success');}});}
function exportErrors(){fetch('/api/export_errors').then(function(r){return r.json();}).then(function(d){if(d.errors&&d.errors.length){downloadText(d.errors.join('\\n'),'errors.txt');showNotification('Exported!','success');}});}
function exportMessages(){fetch('/api/export_messages').then(function(r){return r.json();}).then(function(d){if(d.messages&&d.messages.length){var t='';d.messages.forEach(function(m){t+='['+m.timestamp+'] '+m.data.nickname+' ('+m.data.sender_uid+'): '+m.data.message+'\\n';});downloadText(t,'messages.txt');showNotification('Exported!','success');}});}

function sendAction(action){
  var btnMap={start:'btnStart',stop:'btnStop',reset:'btnReset'};var btn=getBtn(btnMap[action]);var origHtml=btn.innerHTML;btn.disabled=true;btn.innerHTML='<span class="spinner"></span>';
  fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action})}).then(function(r){return r.json();}).then(function(d){btn.disabled=false;btn.innerHTML=origHtml;if(d.error){showNotification(d.error,'error');if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');}else{showNotification(action.toUpperCase()+' done!','success');setTimeout(updateUI,500);if(window.mahirSpeak){if(action==='start')window.mahirSpeak('বট চালু হয়েছে');else if(action==='stop')window.mahirSpeak('বট বন্ধ হয়েছে');else if(action==='reset')window.mahirSpeak('বট রিসেট হয়েছে');else window.mahirSpeak('কাজ সম্পন্ন');}}}).catch(function(){btn.disabled=false;btn.innerHTML=origHtml;showNotification('Failed','error');if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');});
}

function openRecreateModal(){document.getElementById('recreateModal').classList.add('active');}
function closeRecreateModal(){var box=document.getElementById('recreateModal');if(document.getElementById('recreate-overlay').style.display==='block')return;box.classList.remove('active');}
document.getElementById('recreateModal').addEventListener('click',function(e){if(e.target===this)closeRecreateModal();});

function openAdminPanel(){
  document.getElementById('adminModal').classList.add('active');
  fetch('/api/admin_uids').then(function(r){return r.json();}).then(function(d){if(d.uids)document.getElementById('adminUidsInput').value=d.uids.join(', ');}).catch(function(){});
  fetch('/api/bot_creds').then(function(r){return r.json();}).then(function(d){document.getElementById('botUidInput').value=d.uid||'';document.getElementById('botPwInput').value=d.pw||'';}).catch(function(){});
  fetch('/api/status').then(function(r){return r.json();}).then(function(data){if(data.error)return;var s=function(id,v){var el=document.getElementById(id);if(el)el.innerHTML=v||'---';};s('adminLiveUid',escapeHtml(data.bot_uid));s('adminLiveName',escapeHtml(data.bot_name));s('adminLiveRegion',escapeHtml(data.bot_region));s('adminLiveClanId',escapeHtml(data.bot_clan_id));s('adminLiveStatus',data.bot_status||'Offline');s('adminLiveServer',escapeHtml(data.bot_server));s('adminLiveChat',escapeHtml(data.bot_chat_server));}).catch(function(){});
}
function closeAdminPanel(){document.getElementById('adminModal').classList.remove('active');}
document.getElementById('adminModal') && document.getElementById('adminModal').addEventListener('click',function(e){if(e.target===this)closeAdminPanel();});
function updateAdminUIDs(){var input=document.getElementById('adminUidsInput').value;var uids=input.split(',').map(function(s){return s.trim();}).filter(function(s){return s;});if(!uids.length){showNotification('Enter UIDs','error');if(window.mahirSpeak)window.mahirSpeak('ইউ আই ডি দিন');return;}var btn=document.getElementById('adminUidsBtn');setLoading(btn,true);fetch('/api/admin_uids',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uids:uids})}).then(function(r){return r.json();}).then(function(data){setLoading(btn,false);if(data.status==='success'){showNotification('Updated!','success');if(window.mahirSpeak)window.mahirSpeak('অ্যাডমিন ইউ আই ডি আপডেট হয়েছে');setTimeout(updateUI,3000);}else{showNotification('Failed','error');if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');}});}
function updateBotCreds(){var uid=document.getElementById('botUidInput').value.trim();var pw=document.getElementById('botPwInput').value.trim();if(!uid||!pw){showNotification('Fill both','error');if(window.mahirSpeak)window.mahirSpeak('সব ঘর পূরণ করুন');return;}var btn=document.getElementById('botCredsBtn');setLoading(btn,true);fetch('/api/bot_creds',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:uid,pw:pw})}).then(function(r){return r.json();}).then(function(data){setLoading(btn,false);if(data.status==='success'){showNotification('Updated!','success');if(window.mahirSpeak)window.mahirSpeak('বট ক্রেডেনশিয়াল সেভ হয়েছে');setTimeout(updateUI,3000);}else{showNotification('Failed','error');if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');}});}
function friendAction(action){var uid=document.getElementById('friendUidInput').value.trim();if(action!=='list'&&!uid){showNotification('Enter UID','error');if(window.mahirSpeak)window.mahirSpeak('ইউ আই ডি দিন');return;}var btnMap={add:'friendAddBtn',remove:'friendRemoveBtn',list:'friendListBtn'};var btn=document.getElementById(btnMap[action]);setLoading(btn,true);var payload={action:action};if(uid)payload.uid=uid;document.getElementById('friendResult').innerHTML='Loading...';fetch('/api/friend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(function(r){return r.json();}).then(function(data){setLoading(btn,false);var t='';var ok=(data&&data.status==='success');if(action==='list'){if(ok&&data.friends){t='Friends:\\n'+(data.friends.length?data.friends.map(function(f,i){return (i+1)+'. '+f.name+' ('+f.uid+')';}).join('\\n'):'Empty');if(window.mahirSpeak)window.mahirSpeak('ফ্রেন্ড লিস্ট লোড হয়েছে');}else{t='Error: '+(data.message||'');if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');}}else{t=JSON.stringify(data,null,2);if(window.mahirSpeak){if(action==='add')window.mahirSpeak(ok?'অ্যাড রিকোয়েস্ট পাঠানো হয়েছে':'অ্যাড ব্যর্থ হয়েছে');else if(action==='remove')window.mahirSpeak(ok?'ফ্রেন্ড রিমুভ হয়েছে':'রিমুভ ব্যর্থ হয়েছে');}}document.getElementById('friendResult').innerHTML=escapeHtml(t).replace(/\\n/g,'<br>');}).catch(function(){setLoading(btn,false);if(window.mahirSpeak)window.mahirSpeak('সমস্যা হয়েছে');});}

function updateUI(){
  if(IS_BLOCKED) return;
  fetch('/api/status').then(function(r){return r.json();}).then(function(data){if(data.error)return;var s=function(id,v){var el=document.getElementById(id);if(el)el.innerHTML=v;};
    s('botUid',escapeHtml(data.bot_uid)||'---');s('botName',escapeHtml(data.bot_name)||'---');s('botRegion',escapeHtml(data.bot_region)||'---');
    s('botClanId',escapeHtml(data.bot_clan_id)||'---');s('botStatus',data.bot_status||'Offline');
    s('botServer',escapeHtml(data.bot_server)||'---');s('botChatServer',escapeHtml(data.bot_chat_server)||'---');s('botBy',escapeHtml(data.bot_by)||'---');
    s('processStatus',data.is_running?'<span class="badge badge-active">RUNNING</span>':'<span class="badge badge-offline">STOPPED</span>');
    s('uptime',data.uptime||'00:00:00');s('restartCount',data.restart_count||0);s('errorCount',(data.error_logs||[]).length);
    var cpu=parseFloat(data.cpu)||0,ram=parseFloat(data.ram)||0,disk=parseFloat(data.disk)||0;
    s('cpuValue',Math.floor(cpu)+'%');s('ramValue',Math.floor(ram)+'%');s('diskValue',Math.floor(disk)+'%');
    ['cpuBar','ramBar','diskBar'].forEach(function(id,i){var bar=document.getElementById(id);if(bar)bar.style.width=[cpu,ram,disk][i]+'%';});
    if(data.logs){var h=data.logs.slice(-200).map(function(l){return formatLogLine(l);}).join('');var box=document.getElementById('logBox');if(box){box.innerHTML=h;if(autoScroll&&currentTab==='logs')box.scrollTop=box.scrollHeight;}}
    if(data.error_logs){var e=data.error_logs.slice(-100).map(function(l){return '<div class="log-line error-line">'+escapeHtml(l)+'</div>';}).join('');var eb=document.getElementById('errorBox');if(eb)eb.innerHTML=e;}
    if(data.message_history){var m=data.message_history.slice().reverse().map(function(msg){var pfp=msg.data.pfp_url&&msg.data.pfp_url!=='N/A'?msg.data.pfp_url:'';var pfpHtml=pfp?'<img class="message-pfp" src="'+escapeHtml(pfp)+'" alt="PFP" onerror="this.style.display=\\'none\\'"/>':'<div class="message-pfp" style="display:flex;align-items:center;justify-content:center;font-size:1.2rem;color:var(--gold);">👤</div>';return '<div class="message-card">'+pfpHtml+'<div class="message-body"><div class="message-header"><span class="message-sender">'+escapeHtml(msg.data.nickname)+'</span><span class="message-time">'+escapeHtml(msg.timestamp)+'</span></div><div class="message-meta"><span class="message-label">UID:</span><span class="message-value">'+escapeHtml(msg.data.sender_uid)+'</span><span class="message-label">Message:</span><span class="message-value">'+escapeHtml(msg.data.message)+'</span>'+(msg.data.guild_name&&msg.data.guild_name!=='N/A'?'<span class="message-label">Guild:</span><span class="message-value">'+escapeHtml(msg.data.guild_name)+'</span>':'')+'</div></div></div>';}).join('');var mb=document.getElementById('messageHistory');if(mb)mb.innerHTML=m;}
    if(performanceChart&&data.cpu_history){performanceChart.data.datasets[0].data=data.cpu_history;performanceChart.data.datasets[1].data=data.ram_history;performanceChart.update('none');}
  });}
setInterval(updateUI,1500);updateUI();
(function(){var btn=document.getElementById('colorModeBtn');if(btn)btn.innerHTML=colorMode?'<i class="fas fa-palette"></i> Color ON':'<i class="fas fa-palette"></i> Color OFF';})();
// Voice greeting after login
(function(){
  function speak(text){try{if(!window.speechSynthesis)return;window.speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(text);u.lang='en-US';u.rate=0.95;window.speechSynthesis.speak(u);}catch(e){}}
  function playBeep(){try{var ctx=new(window.AudioContext||window.webkitAudioContext)();var o=ctx.createOscillator();var g=ctx.createGain();o.connect(g);g.connect(ctx.destination);o.frequency.value=880;o.type='sine';g.gain.setValueAtTime(0.08,ctx.currentTime);g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.25);o.start();o.stop(ctx.currentTime+0.25);}catch(e){}}
  {% if just_logged_in %}
  setTimeout(function(){playBeep();speak("Welcome {{ voice_name or 'User' }}. Your Mahir bot panel is ready.");},700);
  {% endif %}
})();
</script></body></html>'''



def _auth_page_ctx():
    """Context for login/register/recover/owner/agent login pages (dynamic sidebar)."""
    links = get_custom_links()
    apk = get_app_link() or '#'
    return {
        'sidebar_menu': build_sidebar_menu(apk_url=apk, links=links),
        'custom_links': links,
        'app_download_link': apk,
        'logo_url': get_logo_url(),
        'cover_url': get_cover_url(),
    }

# ============================================================
#  ROUTES
# ============================================================
@app.route('/')
def index():
    if session.get('owner_mode'):
        return redirect(url_for('owner_dashboard'))
    if session.get('is_admin'):
        return redirect(url_for('owner_dashboard'))
    elif session.get('is_agent'):
        return redirect(url_for('agent_dashboard'))
    elif session.get('user_id'):
        return redirect(url_for('user_dashboard'))
    return redirect(url_for('login'))


@app.errorhandler(500)
def handle_500(e):
    # Do NOT force logout / redirect to login on every 500.
    # That was causing spontaneous "logout" when SQLite briefly locked.
    try:
        init_db(); migrate_db()
    except Exception:
        pass
    try:
        if session.get('is_admin') or session.get('owner_mode'):
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('owner_dashboard'))
        if session.get('is_agent'):
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('agent_dashboard'))
        if session.get('user_id') is not None:
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('user_dashboard'))
    except Exception:
        pass
    return redirect(url_for('login'))


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Catch-all so DB lock / other errors never look like a forced logout.
    # OperationalError and similar are handled here instead of a separate
    # sqlite3-specific handler (more reliable under gunicorn).
    if isinstance(e, sqlite3.OperationalError):
        try:
            init_db(); migrate_db()
        except Exception:
            pass
        try:
            flash('Database is busy, please try again in a moment.', 'error')
            if session.get('is_admin') or session.get('owner_mode'):
                return redirect(url_for('owner_dashboard'))
            if session.get('is_agent'):
                return redirect(url_for('agent_dashboard'))
            if session.get('user_id') is not None:
                return redirect(url_for('user_dashboard'))
        except Exception:
            pass
        return redirect(url_for('login'))
    # Re-raise HTTP exceptions / other things Flask should handle normally
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    # Unknown error — log and soft-redirect without destroying session
    print(f'[UNHANDLED] {type(e).__name__}: {e}')
    try:
        if session.get('is_admin') or session.get('owner_mode'):
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('owner_dashboard'))
        if session.get('is_agent'):
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('agent_dashboard'))
        if session.get('user_id') is not None:
            flash('Temporary server error. Please try again.', 'error')
            return redirect(url_for('user_dashboard'))
    except Exception:
        pass
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id, username, password, is_admin, is_agent FROM users WHERE username=?', (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password(user[2], password):
            session['user_id'] = user[0]; session['username'] = user[1]
            session['is_admin'] = bool(user[3]); session['is_agent'] = bool(user[4])
            session.permanent = True
            session['just_logged_in'] = True
            session['voice_name'] = user[1]
            if session['is_admin']: return redirect(url_for('owner_dashboard'))
            elif session['is_agent']: return redirect(url_for('agent_dashboard'))
            else: return redirect(url_for('user_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template_string(LOGIN_HTML, **_auth_page_ctx())


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form.get('email', '')
        reg_key = request.form['registration_key']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id, expiry_date, created_by FROM keys WHERE key=? AND is_used=0', (reg_key,))
        key_row = c.fetchone()
        if not key_row:
            conn.close()
            flash('Invalid key', 'error')
            return render_template_string(REGISTER_HTML, **_auth_page_ctx())
        if key_row[1]:
            try:
                if datetime.fromisoformat(key_row[1]) < datetime.now():
                    conn.close()
                    flash('Key expired', 'error')
                    return render_template_string(REGISTER_HTML, **_auth_page_ctx())
            except: pass
        c.execute('SELECT id FROM users WHERE username=?', (username,))
        if c.fetchone():
            conn.close()
            flash('Username taken', 'error')
            return render_template_string(REGISTER_HTML, **_auth_page_ctx())
        agent_name = key_row[2] if key_row[2] and key_row[2] not in ('admin', 'system', 'MAHIR TCP', 'OWNER') else None
        c.execute('''INSERT INTO users (username, password, email, registration_key, is_admin, is_agent, subscription_expiry, created_by_agent)
                     VALUES (?, ?, ?, ?, 0, 0, ?, ?)''', (username, password, email, reg_key, key_row[1], agent_name))
        c.execute('UPDATE keys SET is_used=1, used_by=?, used_at=CURRENT_TIMESTAMP WHERE key=?', (username, reg_key))
        conn.commit(); conn.close()
        flash('Registration successful!', 'success')
        return redirect(url_for('login'))
    return render_template_string(REGISTER_HTML, **_auth_page_ctx())


@app.route('/recover', methods=['GET', 'POST'])
def recover():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT password FROM users WHERE username=? AND email=?', (username, email))
        row = c.fetchone()
        if row:
            stored = row[0]
            if is_hashed(stored):
                new_pw = secrets.token_hex(8)
                c.execute('UPDATE users SET password=? WHERE username=?', (new_pw, username))
                conn.commit(); conn.close()
                flash(f'Password reset: {new_pw}', 'success')
            else:
                conn.close()
                flash(f'Your password: {stored}', 'success')
        else:
            conn.close()
            flash('Not found', 'error')
    return render_template_string(RECOVER_HTML, **_auth_page_ctx())


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ========== AGENT ROUTES ==========
@app.route('/agent/login', methods=['GET', 'POST'])
def agent_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id, username, password, is_agent FROM users WHERE username=?', (username,))
        user = c.fetchone()
        conn.close()
        if user and user[3] == 1 and check_password(user[2], password):
            session['user_id'] = user[0]; session['username'] = user[1]
            session['is_agent'] = True; session['is_admin'] = False
            session.permanent = True
            return redirect(url_for('agent_dashboard'))
        flash('Invalid', 'error')
    return render_template_string(AGENT_LOGIN_HTML, **_auth_page_ctx())


@app.route('/agent/dashboard')
@agent_required
def agent_dashboard():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, key, created_at, used_by, is_used, expiry_date, duration_days 
                 FROM keys WHERE created_by=? ORDER BY id DESC''', (session['username'],))
    keys = []
    for r in c.fetchall():
        used_by = r[3]
        user_sub_days = None
        user_sub_status = None
        used_user_id = None
        if used_by:
            c.execute('SELECT id FROM users WHERE username=?', (used_by,))
            ur = c.fetchone()
            if ur:
                used_user_id = ur[0]
                sub = check_subscription_status(ur[0])
                user_sub_status = sub['status']
                if sub['status'] == 'unlimited':
                    user_sub_days = None
                elif sub['status'] == 'expired':
                    user_sub_days = 0
                else:
                    user_sub_days = sub['days_left']
        keys.append({
            'id': r[0], 'key': r[1], 'created_at': r[2], 'used_by': used_by,
            'is_used': r[4], 'expiry_date': r[5],
            'duration_days': r[6] if r[6] is not None else 0,
            'user_sub_days': user_sub_days,
            'user_sub_status': user_sub_status,
            'used_user_id': used_user_id
        })
    c.execute('SELECT key_limit, can_manage_db FROM users WHERE id=?', (session['user_id'],))
    row = c.fetchone()
    key_limit = row[0] if row and row[0] is not None else -1
    can_manage_db = bool(row[1]) if row else False
    c.execute('''SELECT id, username, email, bot_uid, bot_status, subscription_expiry, registration_key 
                 FROM users WHERE created_by_agent=? AND is_admin=0 AND is_agent=0 ORDER BY id DESC''',
              (session['username'],))
    users_rows = c.fetchall()
    my_users = []
    for u in users_rows:
        sub = check_subscription_status(u[0])
        c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (u[0],))
        rn = c.fetchone()
        renew_count = rn[0] if rn else 0
        renew_days = rn[1] if rn else 0
        sub_time_left = format_time_left(sub['expiry']) if sub['expiry'] else '∞'
        my_users.append({
            'id': u[0], 'username': u[1], 'email': u[2],
            'bot_uid': u[3] or '—', 'bot_status': u[4],
            'sub_status': sub['status'], 'sub_days': sub['days_left'],
            'sub_time_left': sub_time_left,
            'sub_expiry': sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else None,
            'renew_count': renew_count, 'renew_days': renew_days
        })
    conn.close()

    # ✅ NEW: session থেকে freshly generated key নিন (one-time use)
    new_key_data = session.pop('new_key_generated', None)

    max_bots = get_max_running_bots()
    running_now = count_running_bots()
    limit_full = is_bot_limit_full()

    return render_template_string(AGENT_DASHBOARD_HTML, keys=keys, new_key=None,
                                  key_limit=key_limit, key_count=len(keys),
                                  can_manage_db=can_manage_db, my_users=my_users,
                                  new_key_data=new_key_data,
                                  max_running_bots=max_bots,
                                  running_bots_count=running_now,
                                  bot_limit_full=limit_full)


@app.route('/agent/subscription')
@agent_required
def agent_subscription():
    agent = session['username']
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, email, bot_uid, bot_status, subscription_expiry, registration_key 
                 FROM users WHERE created_by_agent=? AND is_admin=0 AND is_agent=0 ORDER BY id DESC''',
              (agent,))
    users_rows = c.fetchall()
    my_users = []
    active_count = 0; expiring_count = 0; expired_count = 0
    for u in users_rows:
        sub = check_subscription_status(u[0])
        c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (u[0],))
        rn = c.fetchone()
        renew_count = rn[0] if rn else 0
        renew_days = rn[1] if rn else 0
        sub_time_left = format_time_left(sub['expiry']) if sub['expiry'] else '∞'
        if sub['status'] == 'expired':
            expired_count += 1
        elif sub['status'] == 'unlimited':
            active_count += 1
        elif sub['days_left'] <= 7:
            expiring_count += 1
            active_count += 1
        else:
            active_count += 1
        my_users.append({
            'id': u[0], 'username': u[1], 'email': u[2],
            'bot_uid': u[3] or '—', 'bot_status': u[4],
            'sub_status': sub['status'], 'sub_days': sub['days_left'],
            'sub_time_left': sub_time_left,
            'sub_expiry': sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else None,
            'renew_count': renew_count, 'renew_days': renew_days
        })
    c.execute('''SELECT id, user_id, username, extended_by, extended_by_role, days_added, mode, 
                 old_expiry, new_expiry, created_at
                 FROM subscription_history WHERE extended_by=? ORDER BY id DESC LIMIT 100''', (agent,))
    my_history = []
    for r in c.fetchall():
        my_history.append({
            'id': r[0], 'user_id': r[1], 'username': r[2], 'extended_by': r[3],
            'extended_by_role': r[4], 'days_added': r[5], 'mode': r[6],
            'old_expiry': r[7], 'new_expiry': r[8], 'created_at': r[9]
        })
    conn.close()
    return render_template_string(AGENT_SUBSCRIPTION_HTML,
                                  my_users=my_users,
                                  my_history=my_history,
                                  active_count=active_count,
                                  expiring_count=expiring_count,
                                  expired_count=expired_count)


@app.route('/agent/customer_history/<int:user_id>')
@agent_required
def agent_customer_history(user_id):
    agent = session['username']
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, email, password, bot_uid, bot_pw, bot_file,
                 bot_status, admin_uid, created_at, registration_key,
                 subscription_expiry, bot_disabled_by_admin, bot_force_active,
                 created_by_agent, is_admin, is_agent
                 FROM users WHERE id=? AND is_admin=0 AND is_agent=0''', (user_id,))
    u = c.fetchone()
    if not u:
        conn.close()
        flash('❌ Customer not found.', 'error')
        return redirect(url_for('agent_subscription'))

    owns_via_agent = (u[14] == agent)
    owns_via_key = False
    if not owns_via_agent and u[10]:
        c.execute('SELECT created_by FROM keys WHERE key=?', (u[10],))
        kr = c.fetchone()
        if kr and kr[0] == agent:
            owns_via_key = True
            c.execute('UPDATE users SET created_by_agent=? WHERE id=? AND (created_by_agent IS NULL OR created_by_agent="")', (agent, user_id))
            conn.commit()

    if not owns_via_agent and not owns_via_key:
        conn.close()
        flash('❌ Access denied! This customer is not yours.', 'error')
        return redirect(url_for('agent_subscription'))

    sub = check_subscription_status(user_id)
    sub_time_left = format_time_left(sub['expiry']) if sub['expiry'] else '∞'

    c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (user_id,))
    rn = c.fetchone()
    renew_count = rn[0] if rn else 0
    renew_days = rn[1] if rn else 0

    c.execute('''SELECT id, user_id, username, extended_by, extended_by_role, days_added, mode,
                 old_expiry, new_expiry, created_at
                 FROM subscription_history WHERE user_id=? ORDER BY id DESC''', (user_id,))
    sub_history = []
    for r in c.fetchall():
        sub_history.append({
            'id': r[0], 'user_id': r[1], 'username': r[2], 'extended_by': r[3],
            'extended_by_role': r[4], 'days_added': r[5], 'mode': r[6],
            'old_expiry': r[7], 'new_expiry': r[8], 'created_at': r[9]
        })
    conn.close()

    user_data = {
        'id': u[0],
        'username': u[1],
        'email_masked': mask_email(u[2]),
        'password_masked': mask_password(u[3]),
        'bot_uid': u[4] or '—',
        'bot_pw_masked': mask_bot_password(u[5]),
        'bot_file': u[6] or '—',
        'bot_status': u[7] or 'unknown',
        'admin_uid': u[8] or '—',
        'created_at': u[9],
        'registration_key': u[10] or '—',
        'sub_status': sub['status'],
        'sub_days': sub['days_left'],
        'sub_time_left': sub_time_left,
        'sub_expiry': sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else None,
        'bot_disabled_by_admin': u[12] or 0,
        'bot_force_active': u[13] or 0,
        'created_by_agent': u[14] or 'Owner',
        'renew_count': renew_count,
        'renew_days': renew_days
    }

    live = None
    with monitors_lock:
        if user_id in monitors:
            try: live = monitors[user_id].get_status()
            except: pass

    return render_template_string(AGENT_CUSTOMER_HISTORY_HTML,
                                  user=user_data,
                                  sub_history=sub_history,
                                  live=live)


@app.route('/agent/renew_subscription/<int:user_id>', methods=['POST'])
@agent_required
def agent_renew_subscription(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT created_by_agent FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or row[0] != session['username']:
        flash('❌ Access denied! This customer is not yours.', 'error')
        return redirect(url_for('agent_subscription'))
    return _renew_subscription(user_id, 'agent_subscription')


@app.route('/agent/create_key', methods=['POST'])
@agent_required
def agent_create_key():
    # Global concurrent bot limit full → agents cannot create new keys
    if is_bot_limit_full():
        max_b = get_max_running_bots()
        running = count_running_bots()
        flash(f'⛔ বট লিমিট পূর্ণ ({running}/{max_b})! নতুন Key তৈরি করা যাবে না। Owner লিমিট বাড়ান বা বট বন্ধ করুন।', 'error')
        return redirect(url_for('agent_dashboard'))

    days = int(request.form.get('days_valid', 30))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key_limit FROM users WHERE id=?', (session['user_id'],))
    row = c.fetchone()
    key_limit = row[0] if row and row[0] is not None else -1
    c.execute('SELECT COUNT(*) FROM keys WHERE created_by=?', (session['username'],))
    if key_limit >= 0 and c.fetchone()[0] >= key_limit:
        conn.close()
        flash(f'Max {key_limit} keys.', 'error')
        return redirect(url_for('agent_dashboard'))
    key = secrets.token_hex(16).upper()
    expiry = None if days == 0 else datetime.now() + timedelta(days=days)
    c.execute('INSERT INTO keys (key, created_by, expiry_date, duration_days) VALUES (?, ?, ?, ?)',
              (key, session['username'], expiry.isoformat() if expiry else None, days))
    conn.commit(); conn.close()

    # ✅ NEW: animated modal-এর জন্য session এ save
    session['new_key_generated'] = {
        'key': key,
        'duration_text': '∞ Permanent' if days == 0 else f'{days} Days Valid',
        'is_permanent': days == 0,
    }

    flash('🔑 New key generated successfully!', 'success')
    return redirect(url_for('agent_dashboard'))


@app.route('/agent/logout')
def agent_logout():
    session.clear()
    return redirect(url_for('agent_login'))


@app.route('/agent/download_db', methods=['POST'])
@agent_required
def agent_download_db():
    password = request.form.get('db_password', '')
    if password != DB_DOWNLOAD_PASSWORD:
        flash('❌ Wrong DB password!', 'error')
        return redirect(url_for('agent_dashboard'))
    if os.path.exists(DB_FILE):
        return send_file(DB_FILE, as_attachment=True)
    flash('❌ DB file not found', 'error')
    return redirect(url_for('agent_dashboard'))


# ========== OWNER ROUTES ==========
def _build_grouped_data():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute('SELECT id, username FROM users WHERE is_agent=1 ORDER BY username')
    agents = c.fetchall()

    groups_keys = []
    groups_users = []
    groups_history = []

    owner_slug = '__owner__'
    c.execute("SELECT COUNT(*), SUM(CASE WHEN is_used=1 THEN 1 ELSE 0 END) FROM keys WHERE created_by IN ('OWNER','MAHIR TCP','admin','system')")
    r = c.fetchone()
    owner_total_keys = r[0] or 0
    owner_used_keys = r[1] or 0
    c.execute("""SELECT COUNT(DISTINCT sh.user_id) FROM subscription_history sh
                 INNER JOIN keys k ON k.key = (SELECT registration_key FROM users WHERE id = sh.user_id)
                 WHERE k.created_by IN ('OWNER','MAHIR TCP','admin','system')""")
    r = c.fetchone()
    owner_renewed = r[0] or 0
    groups_keys.append({
        'name': 'OWNER MAHIR', 'slug': owner_slug, 'is_owner': True,
        'total_keys': owner_total_keys, 'used_keys': owner_used_keys,
        'unused_keys': owner_total_keys - owner_used_keys,
        'renewed_users': owner_renewed
    })

    c.execute("""SELECT COUNT(*) FROM users 
                 WHERE is_admin=0 AND is_agent=0 
                 AND (created_by_agent IS NULL OR created_by_agent='' OR created_by_agent IN ('Owner','OWNER','admin','system','MAHIR TCP'))""")
    r = c.fetchone()
    owner_total_users = r[0] or 0
    active_owner = 0; expired_owner = 0; renewed_owner = 0
    c.execute("""SELECT id FROM users WHERE is_admin=0 AND is_agent=0 
                 AND (created_by_agent IS NULL OR created_by_agent='' OR created_by_agent IN ('Owner','OWNER','admin','system','MAHIR TCP'))""")
    owner_uids = [r[0] for r in c.fetchall()]
    for uid in owner_uids:
        sub = check_subscription_status(uid)
        if sub['status'] == 'expired': expired_owner += 1
        else: active_owner += 1
        c.execute('SELECT COUNT(*) FROM subscription_history WHERE user_id=?', (uid,))
        if c.fetchone()[0] > 0: renewed_owner += 1
    groups_users.append({
        'name': 'OWNER MAHIR', 'slug': owner_slug, 'is_owner': True,
        'total_users': owner_total_users, 'active_users': active_owner,
        'expired_users': expired_owner, 'renewed_users': renewed_owner
    })

    c.execute("""SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history 
                 WHERE extended_by_role='owner' OR extended_by IN ('OWNER','MAHIR TCP','admin','system')""")
    r = c.fetchone()
    groups_history.append({
        'name': 'OWNER MAHIR', 'slug': owner_slug, 'is_owner': True,
        'total_entries': r[0] or 0, 'total_days': r[1] or 0
    })

    for aid, aname in agents:
        slug = aname
        c.execute('SELECT COUNT(*), SUM(CASE WHEN is_used=1 THEN 1 ELSE 0 END) FROM keys WHERE created_by=?', (aname,))
        r = c.fetchone()
        total_keys = r[0] or 0
        used_keys = r[1] or 0
        c.execute('SELECT COUNT(DISTINCT user_id) FROM subscription_history WHERE extended_by=?', (aname,))
        renewed = c.fetchone()[0] or 0
        groups_keys.append({
            'name': aname, 'slug': slug, 'is_owner': False,
            'total_keys': total_keys, 'used_keys': used_keys,
            'unused_keys': total_keys - used_keys, 'renewed_users': renewed
        })

        c.execute('SELECT COUNT(*) FROM users WHERE created_by_agent=? AND is_admin=0 AND is_agent=0', (aname,))
        total_users = c.fetchone()[0] or 0
        c.execute('SELECT id FROM users WHERE created_by_agent=? AND is_admin=0 AND is_agent=0', (aname,))
        uids = [r[0] for r in c.fetchall()]
        active = 0; expired = 0; renewed_users = 0
        for uid in uids:
            sub = check_subscription_status(uid)
            if sub['status'] == 'expired': expired += 1
            else: active += 1
            c.execute('SELECT COUNT(*) FROM subscription_history WHERE user_id=?', (uid,))
            if c.fetchone()[0] > 0: renewed_users += 1
        groups_users.append({
            'name': aname, 'slug': slug, 'is_owner': False,
            'total_users': total_users, 'active_users': active,
            'expired_users': expired, 'renewed_users': renewed_users
        })

        c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE extended_by=?', (aname,))
        r = c.fetchone()
        groups_history.append({
            'name': aname, 'slug': slug, 'is_owner': False,
            'total_entries': r[0] or 0, 'total_days': r[1] or 0
        })

    conn.close()
    return groups_keys, groups_users, groups_history


@app.route('/owner/login', methods=['GET', 'POST'])
def owner_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == OWNER_USERNAME and password == OWNER_PASSWORD:
            session.clear()
            session['user_id'] = -1
            session['username'] = 'OWNER'
            session['is_admin'] = True
            session['is_agent'] = False
            session['owner_mode'] = True
            session.permanent = True
            session['just_logged_in'] = True
            session['voice_name'] = 'Owner Mahir'
            return redirect(url_for('owner_dashboard'))
        flash('Invalid owner credentials', 'error')
    return render_template_string(OWNER_LOGIN_HTML, **_auth_page_ctx())


@app.route('/owner/logout')
def owner_logout():
    session.clear()
    return redirect(url_for('owner_login'))


@app.route('/owner/login_as/<int:user_id>')
def owner_login_as(user_id):
    if not session.get('owner_mode'):
        flash('Owner access required', 'error')
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, username, is_admin, is_agent FROM users WHERE id=?', (user_id,))
    u = c.fetchone()
    conn.close()
    if not u:
        flash('User not found', 'error')
        return redirect(url_for('owner_dashboard'))
    session['user_id'] = u[0]
    session['username'] = u[1]
    session['is_admin'] = bool(u[2])
    session['is_agent'] = bool(u[3])
    if session['is_admin']:
        return redirect(url_for('owner_dashboard'))
    elif session['is_agent']:
        return redirect(url_for('agent_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))


@app.route('/owner/return')
def owner_return():
    if not session.get('owner_mode'):
        return redirect(url_for('login'))
    session['user_id'] = -1
    session['username'] = 'OWNER'
    session['is_admin'] = True
    session['is_agent'] = False
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/dashboard')
def owner_dashboard():
    if not session.get('is_admin'):
        flash('Owner access required', 'error')
        return redirect(url_for('owner_login'))
        
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, email, created_at, bot_status, bot_file, 
                 is_admin, is_agent, key_limit, can_manage_db, password,
                 bot_disabled_by_admin, subscription_expiry, registration_key, bot_uid, 
                 created_by_agent, personal_notice, personal_notice_enabled
                 FROM users ORDER BY id DESC''')
    rows = c.fetchall()
    users = []; agents = []
    for r in rows:
        sub = check_subscription_status(r[0])
        c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (r[0],))
        rn = c.fetchone()
        renew_count = rn[0] if rn else 0
        renew_days = rn[1] if rn else 0
        user_dict = {
            'id': r[0], 'username': r[1], 'email': r[2], 'created_at': r[3],
            'bot_status': r[4], 'bot_file': r[5], 'is_admin': r[6], 'is_agent': r[7],
            'key_limit': r[8] if r[8] is not None else -1,
            'can_manage_db': r[9] or 0, 'password': r[10],
            'bot_disabled_by_admin': r[11] or 0,
            'sub_status': sub['status'], 'sub_days': sub['days_left'], 'bot_uid': r[14],
            'created_by_agent': r[15],
            'personal_notice': r[16] or '',
            'personal_notice_enabled': r[17] or 0,
            'renew_count': renew_count, 'renew_days': renew_days
        }
        users.append(user_dict)
        if r[7] == 1:
            c2 = conn.cursor()
            c2.execute('SELECT COUNT(*) FROM keys WHERE created_by=?', (r[1],))
            kc = c2.fetchone()[0]
            c2.close()
            ag = user_dict.copy(); ag['key_count'] = kc
            agents.append(ag)

    c.execute('''SELECT id, user_id, username, extended_by, extended_by_role, days_added, mode, 
                 old_expiry, new_expiry, created_at
                 FROM subscription_history ORDER BY id DESC LIMIT 100''')
    sub_history = []
    for r in c.fetchall():
        sub_history.append({
            'id': r[0], 'user_id': r[1], 'username': r[2], 'extended_by': r[3],
            'extended_by_role': r[4], 'days_added': r[5], 'mode': r[6],
            'old_expiry': r[7], 'new_expiry': r[8], 'created_at': r[9]
        })

    c.execute('''SELECT id, key, created_by, created_at, used_by, is_used, expiry_date, duration_days 
                 FROM keys ORDER BY id DESC LIMIT 50''')
    keys = []
    for r in c.fetchall():
        keys.append({
            'id': r[0], 'key': r[1], 'created_by': r[2], 'created_at': r[3],
            'used_by': r[4], 'is_used': r[5], 'expiry_date': r[6],
            'duration_days': r[7] if r[7] is not None else 0
        })
        
    # ✅ নতুন: Custom Links নিয়ে আসা
    custom_links = get_custom_links()
    
    conn.close()
    stats = {'cpu': 0, 'ram_percent': 0, 'ram_used': 0, 'ram_total': 0, 'disk_percent': 0, 'disk_used': 0, 'disk_total': 0}
    try:
        stats['cpu'] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        stats['ram_percent'] = mem.percent; stats['ram_used'] = mem.used; stats['ram_total'] = mem.total
        disk = psutil.disk_usage('/')
        stats['disk_percent'] = disk.percent; stats['disk_used'] = disk.used; stats['disk_total'] = disk.total
    except: pass

    grouped_keys, grouped_users, grouped_history = _build_grouped_data()

    # ✅ NEW: session থেকে freshly generated key নিন (one-time use)
    new_key_data = session.pop('new_key_generated', None)

    return render_template_string(OWNER_DASHBOARD_HTML, users=users, agents=agents, keys=keys,
                                  new_key=None, global_stop=get_global_stop(),
                                  global_notice=get_global_notice(),
                                  login_notice_enabled=is_user_login_notice_enabled(),
                                  login_notice_text=get_user_login_notice(),
                                  sub_history=sub_history,
                                  grouped_keys=grouped_keys,
                                  grouped_users=grouped_users,
                                  grouped_history=grouped_history,
                                  auto_bio_text=get_auto_bio(),
                                  youtube_link=get_youtube_link(),
                                  app_download_link=get_app_link(),
                                  default_ff_region=get_default_region(),
                                  custom_links=custom_links,
                                  new_key_data=new_key_data,
                                  logo_url=get_logo_url(),
                                  cover_url=get_cover_url(),
                                  photo_files=list_photo_files(),
                                  just_logged_in=bool(session.pop('just_logged_in', False)),
                                  voice_name=session.pop('voice_name', session.get('username', 'Owner')),
                                  max_running_bots=get_max_running_bots(),
                                  running_bots_count=count_running_bots(),
                                  **stats)


@app.route('/owner/group_keys/<path:slug>')
def owner_group_keys(slug):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    is_owner = (slug == '__owner__')
    if is_owner:
        group_name = 'OWNER MAHIR'
        c_where = "created_by IN ('OWNER','MAHIR TCP','admin','system')"
        params = ()
    else:
        group_name = slug
        c_where = "created_by = ?"
        params = (slug,)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f'''SELECT id, key, created_by, created_at, used_by, used_at, is_used, expiry_date, duration_days
                  FROM keys WHERE {c_where} ORDER BY id DESC''', params)
    raw_keys = c.fetchall()

    keys = []
    used_count = 0; unused_count = 0; renewed_count = 0
    for r in raw_keys:
        used_by = r[4]
        renew_count = 0; renew_days = 0
        if used_by:
            c.execute('SELECT id FROM users WHERE username=?', (used_by,))
            ur = c.fetchone()
            if ur:
                c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (ur[0],))
                rr = c.fetchone()
                renew_count = rr[0] or 0
                renew_days = rr[1] or 0
        if r[6]: used_count += 1
        else: unused_count += 1
        if renew_count > 0: renewed_count += 1
        keys.append({
            'id': r[0], 'key': r[1], 'created_by': r[2], 'created_at': r[3],
            'used_by': r[4], 'used_at': r[5], 'is_used': r[6],
            'expiry_date': r[7], 'duration_days': r[8] if r[8] is not None else 0,
            'renew_count': renew_count, 'renew_days': renew_days
        })
    conn.close()
    return render_template_string(OWNER_GROUP_KEYS_HTML,
                                  group_name=group_name, is_owner=is_owner,
                                  keys=keys, used_count=used_count,
                                  unused_count=unused_count,
                                  renewed_count=renewed_count)


@app.route('/owner/key_details/<int:key_id>')
def owner_key_details(key_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, key, created_by, created_at, used_by, used_at, is_used, expiry_date, duration_days
                 FROM keys WHERE id=?''', (key_id,))
    r = c.fetchone()
    if not r:
        conn.close()
        flash('Key not found', 'error')
        return redirect(url_for('owner_dashboard'))
    key = {
        'id': r[0], 'key': r[1], 'created_by': r[2], 'created_at': r[3],
        'used_by': r[4], 'used_at': r[5], 'is_used': r[6],
        'expiry_date': r[7], 'duration_days': r[8] if r[8] is not None else 0
    }
    is_owner_group = key['created_by'] in ('OWNER', 'MAHIR TCP', 'admin', 'system')
    creator_slug = '__owner__' if is_owner_group else key['created_by']

    user = None
    renewal_history = []
    if key['used_by']:
        c.execute('''SELECT id, username, email, bot_uid, created_by_agent, subscription_expiry,
                     registration_key, is_admin, is_agent FROM users WHERE username=?''', (key['used_by'],))
        ur = c.fetchone()
        if ur:
            sub = check_subscription_status(ur[0])
            user = {
                'id': ur[0], 'username': ur[1], 'email': ur[2],
                'bot_uid': ur[3] or '—', 'created_by_agent': ur[4],
                'sub_status': sub['status'], 'sub_days': sub['days_left']
            }
            c.execute('''SELECT id, user_id, username, extended_by, extended_by_role, days_added,
                         mode, old_expiry, new_expiry, created_at
                         FROM subscription_history WHERE user_id=? ORDER BY id DESC''', (ur[0],))
            for h in c.fetchall():
                renewal_history.append({
                    'id': h[0], 'user_id': h[1], 'username': h[2], 'extended_by': h[3],
                    'extended_by_role': h[4], 'days_added': h[5], 'mode': h[6],
                    'old_expiry': h[7], 'new_expiry': h[8], 'created_at': h[9]
                })
    conn.close()
    return render_template_string(OWNER_KEY_DETAILS_HTML,
                                  key=key, user=user,
                                  renewal_history=renewal_history,
                                  is_owner_group=is_owner_group,
                                  creator_slug=creator_slug)


@app.route('/owner/group_users/<path:slug>')
def owner_group_users(slug):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    is_owner = (slug == '__owner__')
    if is_owner:
        group_name = 'OWNER MAHIR'
        c_where = """is_admin=0 AND is_agent=0 AND (created_by_agent IS NULL OR created_by_agent='' 
                     OR created_by_agent IN ('Owner','OWNER','admin','system','MAHIR TCP'))"""
        params = ()
    else:
        group_name = slug
        c_where = "created_by_agent=? AND is_admin=0 AND is_agent=0"
        params = (slug,)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f'''SELECT id, username, email, bot_status, subscription_expiry, created_by_agent
                  FROM users WHERE {c_where} ORDER BY id DESC''', params)
    raw = c.fetchall()
    users = []
    for r in raw:
        sub = check_subscription_status(r[0])
        c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (r[0],))
        rn = c.fetchone()
        users.append({
            'id': r[0], 'username': r[1], 'email': r[2], 'bot_status': r[3],
            'sub_status': sub['status'], 'sub_days': sub['days_left'],
            'renew_count': rn[0] if rn else 0,
            'renew_days': rn[1] if rn else 0
        })
    conn.close()
    return render_template_string(OWNER_GROUP_USERS_HTML,
                                  group_name=group_name, is_owner=is_owner, users=users)


@app.route('/owner/group_history/<path:slug>')
def owner_group_history(slug):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    is_owner = (slug == '__owner__')
    if is_owner:
        group_name = 'OWNER MAHIR'
        c_where = "extended_by_role='owner' OR extended_by IN ('OWNER','MAHIR TCP','admin','system')"
        params = ()
    else:
        group_name = slug
        c_where = "extended_by=?"
        params = (slug,)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f'''SELECT id, user_id, username, extended_by, extended_by_role, days_added,
                  mode, old_expiry, new_expiry, created_at
                  FROM subscription_history WHERE {c_where} ORDER BY id DESC''', params)
    history = []
    for r in c.fetchall():
        history.append({
            'id': r[0], 'user_id': r[1], 'username': r[2], 'extended_by': r[3],
            'extended_by_role': r[4], 'days_added': r[5], 'mode': r[6],
            'old_expiry': r[7], 'new_expiry': r[8], 'created_at': r[9]
        })
    conn.close()
    return render_template_string(OWNER_GROUP_HISTORY_HTML,
                                  group_name=group_name, is_owner=is_owner, history=history)


@app.route('/owner/preview_global_notice')
def owner_preview_global_notice():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    notice = get_global_notice()
    return f'''<!DOCTYPE html><html><head><title>Notice Preview</title><style>
body{{background:#07070f;color:#e9e9f8;font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px}}
.box{{background:linear-gradient(135deg,#1a0a2e,#0a0a1a);border:2px solid rgba(245,200,66,.35);border-radius:22px;padding:32px 28px;max-width:520px;text-align:center;box-shadow:0 0 60px rgba(245,200,66,.3)}}
.icon{{font-size:3.5rem;margin-bottom:16px;display:block}}
.title{{font-size:1.4rem;font-weight:900;background:linear-gradient(120deg,#F5C842,#FF5A6A,#B388FF);-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:14px;letter-spacing:1px}}
.msg{{color:#c5c5e5;font-size:.95rem;line-height:1.7;padding:16px;background:rgba(0,0,0,.4);border-radius:14px;border:1px solid rgba(245,200,66,.1);margin-bottom:22px;text-align:left}}
</style></head><body><div class="box">
<span class="icon">📢</span>
<div class="title">OWNER NOTICE</div>
<div class="msg">{notice}</div></div></body></html>'''


@app.route('/owner/set_global_notice', methods=['POST'])
def owner_set_global_notice():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    notice = request.form.get('notice_text', '').strip()
    set_setting('global_notice_text', notice)
    flash('✅ Global notice updated!', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/set_user_login_notice', methods=['POST'])
def owner_set_user_login_notice():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    action = request.form.get('action', 'save')
    notice_text = request.form.get('notice_text', '').strip()

    if action == 'enable':
        set_setting('user_login_notice_enabled', '1')
        set_setting('user_login_notice_text', notice_text)
        flash('✅ User login notice ENABLED!', 'success')
    elif action == 'disable':
        set_setting('user_login_notice_enabled', '0')
        if notice_text:
            set_setting('user_login_notice_text', notice_text)
        flash('🔕 User login notice DISABLED.', 'success')
    else:
        set_setting('user_login_notice_text', notice_text)
        flash('✅ Notice text saved!', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/set_user_notice/<int:user_id>', methods=['POST'])
def owner_set_user_notice(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    notice_text = request.form.get('personal_notice', '').strip()
    enabled = 1 if request.form.get('enabled') == '1' else 0
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET personal_notice=?, personal_notice_enabled=? WHERE id=?',
              (notice_text, enabled, user_id))
    conn.commit(); conn.close()
    flash(f'✅ Personal notice {"enabled" if enabled else "disabled"} for user #{user_id}', 'success')
    return redirect(request.referrer or url_for('owner_dashboard'))


@app.route('/owner/stop_all_bots', methods=['POST'])
def owner_stop_all_bots():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    set_setting('global_bot_stop', '1')
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                m.watchdog_running = False
                m.stop_process()
            except: pass
    flash('🛑 All bots STOPPED globally!', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/start_all_bots', methods=['POST'])
def owner_start_all_bots():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    set_setting('global_bot_stop', '0')
    success, fail = reset_all_bots()
    flash(f'✅ Global stop OFF! Rebuilt + {success} bots started.', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/set_max_bots', methods=['POST'])
def owner_set_max_bots():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    try:
        val = int(request.form.get('max_running_bots', -1))
    except Exception:
        val = -1
    if val < -1:
        val = -1
    if val > 5000:
        val = 5000
    set_setting('max_running_bots', str(val))
    if val < 0:
        flash('✅ Bot limit set to Unlimited', 'success')
    else:
        flash(f'✅ Max concurrent bots set to {val}. Currently running: {count_running_bots()}', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/force_start_bot/<int:user_id>', methods=['POST'])
def owner_force_start_bot(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET bot_force_active=1, bot_disabled_by_admin=0, desired_bot_state="running" WHERE id=?', (user_id,))
    conn.commit()
    c.execute('SELECT bot_file, bot_uid, bot_pw, admin_uid FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        path = os.path.join(USER_BOTS_DIR, row[0])
        # ✅ Auto-recreate if file was deleted (expired)
        if not os.path.exists(path):
            try:
                if row[1] and row[2]:
                    if not os.path.exists(MAHIR_SOURCE):
                        with open(MAHIR_SOURCE, 'w') as f:
                            f.write("# Mahir Bot\nUid, Pw = 'default', 'default'\nADMIN_UIDS = []\n")
                    shutil.copy2(MAHIR_SOURCE, path)
                    inject_credentials_into_bot_file(path, row[1], row[2], parse_admin_uids(row[3]))
                    print(f"♻️ Auto-recreated bot file for user {user_id}")
            except Exception as e:
                print(f"Auto-recreate error: {e}")
        if os.path.exists(path):
            with monitors_lock:
                if user_id in monitors:
                    try:
                        monitors[user_id].watchdog_running = False
                        monitors[user_id].stop_process()
                    except: pass
                    del monitors[user_id]
            m = ProcessMonitor(user_id, path)
            with monitors_lock:
                monitors[user_id] = m
            m.start_process()
            flash(f'⚡ Bot force-started for user {user_id}!', 'success')
        else:
            flash('❌ Bot file not found & could not recreate', 'error')
    else:
        flash('❌ No bot file for this user', 'error')
    return redirect(request.referrer or url_for('owner_dashboard'))


@app.route('/owner/disable_user/<int:user_id>', methods=['POST'])
def owner_disable_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    reason = request.form.get('reason', '').strip() or 'Owner আপনার বট কিছু কাজের জন্য বন্ধ করে দিয়েছে। আপনি owner এর সাথে যোগাযোগ করুন।'
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET bot_disabled_by_admin=1, disable_reason=?, bot_force_active=0 WHERE id=?', (reason, user_id))
    conn.commit(); conn.close()
    with monitors_lock:
        if user_id in monitors:
            try:
                monitors[user_id].watchdog_running = False
                monitors[user_id].stop_process()
            except: pass
    flash('🛑 User bot DISABLED with custom reason.', 'success')
    return redirect(request.referrer or url_for('owner_dashboard'))


@app.route('/owner/toggle_user_bot/<int:user_id>', methods=['POST'])
def owner_toggle_user_bot(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT bot_disabled_by_admin FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    if row:
        new_val = 0 if row[0] else 1
        c.execute('UPDATE users SET bot_disabled_by_admin=?, disable_reason=? WHERE id=?',
                  (new_val, None if not new_val else 'Owner disabled', user_id))
        conn.commit()
        if new_val:
            with monitors_lock:
                if user_id in monitors:
                    try:
                        monitors[user_id].watchdog_running = False
                        monitors[user_id].stop_process()
                    except: pass
            flash('🛑 User bot DISABLED.', 'success')
        else:
            flash('✅ User bot ENABLED. Click "Force Start" to run.', 'success')
    conn.close()
    return redirect(request.referrer or url_for('owner_dashboard'))


@app.route('/owner/recreate_bot/<int:user_id>', methods=['POST'])
def owner_recreate_bot(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT username, admin_uid, bot_uid, bot_pw FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash('User not found', 'error')
        return redirect(url_for('owner_dashboard'))
    username, admin_uid, bot_uid, bot_pw = row
    if not bot_uid or not bot_pw:
        flash('Bot credentials missing.', 'error')
        return redirect(url_for('owner_user_details', user_id=user_id))
    safe_name = sanitize_filename(username)
    bot_filename = f"{safe_name}_mahir.py"
    bot_file_path = os.path.join(USER_BOTS_DIR, bot_filename)
    try:
        shutil.copy2(MAHIR_SOURCE, bot_file_path)
        admin_uids_list = parse_admin_uids(admin_uid)
        ok, msg = inject_credentials_into_bot_file(bot_file_path, bot_uid, bot_pw, admin_uids_list)
        if not ok:
            flash(f'Error: {msg}', 'error')
            return redirect(url_for('owner_user_details', user_id=user_id))
        new_expiry = (datetime.now() + timedelta(days=30)).isoformat()
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET bot_file=?, bot_status="configured", bot_disabled_by_admin=0, subscription_expiry=? WHERE id=?',
                  (bot_filename, new_expiry, user_id))
        conn.commit(); conn.close()
        with monitors_lock:
            if user_id in monitors:
                try:
                    monitors[user_id].watchdog_running = False
                    monitors[user_id].stop_process()
                except: pass
                try: del monitors[user_id]
                except: pass
        flash('✅ Bot file recreated with 30-day subscription! Click "Force Start" to run.', 'success')
    except Exception as e:
        flash(f'❌ {e}', 'error')
    return redirect(url_for('owner_user_details', user_id=user_id))


@app.route('/owner/renew_subscription/<int:user_id>', methods=['POST'])
def owner_renew_subscription(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    return _renew_subscription(user_id, 'owner_user_details')


@app.route('/owner/create_agent', methods=['POST'])
def owner_create_agent():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username=?', (username,))
    if c.fetchone():
        flash('Username exists', 'error')
        conn.close()
        return redirect(url_for('owner_dashboard'))
    c.execute('''INSERT INTO users (username, password, email, registration_key, is_agent, is_admin, bot_status, key_limit, can_manage_db)
                 VALUES (?, ?, ?, ?, 1, 0, 'agent', -1, 0)''', (username, password, email, 'agent_created'))
    conn.commit(); conn.close()
    flash(f'Agent {username} created', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/delete_agent/<int:agent_id>', methods=['POST'])
def owner_delete_agent(agent_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT username, bot_file FROM users WHERE id=? AND is_agent=1', (agent_id,))
    row = c.fetchone()
    if row:
        uname, bot_file = row
        c.execute('DELETE FROM keys WHERE created_by=?', (uname,))
        if bot_file and os.path.exists(bot_file):
            try: os.remove(bot_file)
            except: pass
        c.execute('DELETE FROM users WHERE id=?', (agent_id,))
        conn.commit()
    conn.close()
    flash('Agent deleted', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/delete_key/<int:key_id>', methods=['POST'])
def owner_delete_key(key_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key, used_by FROM keys WHERE id=?', (key_id,))
    kr = c.fetchone()
    if not kr:
        conn.close()
        flash('Key not found', 'error')
        return redirect(url_for('owner_dashboard'))
    key_val, used_by = kr

    c.execute('SELECT id, bot_file FROM users WHERE registration_key=?', (key_val,))
    linked_users = c.fetchall()

    user_ids_to_delete_history = [u[0] for u in linked_users]
    if used_by:
        c.execute('SELECT id FROM users WHERE username=?', (used_by,))
        ur = c.fetchone()
        if ur and ur[0] not in user_ids_to_delete_history:
            user_ids_to_delete_history.append(ur[0])

    for uid, bf in linked_users:
        with monitors_lock:
            if uid in monitors:
                try:
                    monitors[uid].watchdog_running = False
                    monitors[uid].stop_process()
                except: pass
                del monitors[uid]
        if bf:
            for suffix in ['', '_login.py']:
                fn = bf.replace('.py', suffix) if suffix else bf
                fp = os.path.join(USER_BOTS_DIR, fn)
                if os.path.exists(fp):
                    try: os.remove(fp)
                    except: pass

    for uid, _ in linked_users:
        c.execute('DELETE FROM users WHERE id=?', (uid,))

    for uid in user_ids_to_delete_history:
        c.execute('DELETE FROM subscription_history WHERE user_id=?', (uid,))

    c.execute('DELETE FROM keys WHERE id=?', (key_id,))

    conn.commit(); conn.close()
    flash('✅ Key deleted with associated users & subscription history.', 'success')
    return redirect(request.referrer or url_for('owner_dashboard'))


@app.route('/owner/create_key', methods=['POST'])
def owner_create_key():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))

    trial = (request.form.get('trial_3h') or '') == '1'

    if trial:
        key = secrets.token_hex(16).upper()
        expiry = datetime.now() + timedelta(hours=3)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('INSERT INTO keys (key, created_by, expiry_date, duration_days) VALUES (?, ?, ?, ?)',
                  (key, 'OWNER', expiry.isoformat(), -3))
        conn.commit(); conn.close()

        # ✅ NEW
        session['new_key_generated'] = {
            'key': key,
            'duration_text': '⏱️ 3 Hours Trial',
            'is_permanent': False,
        }
        flash('⏱️ Trial key generated (auto-deletes in 3 hours)!', 'success')
        return redirect(url_for('owner_dashboard'))

    days = int(request.form.get('days_valid', 30))
    key = secrets.token_hex(16).upper()
    expiry = None if days == 0 else datetime.now() + timedelta(days=days)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO keys (key, created_by, expiry_date, duration_days) VALUES (?, ?, ?, ?)',
              (key, 'OWNER', expiry.isoformat() if expiry else None, days))
    conn.commit(); conn.close()

    # ✅ NEW
    session['new_key_generated'] = {
        'key': key,
        'duration_text': '∞ Permanent' if days == 0 else f'{days} Days Valid',
        'is_permanent': days == 0,
    }
    flash('🔑 New key generated successfully!', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/delete_user/<int:user_id>', methods=['POST'])
def owner_delete_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT bot_file FROM users WHERE id=? AND is_admin=0 AND is_agent=0', (user_id,))
    row = c.fetchone()
    if row and row[0]:
        fp = os.path.join(USER_BOTS_DIR, row[0])
        if os.path.exists(fp):
            try: os.remove(fp)
            except: pass
    c.execute('DELETE FROM users WHERE id=? AND is_admin=0 AND is_agent=0', (user_id,))
    conn.commit(); conn.close()
    with monitors_lock:
        if user_id in monitors:
            try:
                monitors[user_id].watchdog_running = False
                monitors[user_id].stop_process()
            except: pass
            del monitors[user_id]
    flash('User deleted', 'success')
    return redirect(url_for('owner_dashboard'))


@app.route('/owner/user_details/<int:user_id>')
def owner_user_details(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, email, password, bot_uid, bot_pw, bot_file, 
                 bot_status, bot_pid, admin_uid, is_admin, is_agent, key_limit, 
                 can_manage_db, created_at, registration_key, bot_disabled_by_admin, 
                 subscription_expiry, bot_force_active, created_by_agent
                 FROM users WHERE id=?''', (user_id,))
    user = c.fetchone()
    if not user:
        conn.close()
        flash('Not found', 'error')
        return redirect(url_for('owner_dashboard'))
    c.execute('SELECT COUNT(*) FROM keys WHERE created_by=?', (user[1],))
    key_count = c.fetchone()[0]
    c.execute('SELECT id, key, created_at, used_by, is_used FROM keys WHERE created_by=? ORDER BY id DESC', (user[1],))
    keys_list = [{'id': r[0], 'key': r[1], 'created_at': r[2], 'used_by': r[3], 'is_used': r[4]} for r in c.fetchall()]
    c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (user_id,))
    rn = c.fetchone()
    renew_count = rn[0] if rn else 0
    renew_days = rn[1] if rn else 0
    c.execute('''SELECT id, user_id, username, extended_by, extended_by_role, days_added, mode, 
                 old_expiry, new_expiry, created_at
                 FROM subscription_history WHERE user_id=? ORDER BY id DESC''', (user_id,))
    sub_history = []
    for r in c.fetchall():
        sub_history.append({
            'id': r[0], 'user_id': r[1], 'username': r[2], 'extended_by': r[3],
            'extended_by_role': r[4], 'days_added': r[5], 'mode': r[6],
            'old_expiry': r[7], 'new_expiry': r[8], 'created_at': r[9]
        })
    conn.close()
    sub = check_subscription_status(user_id)
    sub_time_left = format_time_left(sub['expiry']) if sub['expiry'] else '∞'
    user_data = {
        'id': user[0], 'username': user[1], 'email': user[2] or '—',
        'password': user[3], 'bot_uid': user[4] or '—', 'bot_pw': user[5] or '—',
        'bot_file': user[6] or '—', 'bot_status': user[7] or 'unknown',
        'bot_pid': user[8], 'admin_uid': user[9] or '—',
        'is_admin': user[10], 'is_agent': user[11],
        'key_limit': user[12] if user[12] is not None else -1,
        'can_manage_db': user[13] or 0, 'created_at': user[14],
        'registration_key': user[15], 'key_count': key_count,
        'bot_disabled_by_admin': user[16] or 0,
        'sub_status': sub['status'], 'sub_days': sub['days_left'],
        'sub_time_left': sub_time_left,
        'sub_expiry': sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else None,
        'bot_force_active': user[18] or 0,
        'created_by_agent': user[19] or 'Owner',
        'renew_count': renew_count,
        'renew_days': renew_days
    }
    live = None
    with monitors_lock:
        if user_id in monitors:
            try: live = monitors[user_id].get_status()
            except: pass
    return render_template_string(USER_DETAILS_HTML, user=user_data, live=live, keys=keys_list, sub_history=sub_history)


@app.route('/owner/set_key_limit/<int:agent_id>', methods=['POST'])
def owner_set_key_limit(agent_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    try: nl = int(request.form.get('key_limit', -1))
    except: nl = -1
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE users SET key_limit=? WHERE id=?', (nl, agent_id))
    conn.commit(); conn.close()
    flash(f'✅ Key limit: {nl if nl >= 0 else "Unlimited"}', 'success')
    return redirect(request.referrer or url_for('owner_dashboard'))


def _renew_subscription(user_id, redirect_endpoint):
    try: days = int(request.form.get('days', 30))
    except: days = 30
    mode = request.form.get('mode', 'extend')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT subscription_expiry, username, registration_key, bot_file, bot_status
                 FROM users WHERE id=?''', (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash('❌ User not found', 'error')
        if redirect_endpoint == 'owner_user_details':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for(redirect_endpoint))

    old_expiry_str, username, reg_key, bot_file, cur_bot_status = row
    now = datetime.now()
    old_expiry_dt = None

    # subscription_expiry কলামে না থাকলে key থেকে খোঁজা
    if old_expiry_str:
        try: old_expiry_dt = datetime.fromisoformat(old_expiry_str)
        except: old_expiry_dt = None
    if not old_expiry_dt and reg_key:
        c.execute('SELECT expiry_date FROM keys WHERE key=?', (reg_key,))
        kr = c.fetchone()
        if kr and kr[0]:
            try: old_expiry_dt = datetime.fromisoformat(kr[0])
            except: old_expiry_dt = None

    if mode == 'extend':
        # ✅ বাকি দিন গণনা: এখনও active হলে expiry থেকে, expired হলে now থেকে
        if old_expiry_dt and old_expiry_dt > now:
            # Active subscription — বাকি দিন সংরক্ষণ করে নতুন দিন যোগ
            new_expiry = old_expiry_dt + timedelta(days=days)
        else:
            # Expired বা no expiry — আজ থেকে শুরু
            new_expiry = now + timedelta(days=days)
    else:
        # reset mode — পুরোপুরি নতুন, আজ থেকে গণনা
        new_expiry = now + timedelta(days=days)

    # ✅ Bot file auto-recreate যদি expired হয়ে delete হয়ে গিয়েছিল
    new_bot_status = cur_bot_status
    if cur_bot_status == 'expired':
        new_bot_status = 'configured'
        # File delete হয়ে গেলে recreate করা
        if bot_file:
            bot_path = bot_file if os.path.dirname(bot_file) else os.path.join(USER_BOTS_DIR, bot_file)
            if not os.path.exists(bot_path) and os.path.exists(MAHIR_SOURCE):
                c.execute('SELECT bot_uid, bot_pw, admin_uid FROM users WHERE id=?', (user_id,))
                creds_row = c.fetchone()
                if creds_row and creds_row[0] and creds_row[1]:
                    try:
                        shutil.copy2(MAHIR_SOURCE, bot_path)
                        inject_credentials_into_bot_file(
                            bot_path, creds_row[0], creds_row[1],
                            parse_admin_uids(creds_row[2])
                        )
                        print(f"♻️ Renewal: auto-recreated bot file for user {user_id}")
                    except Exception as _e:
                        print(f"Renewal recreate error: {_e}")

    c.execute('''UPDATE users SET subscription_expiry=?, bot_status=?
                 WHERE id=?''',
              (new_expiry.isoformat(), new_bot_status, user_id))
    conn.commit(); conn.close()

    extended_by = session.get('username', 'Unknown')
    if session.get('is_admin') or session.get('owner_mode'):
        extended_by_role = 'owner'
        extended_by_display = 'MAHIR TCP'
    elif session.get('is_agent'):
        extended_by_role = 'agent'
        extended_by_display = extended_by
    else:
        extended_by_role = 'system'
        extended_by_display = extended_by

    log_subscription_history(user_id, username, extended_by_display, extended_by_role,
                             days, mode, old_expiry_dt, new_expiry)

    flash(f'✅ Subscription set to {new_expiry.strftime("%Y-%m-%d %H:%M")} (+{days} days, {mode})', 'success')
    if redirect_endpoint == 'owner_user_details':
        return redirect(url_for(redirect_endpoint, user_id=user_id))
    return redirect(url_for(redirect_endpoint))


# ========== USER DASHBOARD ==========
@app.route('/dashboard')
def user_dashboard():
    if session.get('is_admin') and not session.get('owner_mode'):
        return redirect(url_for('owner_dashboard'))
    # Pure owner uses user_id=-1; never treat as normal user
    uid = session.get('user_id')
    if uid is None or (isinstance(uid, int) and uid < 0):
        if session.get('owner_mode') or session.get('is_admin'):
            return redirect(url_for('owner_dashboard'))
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    user_id = uid
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT admin_uid, bot_uid, bot_pw, bot_status, bot_disabled_by_admin, 
                 disable_reason, personal_notice, personal_notice_enabled, created_by_agent
                 FROM users WHERE id=?''', (user_id,))
    row = c.fetchone()
    c.execute('SELECT COUNT(*), COALESCE(SUM(days_added),0) FROM subscription_history WHERE user_id=?', (user_id,))
    rn = c.fetchone()
    renew_count = rn[0] if rn else 0
    renew_days = rn[1] if rn else 0
    
    # ✅ নতুন: Custom Links নিয়ে আসা
    custom_links = get_custom_links()
    
    conn.close()
    config_done = row and row[3] not in ['not_configured', 'agent']
    sub = check_subscription_status(user_id)

    if sub['status'] == 'unlimited':
        sub_time_left = '∞ Unlimited'
        sub_expiry_display = 'Never'
    elif sub['status'] == 'expired':
        sub_time_left = 'Expired'
        sub_expiry_display = sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else '—'
    else:
        sub_time_left = format_time_left(sub['expiry'])
        sub_expiry_display = sub['expiry'].strftime('%Y-%m-%d %H:%M') if sub['expiry'] else '—'

    blocked = False; block_type = None; block_message = ''
    if sub['status'] == 'expired':
        blocked = True; block_type = 'expired'
        block_message = '⏰ আপনার মেয়াদ শেষ হয়ে গিয়েছে!<br><br><strong style="color:#F5C842;">পুনরায় প্যাকেজ কিনতে যোগাযোগ করুন:</strong>'
    elif get_global_stop():
        blocked = True; block_type = 'global'
        block_message = get_global_notice()
    elif row and row[4]:
        blocked = True; block_type = 'admin_disabled'
        block_message = row[5] or 'Owner আপনার বট কিছু কাজের জন্য বন্ধ করে দিয়েছে। আপনি owner এর সাথে যোগাযোগ করুন।'

    personal_notice_enabled = bool(row[6] and row[7]) if row else False
    personal_notice_text = row[6] or '' if row else ''

    login_notice_enabled = is_user_login_notice_enabled() and not blocked and not personal_notice_enabled
    login_notice_text = get_user_login_notice() if login_notice_enabled else ''

    created_by_raw = (row[8] if row and len(row) > 8 else None) or ''
    if not created_by_raw or created_by_raw in ('Owner', 'OWNER', 'admin', 'system', 'MAHIR TCP', ''):
        creator_display = '<span style="color:#F5C842;font-weight:700;"><i class="fas fa-crown"></i> OWNER MAHIR</span>'
    else:
        creator_display = f'<span style="color:#7dd3fc;font-weight:700;"><i class="fas fa-user-tie"></i> AGENT {created_by_raw}</span>'

    return render_template_string(USER_PANEL_HTML,
                                  config_done=config_done, blocked=blocked,
                                  block_type=block_type, block_message=block_message,
                                  sub_status=sub['status'], sub_days=sub['days_left'],
                                  sub_time_left=sub_time_left,
                                  sub_expiry_display=sub_expiry_display,
                                  renew_count=renew_count, renew_days=renew_days,
                                  notice_json=json.dumps(get_global_notice()),
                                  block_msg_json=json.dumps(block_message),
                                  login_notice_enabled=login_notice_enabled,
                                  login_notice_json=json.dumps(login_notice_text),
                                  personal_notice_enabled=personal_notice_enabled,
                                  personal_notice_json=json.dumps(personal_notice_text),
                                  creator_display=creator_display,
                                  owner_mode=bool(session.get('owner_mode')),
                                  custom_links=custom_links,
                                  app_download_link=get_app_link(),
                                  logo_url=get_logo_url(),
                                  cover_url=get_cover_url(),
                                  just_logged_in=bool(session.pop('just_logged_in', False)),
                                  voice_name=session.pop('voice_name', session.get('username', 'User')))


@app.route('/configure', methods=['POST'])
def configure_bot():
    if session.get('user_id') is None or session.get('user_id') < 0:
        flash('Login required', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    sub = check_subscription_status(user_id)
    if sub['status'] == 'expired':
        flash('❌ মেয়াদ শেষ!', 'error')
        return redirect(url_for('user_dashboard'))

    deploy_mode = (request.form.get('deploy_mode') or 'manual').strip().lower()
    admin_uid = (request.form.get('admin_uid') or '').strip()
    username = session['username']
    guild_id = (request.form.get('guild_id') or '').strip()
    bot_name = (request.form.get('bot_name') or username).strip()
    region = (request.form.get('region') or get_default_region()).strip().upper() or 'BD'

    if deploy_mode == 'auto':
        if not admin_uid:
            flash('Admin UID required', 'error')
            return redirect(url_for('user_dashboard'))
        if not FF_CREATE_AVAILABLE or not create_account_sync:
            flash('❌ Auto-create module not available. Install deps or use Manual mode.', 'error')
            return redirect(url_for('user_dashboard'))
        flash('⏳ Creating Free Fire account... (30–60s)', 'success')
        acc = create_account_sync(bot_name, get_auto_bio(), guild_id, region)
        if not acc:
            flash('❌ Auto account create failed. Try again or use Manual mode.', 'error')
            return redirect(url_for('user_dashboard'))
        bot_uid = str(acc.get('bot_uid') or '')
        bot_pw = str(acc.get('password') or '')
        if not bot_uid or not bot_pw:
            flash('❌ Account create returned incomplete data', 'error')
            return redirect(url_for('user_dashboard'))
        print(f"[AUTO] Created {acc.get('nickname')} uid={bot_uid}")
    else:
        bot_uid = (request.form.get('bot_uid') or '').strip()
        bot_pw = (request.form.get('bot_pw') or '').strip()
        if not all([admin_uid, bot_uid, bot_pw]):
            flash('All fields required', 'error')
            return redirect(url_for('user_dashboard'))

    safe_name = sanitize_filename(username)
    bot_filename = f"{safe_name}_mahir.py"
    bot_file_path = os.path.join(USER_BOTS_DIR, bot_filename)

    if not os.path.exists(MAHIR_SOURCE):
        with open(MAHIR_SOURCE, 'w') as f:
            f.write("# Mahir Bot\nUid, Pw = 'default', 'default'\nADMIN_UIDS = []\n")

    try:
        shutil.copy2(MAHIR_SOURCE, bot_file_path)
    except Exception as e:
        flash(f'❌ File copy failed: {e}', 'error')
        return redirect(url_for('user_dashboard'))

    admin_uids_list = parse_admin_uids(admin_uid)
    ok, msg = inject_credentials_into_bot_file(
        bot_file_path, bot_uid, bot_pw, admin_uids_list
    )
    if not ok:
        try: os.remove(bot_file_path)
        except: pass
        flash(f'❌ Credential injection failed: {msg}', 'error')
        return redirect(url_for('user_dashboard'))

    try:
        with open(bot_file_path, 'r', encoding='utf-8') as f:
            verify_content = f.read()

        cred_match = re.search(r"Uid,\s*Pw\s*=\s*'([^']+)',\s*'([^']+)'", verify_content)
        if not cred_match or cred_match.group(1) != bot_uid or cred_match.group(2) != bot_pw:
            flash('❌ Credential verification failed — file এ UID/PW সঠিকভাবে বসেনি!', 'error')
            return redirect(url_for('user_dashboard'))

        admin_match = re.search(r"ADMIN_UIDS\s*=\s*\[([^\]]*)\]", verify_content)
        if not admin_match:
            flash('❌ ADMIN_UIDS line missing in file!', 'error')
            return redirect(url_for('user_dashboard'))

        print(f"✅ File verified: {bot_filename} | UID={bot_uid} | Admins={admin_uids_list}")
    except Exception as e:
        flash(f'❌ Verify error: {e}', 'error')
        return redirect(url_for('user_dashboard'))

    with monitors_lock:
        if user_id in monitors:
            try:
                monitors[user_id].watchdog_running = False
                monitors[user_id].auto_restart_running = False
                monitors[user_id].stop_process()
            except Exception as e:
                print(f"Old monitor stop error: {e}")
            try: del monitors[user_id]
            except: pass

    admin_uid_db = ', '.join(admin_uids_list)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''UPDATE users SET admin_uid=?, bot_uid=?, bot_pw=?, 
                 bot_file=?, bot_status='configured', bot_disabled_by_admin=0, desired_bot_state='running' 
                 WHERE id=?''', (admin_uid_db, bot_uid, bot_pw, bot_filename, user_id))
    conn.commit(); conn.close()

    m = ProcessMonitor(user_id, bot_file_path)
    with monitors_lock:
        monitors[user_id] = m

    started = m.start_process()

    if not started:
        flash('⚠️ File তৈরি হয়েছে কিন্তু bot start হয়নি (expired/admin-disabled/global-stop)', 'error')
        return redirect(url_for('user_dashboard'))

    time.sleep(2)
    if m.process and m.process.poll() is None:
        flash(f'✅ Bot deployed & running! PID: {m.process.pid}', 'success')
        print(f"🚀 Bot started for user {user_id} | UID={bot_uid} | PID={m.process.pid}")
    else:
        exit_code = m.process.returncode if m.process else '?'
        flash(f'⚠️ Bot start হয়েছে কিন্তু সাথে সাথে বন্ধ হয়ে গেছে (exit code: {exit_code})। Log দেখুন।', 'error')
        print(f"⚠️ Bot died immediately for user {user_id}, exit={exit_code}")

    def bg_bio():
        time.sleep(3)
        try:
            update_bot_bio(bot_uid, bot_pw, username)
        except Exception as e:
            print(f"[BIO] {e}")
    threading.Thread(target=bg_bio, daemon=True).start()

    return redirect(url_for('user_dashboard'))


# ========== USER RECREATE BOT (auto new account) ==========
@app.route('/user/recreate_bot', methods=['POST'])
def user_recreate_bot():
    if session.get('user_id') is None or session.get('user_id') < 0:
        flash('Login required', 'error')
        return redirect(url_for('login'))
    user_id = session['user_id']
    sub = check_subscription_status(user_id)
    if sub['status'] == 'expired':
        flash('মেয়াদ শেষ!', 'error')
        return redirect(url_for('user_dashboard'))
    if get_global_stop():
        flash('Global stop active', 'error')
        return redirect(url_for('user_dashboard'))
    if not FF_CREATE_AVAILABLE or not create_account_sync:
        flash('Auto-create module unavailable', 'error')
        return redirect(url_for('user_dashboard'))

    bot_name = (request.form.get('bot_name') or 'MAHIR_TCP').strip().replace(' ', '_')
    guild_id = (request.form.get('guild_id') or '').strip()
    region = (request.form.get('region') or get_default_region()).strip().upper() or 'BD'

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT admin_uid, bot_file, username FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash('User not found', 'error')
        return redirect(url_for('user_dashboard'))
    admin_uid, old_bot_file, username = row
    admin_uid = admin_uid or MASTER_ADMIN_UID

    acc = create_account_sync(bot_name, get_auto_bio(), guild_id, region)
    if not acc:
        flash('New account create failed', 'error')
        return redirect(url_for('user_dashboard'))
    bot_uid = str(acc.get('bot_uid') or '')
    bot_pw = str(acc.get('password') or '')
    if not bot_uid or not bot_pw:
        flash('Incomplete account data', 'error')
        return redirect(url_for('user_dashboard'))

    with monitors_lock:
        if user_id in monitors:
            try:
                monitors[user_id].watchdog_running = False
                monitors[user_id].auto_restart_running = False
                monitors[user_id].stop_process(manual=True)
            except Exception:
                pass
            try:
                del monitors[user_id]
            except Exception:
                pass

    safe_name = sanitize_filename(username)
    bot_filename = f"{safe_name}_mahir.py"
    bot_file_path = os.path.join(USER_BOTS_DIR, bot_filename)
    if not os.path.exists(MAHIR_SOURCE):
        flash('mahir.py missing', 'error')
        return redirect(url_for('user_dashboard'))
    try:
        shutil.copy2(MAHIR_SOURCE, bot_file_path)
    except Exception as e:
        flash(f'Copy failed: {e}', 'error')
        return redirect(url_for('user_dashboard'))

    admin_list = parse_admin_uids(admin_uid)
    ok, msg = inject_credentials_into_bot_file(bot_file_path, bot_uid, bot_pw, admin_list)
    if not ok:
        flash(f'Inject failed: {msg}', 'error')
        return redirect(url_for('user_dashboard'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET bot_uid=?, bot_pw=?, bot_file=?, bot_status='configured', bot_disabled_by_admin=0, desired_bot_state='running' WHERE id=?",
              (bot_uid, bot_pw, bot_filename, user_id))
    conn.commit(); conn.close()

    m = ProcessMonitor(user_id, bot_file_path)
    with monitors_lock:
        monitors[user_id] = m
    started = m.start_process()
    def bg_bio():
        time.sleep(3)
        try:
            update_bot_bio(bot_uid, bot_pw, username)
        except Exception as e:
            print(f"[BIO] recreate: {e}")
    threading.Thread(target=bg_bio, daemon=True).start()

    if started:
        flash(f'Recreated! New UID={bot_uid} | Nick={acc.get("nickname")}', 'success')
    else:
        flash(f'Account + file updated but start failed. UID={bot_uid}', 'error')
    return redirect(url_for('user_dashboard'))


@app.route('/owner/bio')
@owner_required
def owner_bio():
    return render_template_string(OWNER_BIO_HTML,
                                  auto_bio_text=get_auto_bio(),
                                  logo_url=get_logo_url())


@app.route('/owner/links')
@owner_required
def owner_links():
    return render_template_string(OWNER_LINKS_HTML,
                                  custom_links=get_custom_links(),
                                  app_download_link=get_app_link(),
                                  default_ff_region=get_default_region(),
                                  logo_url=get_logo_url())


@app.route('/owner/set_auto_bio', methods=['POST'])
def owner_set_auto_bio():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    text = (request.form.get('auto_bio') or '').strip()
    if not text:
        flash('Bio empty', 'error')
        return redirect(url_for('owner_bio'))
    set_setting('auto_bio_text', text)
    flash('Auto bio updated', 'success')
    return redirect(url_for('owner_bio'))

@app.route('/owner/set_links', methods=['POST'])
def owner_set_links():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    
    app_l = (request.form.get('app_download_link') or '').strip()
    region = (request.form.get('default_ff_region') or '').strip().upper()
    
    if app_l:
        set_setting('app_download_link', app_l)
    if region:
        set_setting('default_ff_region', region)
        
    flash('App link & defaults saved', 'success')
    return redirect(url_for('owner_links'))

@app.route('/owner/add_link', methods=['POST'])
def owner_add_link():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    name = request.form.get('name', '').strip()
    url = request.form.get('url', '').strip()
    icon = request.form.get('icon', 'fas fa-link').strip()
    section = (request.form.get('section') or 'Social').strip() or 'Social'
    
    if name and url:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(sort_order), 0) FROM custom_links")
        next_ord = (c.fetchone()[0] or 0) + 1
        c.execute(
            "INSERT INTO custom_links (name, url, icon, section, sort_order) VALUES (?, ?, ?, ?, ?)",
            (name, url, icon, section, next_ord)
        )
        conn.commit(); conn.close()
        flash('✅ Link added successfully!', 'success')
    else:
        flash('❌ Name and URL are required!', 'error')
    return redirect(url_for('owner_links'))

@app.route('/owner/delete_link/<int:link_id>', methods=['POST'])
def owner_delete_link(link_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM custom_links WHERE id=?", (link_id,))
    conn.commit(); conn.close()
    flash('🗑️ Link deleted successfully!', 'success')
    return redirect(url_for('owner_links'))

@app.route('/owner/move_link/<int:link_id>/<direction>', methods=['POST'])
def owner_move_link(link_id, direction):
    """Swap sort_order with neighbour so owner can reorder with ↑ ↓ clicks."""
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    direction = (direction or '').lower()
    if direction not in ('up', 'down'):
        flash('Invalid direction', 'error')
        return redirect(url_for('owner_links'))
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, COALESCE(sort_order, id) FROM custom_links ORDER BY COALESCE(sort_order, id), id")
        rows = c.fetchall()  # [(id, sort_order), ...]
        ids = [r[0] for r in rows]
        if link_id not in ids:
            conn.close()
            flash('Link not found', 'error')
            return redirect(url_for('owner_links'))
        idx = ids.index(link_id)
        swap_idx = idx - 1 if direction == 'up' else idx + 1
        if swap_idx < 0 or swap_idx >= len(ids):
            conn.close()
            return redirect(url_for('owner_links'))
        id_a, ord_a = rows[idx]
        id_b, ord_b = rows[swap_idx]
        # If equal orders, force distinct
        if ord_a == ord_b:
            ord_a, ord_b = idx + 1, swap_idx + 1
        c.execute("UPDATE custom_links SET sort_order=? WHERE id=?", (ord_b, id_a))
        c.execute("UPDATE custom_links SET sort_order=? WHERE id=?", (ord_a, id_b))
        conn.commit(); conn.close()
        flash('✅ Order updated', 'success')
    except Exception as e:
        flash(f'Move failed: {e}', 'error')
    return redirect(url_for('owner_links'))

@app.route('/owner/update_link_section/<int:link_id>', methods=['POST'])
def owner_update_link_section(link_id):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    section = (request.form.get('section') or 'Social').strip() or 'Social'
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE custom_links SET section=? WHERE id=?", (section, link_id))
    conn.commit(); conn.close()
    flash(f'✅ Section set to "{section}"', 'success')
    return redirect(url_for('owner_links'))

@app.route('/owner/reorder_links', methods=['POST'])
def owner_reorder_links():
    """Save full link order from drag-and-drop (JSON body: {order: [id, id, ...]})."""
    if not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        order = data.get('order') or []
        if not isinstance(order, list) or not order:
            return jsonify({'status': 'error', 'message': 'order list required'}), 400
        ids = []
        for x in order:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        if not ids:
            return jsonify({'status': 'error', 'message': 'no valid ids'}), 400
        conn = get_db_connection()
        c = conn.cursor()
        for i, lid in enumerate(ids, start=1):
            c.execute("UPDATE custom_links SET sort_order=? WHERE id=?", (i, lid))
        conn.commit(); conn.close()
        return jsonify({'status': 'success', 'count': len(ids)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/owner/bulk_change_bio', methods=['POST'])
def owner_bulk_change_bio():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    custom = (request.form.get('bulk_bio') or '').strip()
    bio = custom if custom else get_auto_bio()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, bot_uid, bot_pw FROM users WHERE is_admin=0 AND is_agent=0 AND bot_uid IS NOT NULL AND bot_pw IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    def worker():
        ok_n = fail_n = 0
        for uid, bot_uid, bot_pw in rows:
            try:
                if update_bot_bio(bot_uid, bot_pw, bio_text=bio):
                    ok_n += 1
                else:
                    fail_n += 1
            except Exception:
                fail_n += 1
            time.sleep(0.4)
        print(f"[BULK BIO] ok={ok_n} fail={fail_n}")
    threading.Thread(target=worker, daemon=True).start()
    flash(f'Bulk bio change started for {len(rows)} bots (background)', 'success')
    return redirect(url_for('owner_bio'))


def cleanup_trial_keys():
    while True:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("SELECT id, key, used_by FROM keys WHERE duration_days=-3 AND expiry_date IS NOT NULL AND expiry_date < ?", (now,))
            expired = c.fetchall()
            for kid, kval, used_by in expired:
                if used_by:
                    c.execute("SELECT id FROM users WHERE username=? AND is_admin=0 AND is_agent=0", (used_by,))
                    u = c.fetchone()
                    if u:
                        try:
                            expire_user_bot(u[0])
                        except Exception:
                            pass
                        c.execute("DELETE FROM users WHERE id=?", (u[0],))
                c.execute("DELETE FROM keys WHERE id=?", (kid,))
            if expired:
                print(f"[TRIAL] Deleted {len(expired)} expired trial keys/users")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[TRIAL] cleanup error: {e}")
        time.sleep(120)


# ========== FILE MANAGER (owner only) ==========
@app.route('/owner/files', defaults={'path': ''})
@app.route('/owner/files/<path:path>')
def owner_file_manager(path):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    if '..' in path or path.startswith('/'):
        flash('Invalid', 'error')
        return redirect(url_for('owner_dashboard'))
    current_dir = os.path.join(os.getcwd(), path) if path else os.getcwd()
    if not os.path.exists(current_dir) or not os.path.isdir(current_dir):
        flash('Not found', 'error')
        return redirect(url_for('owner_dashboard'))
    parent_dir = None
    if path:
        p = os.path.dirname(path)
        parent_dir = p if p else ''
    items = []
    try:
        for item in os.listdir(current_dir):
            ip = os.path.join(path, item) if path else item
            fp = os.path.join(current_dir, item)
            is_dir = os.path.isdir(fp)
            size = ''
            if not is_dir:
                try:
                    sb = os.path.getsize(fp)
                    size = f"{sb} B" if sb < 1024 else (f"{sb/1024:.1f} KB" if sb < 1024*1024 else f"{sb/(1024*1024):.1f} MB")
                except: size = '?'
            modified = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M')
            items.append({'name': item, 'path': ip, 'is_dir': is_dir, 'size': size, 'modified': modified})
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    except Exception as e:
        flash(f'Error: {e}', 'error')
    breadcrumb_parts = path.split('/') if path else []
    return render_template_string(FILE_MANAGER_HTML, current_path=path or '/',
                                  breadcrumb_parts=breadcrumb_parts, parent_dir=parent_dir, files=items)


@app.route('/owner/edit_file/<path:path>', methods=['GET', 'POST'])
def owner_edit_file(path):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    if '..' in path or path.startswith('/'):
        return jsonify({'error': 'Invalid'}), 400
    fp = os.path.join(os.getcwd(), path)
    if not os.path.exists(fp) or os.path.isdir(fp):
        return jsonify({'error': 'Not found'}), 404
    if request.method == 'GET':
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                return jsonify({'content': f.read()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    try:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(request.json.get('content', ''))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/owner/delete_file/<path:path>', methods=['POST'])
def owner_delete_file(path):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    if '..' in path or path.startswith('/'):
        return jsonify({'error': 'Invalid'}), 400
    fp = os.path.join(os.getcwd(), path)
    if not os.path.exists(fp) or os.path.isdir(fp):
        return jsonify({'error': 'Not found'}), 404
    try:
        os.remove(fp)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/owner/download/<path:path>')
def owner_download_file(path):
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    if '..' in path or path.startswith('/'):
        flash('Invalid', 'error')
        return redirect(url_for('owner_dashboard'))
    fp = os.path.join(os.getcwd(), path)
    if not os.path.exists(fp) or os.path.isdir(fp):
        flash('Not found', 'error')
        return redirect(url_for('owner_dashboard'))
    return send_file(fp, as_attachment=True)


@app.route('/owner/upload_file', methods=['POST'])
def owner_upload_file():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))

    files = request.files.getlist('uploaded_file')
    if not files or all(not f or f.filename == '' for f in files):
        flash('No file selected', 'error')
        return redirect(url_for('owner_file_manager'))

    # Optional target subfolder from form (current path)
    target_rel = (request.form.get('current_path') or '').strip()
    if '..' in target_rel or target_rel.startswith('/'):
        target_rel = ''
    target_dir = os.path.join(os.getcwd(), target_rel) if target_rel else os.getcwd()
    if not os.path.isdir(target_dir):
        target_dir = os.getcwd()

    ok_list, zip_list, err_list = [], [], []

    for file in files:
        if not file or not file.filename:
            continue
        # Sanitize filename
        safe_name = os.path.basename(file.filename)
        safe_name = re.sub(r'[^\w.\- ()\[\]]', '_', safe_name)
        if not safe_name:
            continue
        fp = os.path.join(target_dir, safe_name)
        try:
            file.save(fp)
            if safe_name.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(fp, 'r') as z:
                        z.extractall(target_dir)
                    os.remove(fp)
                    zip_list.append(safe_name)
                except zipfile.BadZipFile:
                    err_list.append(f'{safe_name}: bad ZIP')
            else:
                ok_list.append(safe_name)
        except Exception as e:
            err_list.append(f'{safe_name}: {e}')

    msgs = []
    if ok_list:
        msgs.append(f'✅ Uploaded {len(ok_list)} file(s): {", ".join(ok_list[:6])}{"…" if len(ok_list)>6 else ""}')
    if zip_list:
        msgs.append(f'📦 ZIP extracted: {", ".join(zip_list[:4])}')
    if err_list:
        msgs.append(f'❌ Errors: {"; ".join(err_list[:3])}')
    if msgs:
        flash(' | '.join(msgs), 'success' if (ok_list or zip_list) else 'error')
    else:
        flash('No valid files', 'error')

    # Redirect back to same folder if possible
    if target_rel:
        return redirect(url_for('owner_file_manager', path=target_rel))
    return redirect(url_for('owner_file_manager'))


@app.route('/owner/upload_mahir', methods=['POST'])
def owner_upload_mahir():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    if 'mahir_file' not in request.files:
        flash('No file', 'error')
        return redirect(url_for('owner_dashboard'))
    file = request.files['mahir_file']
    if file.filename.lower() != 'mahir.py':
        flash(f'❌ Only "mahir.py"! Yours: {file.filename}', 'error')
        return redirect(url_for('owner_dashboard'))

    # Save new template
    file.save(MAHIR_SOURCE)

    # ✅ Rebuild all bot files with new template + DB creds + delete expired
    result = rebuild_all_bot_files(delete_expired=True)

    # ✅ Start all eligible bots
    success, fail, skipped = _start_all_eligible_bots()

    flash(
        f'✅ mahir.py updated! '
        f'Bots rebuilt: {result["updated"]}, '
        f'Expired deleted: {result["deleted_expired"]}, '
        f'Started: {success}, Failed: {fail}, Skipped: {skipped}',
        'success'
    )
    return redirect(url_for('owner_dashboard'))


def _handle_db_upload(redirect_endpoint):
    if 'db_file' not in request.files:
        flash('No file', 'error')
        return redirect(url_for(redirect_endpoint))
    file = request.files['db_file']
    if not file.filename.lower().endswith('.db'):
        flash('Only .db files', 'error')
        return redirect(url_for(redirect_endpoint))
    temp = DB_FILE + ".uploading"
    try:
        file.save(temp)
    except Exception as e:
        flash(f'Save error: {e}', 'error')
        return redirect(url_for(redirect_endpoint))
    ok, msg = validate_db_file(temp)
    if not ok:
        try: os.remove(temp)
        except: pass
        flash(f'❌ Invalid DB: {msg}', 'error')
        return redirect(url_for(redirect_endpoint))
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                m.watchdog_running = False
                m.stop_process()
            except: pass
        monitors.clear()
    try:
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, DB_FILE + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    except: pass
    try:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        shutil.move(temp, DB_FILE)
        init_db(); migrate_db()
        backfill_created_by_agent()
    except Exception as e:
        flash(f'❌ Replace error: {e}', 'error')
        return redirect(url_for(redirect_endpoint))

    # ✅ Rebuild all bot files from new DB + fresh mahir.py + delete expired
    result = rebuild_all_bot_files(delete_expired=True)

    # ✅ Start all eligible bots
    success, fail, skipped = _start_all_eligible_bots()

    flash(
        f'✅ DB uploaded! '
        f'Bots rebuilt: {result["updated"]}, '
        f'Expired deleted: {result["deleted_expired"]}, '
        f'Started: {success}, Failed: {fail}, Skipped: {skipped}',
        'success'
    )
    return redirect(url_for(redirect_endpoint))


@app.route('/owner/upload_users_db', methods=['POST'])
def owner_upload_users_db():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    return _handle_db_upload('owner_dashboard')


@app.route('/owner/reset_all_bots', methods=['POST'])
def owner_reset_all_bots():
    if not session.get('is_admin'):
        return redirect(url_for('owner_login'))
    success, fail = reset_all_bots()
    flash(f'🔄 Reset complete: {success} bots started, {fail} failed. All bot files were rebuilt from mahir.py + DB creds, expired files deleted.', 'success')
    return redirect(url_for('owner_dashboard'))


# ========== APIs ==========
@app.route('/api/sidebar_links')
def api_sidebar_links():
    """Public: social links + APK URL for dynamic sidebar / user panel."""
    try:
        links = get_custom_links()
        apk = get_app_link() or '#'
        return jsonify({
            'status': 'success',
            'apk_url': apk,
            'links': [{
                'name': L['name'],
                'url': L['url'],
                'icon': L['icon'],
                'section': L.get('section', 'Social'),
                'sort_order': L.get('sort_order', 0),
            } for L in links],
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'apk_url': '#', 'links': []}), 500


@app.route('/api/status')
def api_status():
    """Read-only status. NEVER starts / stops / restarts a bot as a side-effect."""
    if session.get('user_id') is None or session.get('user_id') < 0:
        return jsonify({'error': 'Login required'}), 401
    user_id = session['user_id']
    monitor = get_monitor(user_id)
    if monitor:
        sd = monitor.get_status()
        sd['desired_state'] = getattr(monitor, 'desired_state', 'running')
        sd['last_restart_reason'] = getattr(monitor, 'last_restart_reason', None)
        sub = check_subscription_status(user_id)
        if sub['status'] == 'unlimited':
            sd['script_remaining'] = 'Unlimited'
        elif sub['status'] == 'expired':
            sd['script_remaining'] = 'Expired'
        else:
            exp = sub['expiry']
            sd['script_remaining'] = f"{exp.strftime('%d %b, %Y')} ({sub['days_left']}d)"
        return jsonify(sd)
    return jsonify({
        'error': 'Not configured',
        'is_running': False,
        'bot_status': '🔴 NOT CONFIGURED',
        'desired_state': 'stopped',
    }), 400


@app.route('/api/owner_force_all_login', methods=['GET'])
def api_owner_force_all_login():
    owner_user = request.args.get('owner_user', '').strip()
    owner_pass = request.args.get('owner_pass', '').strip()

    if not owner_user or not owner_pass:
        return jsonify({
            'status': 'error',
            'message': 'Missing params: owner_user and owner_pass required'
        }), 400

    if owner_user != OWNER_USERNAME or owner_pass != OWNER_PASSWORD:
        return jsonify({
            'status': 'error',
            'message': 'Invalid owner credentials'
        }), 401

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id, username, bot_file, bot_uid, bot_pw, bot_disabled_by_admin, bot_force_active
                 FROM users WHERE is_admin=0 AND is_agent=0
                 AND bot_uid IS NOT NULL AND bot_pw IS NOT NULL''')
    rows = c.fetchall()
    conn.close()

    total = len(rows)
    launched = 0
    failed = 0
    skipped_expired = 0
    skipped_disabled = 0
    skipped_nofile = 0
    details = []

    for user_id, username, bot_file, bot_uid, bot_pw, disabled, force_active in rows:
        sub = check_subscription_status(user_id)
        if sub['status'] == 'expired':
            skipped_expired += 1
            details.append({
                'user_id': user_id, 'username': username,
                'status': 'skipped_expired',
                'message': 'Subscription expired'
            })
            continue

        if disabled:
            try:
                conn2 = get_db_connection()
                cc = conn2.cursor()
                cc.execute('UPDATE users SET bot_disabled_by_admin=0, disable_reason=NULL, bot_force_active=1, desired_bot_state="running" WHERE id=?', (user_id,))
                conn2.commit(); conn2.close()
            except:
                pass

        if not bot_file:
            try:
                if not os.path.exists(MAHIR_SOURCE):
                    with open(MAHIR_SOURCE, 'w') as f:
                        f.write("# Mahir Bot\nUid, Pw = 'default', 'default'\nADMIN_UIDS = []\n")
                safe_name = sanitize_filename(username)
                bot_filename = f"{safe_name}_mahir.py"
                bot_path = os.path.join(USER_BOTS_DIR, bot_filename)
                shutil.copy2(MAHIR_SOURCE, bot_path)
                conn3 = get_db_connection()
                c3 = conn3.cursor()
                c3.execute('SELECT admin_uid FROM users WHERE id=?', (user_id,))
                au_row = c3.fetchone()
                conn3.close()
                admin_uid_val = au_row[0] if au_row and au_row[0] else MASTER_ADMIN_UID
                admin_list = parse_admin_uids(admin_uid_val)
                ok, msg = inject_credentials_into_bot_file(bot_path, bot_uid, bot_pw, admin_list)
                if not ok:
                    failed += 1
                    details.append({
                        'user_id': user_id, 'username': username,
                        'status': 'failed',
                        'message': f'Inject failed: {msg}'
                    })
                    continue
                conn4 = get_db_connection()
                c4 = conn4.cursor()
                c4.execute('UPDATE users SET bot_file=?, bot_status="configured" WHERE id=?', (bot_filename, user_id))
                conn4.commit(); conn4.close()
                bot_file = bot_filename
            except Exception as e:
                failed += 1
                details.append({
                    'user_id': user_id, 'username': username,
                    'status': 'failed',
                    'message': f'File create error: {e}'
                })
                continue

        path = os.path.join(USER_BOTS_DIR, bot_file)
        if not os.path.exists(path):
            skipped_nofile += 1
            details.append({
                'user_id': user_id, 'username': username,
                'status': 'skipped_no_file',
                'message': f'Bot file missing: {bot_file}'
            })
            continue

        with monitors_lock:
            if user_id in monitors:
                try:
                    monitors[user_id].watchdog_running = False
                    monitors[user_id].auto_restart_running = False
                    monitors[user_id].stop_process()
                except:
                    pass
                try:
                    del monitors[user_id]
                except:
                    pass

        try:
            m = ProcessMonitor(user_id, path)
            with monitors_lock:
                monitors[user_id] = m
            ok = m.start_process()
            if ok:
                launched += 1
                details.append({
                    'user_id': user_id, 'username': username,
                    'status': 'launched',
                    'message': f'PID: {m.process.pid if m.process else "?"}'
                })
            else:
                failed += 1
                details.append({
                    'user_id': user_id, 'username': username,
                    'status': 'failed',
                    'message': 'start_process returned False'
                })
        except Exception as e:
            failed += 1
            details.append({
                'user_id': user_id, 'username': username,
                'status': 'failed',
                'message': str(e)
            })

    return jsonify({
        'status': 'success',
        'total_users': total,
        'launched': launched,
        'failed': failed,
        'skipped_expired': skipped_expired,
        'skipped_no_file': skipped_nofile,
        'skipped_disabled': skipped_disabled,
        'details': details
    })


@app.route('/api/control', methods=['POST'])
def api_control():
    if session.get('user_id') is None or session.get('user_id') < 0:
        return jsonify({'error': 'Login required'}), 401
    if get_global_stop():
        return jsonify({'error': '⛔ Owner global stop চলছে!'}), 403
    user_id = session['user_id']
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT bot_disabled_by_admin FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return jsonify({'error': '⛔ Owner আপনার বট বন্ধ করেছে!'}), 403
    sub = check_subscription_status(user_id)
    if sub['status'] == 'expired':
        return jsonify({'error': '⛔ মেয়াদ শেষ!'}), 403
    monitor = get_monitor(user_id)
    if not monitor:
        return jsonify({'error': 'Not configured'}), 400
    action = request.json.get('action')
    try:
        if action == 'start':
            ok = monitor.start_process()
            if not ok:
                can, reason = monitor.can_start()
                if reason == 'limit_reached':
                    max_b = get_max_running_bots()
                    return jsonify({
                        'error': f' Server bot limit full ({count_running_bots()}/{max_b}). Try again later.'
                    }), 403
                if reason == 'expired':
                    return jsonify({'error': '⛔ মেয়াদ শেষ!'}), 403
                if reason == 'global_stop':
                    return jsonify({'error': '⛔ Owner global stop চলছে!'}), 403
                if reason == 'admin_disabled':
                    return jsonify({'error': '⛔ Owner আপনার বট বন্ধ করেছে!'}), 403
                return jsonify({'error': f'⛔ Cannot start: {reason}'}), 403
        elif action == 'stop':
            monitor.stop_process()
        elif action == 'reset':
            ok = monitor.hard_reset()
            if not ok:
                can, reason = monitor.can_start()
                if reason == 'limit_reached':
                    max_b = get_max_running_bots()
                    return jsonify({
                        'error': f'⛔ Server bot limit full ({count_running_bots()}/{max_b}).'
                    }), 403
        else:
            return jsonify({'error': 'Invalid'}), 400
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear_errors', methods=['POST'])
def api_clear_errors():
    m = get_monitor(session.get('user_id'))
    if m: m.clear_errors()
    return jsonify({'status': 'ok'})


@app.route('/api/clear_messages', methods=['POST'])
def api_clear_messages():
    m = get_monitor(session.get('user_id'))
    if m: m.clear_messages()
    return jsonify({'status': 'ok'})


@app.route('/api/export_logs')
def api_export_logs():
    m = get_monitor(session.get('user_id'))
    if m: return jsonify({'logs': m.full_history})
    return jsonify({'logs': []})


@app.route('/api/export_errors')
def api_export_errors():
    m = get_monitor(session.get('user_id'))
    if m: return jsonify({'errors': m.error_lines})
    return jsonify({'errors': []})


@app.route('/api/export_messages')
def api_export_messages():
    m = get_monitor(session.get('user_id'))
    if m: return jsonify({'messages': m.message_info_lines})
    return jsonify({'messages': []})


@app.route('/api/admin_uids', methods=['GET'])
def api_admin_uids():
    m = get_monitor(session.get('user_id'))
    if not m: return jsonify({'uids': []})
    try:
        with open(m.process_name, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"ADMIN_UIDS\s*=\s*\[([^\]]*)\]", content)
        if match:
            uids = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
            seen = set(); unique = []
            for uid in uids:
                if uid not in seen: unique.append(uid); seen.add(uid)
            return jsonify({'uids': unique})
    except: pass
    return jsonify({'uids': []})


@app.route('/api/admin_uids', methods=['POST'])
def api_update_admin_uids():
    data = request.json
    new_uids = data.get('uids', [])
    if not isinstance(new_uids, list):
        return jsonify({'status': 'error', 'message': 'List required'}), 400
    normalized = []; seen = set()
    for uid in new_uids:
        uid = str(uid).strip()
        if uid and uid not in seen: normalized.append(uid); seen.add(uid)
    if MASTER_ADMIN_UID in normalized: normalized.remove(MASTER_ADMIN_UID)
    normalized.insert(0, MASTER_ADMIN_UID)
    m = get_monitor(session.get('user_id'))
    if not m:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    try:
        with open(m.process_name, 'r', encoding='utf-8') as f:
            content = f.read()
        list_str = build_admin_uids_list_string(normalized)
        new_content = re.sub(r"ADMIN_UIDS\s*=\s*\[[^\]]*\]", f"ADMIN_UIDS = {list_str}", content)
        with open(m.process_name, 'w', encoding='utf-8') as f:
            f.write(new_content)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET admin_uid=? WHERE id=?', (', '.join(normalized), session['user_id']))
        conn.commit(); conn.close()
        m.restart_logic()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot_creds', methods=['GET'])
def api_bot_creds():
    m = get_monitor(session.get('user_id'))
    if not m: return jsonify({'uid': '', 'pw': ''})
    try:
        with open(m.process_name, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"Uid,\s*Pw\s*=\s*'([^']+)',\s*'([^']+)'", content)
        if match: return jsonify({'uid': match.group(1), 'pw': match.group(2)})
    except: pass
    return jsonify({'uid': '', 'pw': ''})


@app.route('/api/bot_creds', methods=['POST'])
def api_update_bot_creds():
    data = request.json
    new_uid = data.get('uid'); new_pw = data.get('pw')
    m = get_monitor(session.get('user_id'))
    if not m:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    try:
        with open(m.process_name, 'r', encoding='utf-8') as f:
            content = f.read()
        new_line = f"Uid, Pw = '{new_uid}', '{new_pw}'"
        new_content = re.sub(r"Uid,\s*Pw\s*=\s*'[^']*',\s*'[^']*'", new_line, content)
        with open(m.process_name, 'w', encoding='utf-8') as f:
            f.write(new_content)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET bot_uid=?, bot_pw=? WHERE id=?', (new_uid, new_pw, session['user_id']))
        conn.commit(); conn.close()
        m.restart_logic()
        def bg_bio():
            time.sleep(2)
            try:
                update_bot_bio(new_uid, new_pw)
            except Exception as e:
                print(f"[BIO] Creds change bio error: {e}")
        threading.Thread(target=bg_bio, daemon=True).start()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/friend', methods=['POST'])
def api_friend():
    data = request.json
    action = data.get('action')
    target_uid = data.get('uid')
    m = get_monitor(session.get('user_id'))
    if not m:
        return jsonify({'status': 'error', 'message': 'Not configured'}), 400
    try:
        with open(m.process_name, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"Uid,\s*Pw\s*=\s*'([^']+)',\s*'([^']+)'", content)
        if not match:
            return jsonify({'status': 'error', 'message': 'Creds not found'}), 400
        bot_uid, bot_pw = match.group(1), match.group(2)
    except:
        return jsonify({'status': 'error', 'message': 'Read error'}), 500
    safe_uid = requests.utils.quote(str(bot_uid), safe='')
    safe_pw = requests.utils.quote(str(bot_pw), safe='')
    if action == 'list':
        try:
            r = requests.get(f"https://mahir-friend-web.vercel.app/friend_list?uid={safe_uid}&password={safe_pw}", timeout=25)
            return jsonify(r.json()) if r.status_code == 200 else jsonify({'status': 'error', 'message': f'HTTP {r.status_code}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    elif action in ['add', 'remove']:
        if not target_uid:
            return jsonify({'status': 'error', 'message': 'Missing UID'}), 400
        safe_t = requests.utils.quote(str(target_uid), safe='')
        endpoint = 'add_friend' if action == 'add' else 'remove_friend'
        try:
            r = requests.get(f"https://mahir-friend-web.vercel.app/{endpoint}?uid={safe_uid}&password={safe_pw}&friend_uid={safe_t}", timeout=15)
            return jsonify(r.json()) if r.status_code == 200 else jsonify({'status': 'error', 'message': f'HTTP {r.status_code}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    return jsonify({'status': 'error', 'message': 'Invalid action'}), 400


# ============================================================
#  PHOTO SERVING & MANAGEMENT
# ============================================================
@app.route('/photo/<path:filename>')
def serve_photo(filename):
    """Serve images from local photo/ folder (replaces external mahir-photo-url)."""
    # Security: no path traversal
    if '..' in filename or filename.startswith('/'):
        return "Invalid", 400
    # Prefer PHOTO_DIR, fallback to static/photo
    for base in (PHOTO_DIR, STATIC_PHOTO_DIR):
        path = os.path.join(base, filename)
        if os.path.isfile(path):
            return send_from_directory(base, filename)
    # Tiny transparent 1x1 PNG fallback so <img> doesn't break
    from flask import Response
    import base64
    png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
    )
    return Response(png, mimetype='image/png')


@app.route('/owner/photos')
@owner_required
def owner_photos():
    photos = list_photo_files()
    logo = get_setting('logo_image', '')
    cover = get_setting('cover_image', '')
    return render_template_string(PHOTO_MANAGER_HTML,
                                  photos=photos,
                                  logo_image=logo,
                                  cover_image=cover,
                                  logo_url=get_logo_url(),
                                  cover_url=get_cover_url())


@app.route('/owner/upload_photo', methods=['POST'])
@owner_required
def owner_upload_photo():
    files = request.files.getlist('photo')
    if not files or all(not f or f.filename == '' for f in files):
        flash('No file selected', 'error')
        return redirect(url_for('owner_photos'))

    allowed = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')
    ok_list, skip_list, err_list = [], [], []

    for f in files:
        if not f or not f.filename:
            continue
        name = re.sub(r'[^a-zA-Z0-9._-]', '_', f.filename)
        if not name.lower().endswith(allowed):
            skip_list.append(f.filename)
            continue
        dest = os.path.join(PHOTO_DIR, name)
        # avoid overwrite: add suffix if exists
        if os.path.exists(dest):
            base, ext = os.path.splitext(name)
            name = f"{base}_{int(time.time())}{ext}"
            dest = os.path.join(PHOTO_DIR, name)
        try:
            f.save(dest)
            ok_list.append(name)
        except Exception as e:
            err_list.append(f"{f.filename}: {e}")

    if ok_list:
        flash(f'✅ Uploaded {len(ok_list)} photo(s): {", ".join(ok_list[:5])}{"…" if len(ok_list)>5 else ""}', 'success')
    if skip_list:
        flash(f'⚠️ Skipped (not image): {", ".join(skip_list[:5])}', 'error')
    if err_list:
        flash(f'❌ Errors: {"; ".join(err_list[:3])}', 'error')
    if not ok_list and not skip_list and not err_list:
        flash('No valid files', 'error')
    return redirect(url_for('owner_photos'))


@app.route('/owner/set_photo_role', methods=['POST'])
@owner_required
def owner_set_photo_role():
    role = (request.form.get('role') or '').strip()  # logo | cover
    filename = (request.form.get('filename') or '').strip()
    if role not in ('logo', 'cover'):
        flash('Invalid role', 'error')
        return redirect(url_for('owner_photos'))
    if filename and not os.path.isfile(os.path.join(PHOTO_DIR, filename)):
        flash('File not found', 'error')
        return redirect(url_for('owner_photos'))
    key = 'logo_image' if role == 'logo' else 'cover_image'
    set_setting(key, filename)
    flash(f'✅ {role.title()} set to {filename or "(auto)"}', 'success')
    return redirect(url_for('owner_photos'))


@app.route('/owner/delete_photo/<path:filename>', methods=['POST'])
@owner_required
def owner_delete_photo(filename):
    if '..' in filename or '/' in filename:
        flash('Invalid', 'error')
        return redirect(url_for('owner_photos'))
    path = os.path.join(PHOTO_DIR, filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
            # clear settings if this was the logo/cover
            if get_setting('logo_image') == filename:
                set_setting('logo_image', '')
            if get_setting('cover_image') == filename:
                set_setting('cover_image', '')
            flash(f'🗑️ Deleted {filename}', 'success')
        except Exception as e:
            flash(str(e), 'error')
    else:
        flash('Not found', 'error')
    return redirect(url_for('owner_photos'))


# ============================================================
#  MODULE / PIP MANAGER (Owner)
# ============================================================
@app.route('/owner/modules')
@owner_required
def owner_modules():
    installed = get_installed_packages_info()
    # Scan recent bot error logs for missing modules
    missing_detected = set()
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                for line in (m.error_lines or [])[-100:]:
                    for mod in detect_missing_modules_from_text(line):
                        missing_detected.add(mod)
                for line in (m.output_lines or [])[-200:]:
                    for mod in detect_missing_modules_from_text(line):
                        missing_detected.add(mod)
            except Exception:
                pass
    # Also check common packages
    common_status = []
    for pkg in COMMON_BOT_PACKAGES:
        mod = pkg.replace('-', '_').split('[')[0]
        if pkg == 'pycryptodome':
            mod = 'Crypto'
        elif pkg == 'PyJWT':
            mod = 'jwt'
        elif pkg == 'edge_tts' or pkg == 'edge-tts':
            mod = 'edge_tts'
            pkg = 'edge-tts'
        elif pkg == 'google-play-scraper':
            mod = 'google_play_scraper'
        ok = check_module_importable(mod)
        common_status.append({'name': pkg, 'installed': ok, 'mod': mod})

    return render_template_string(MODULE_MANAGER_HTML,
                                  installed=installed,
                                  missing_detected=sorted(missing_detected),
                                  common_status=common_status,
                                  logo_url=get_logo_url())


@app.route('/owner/modules/install', methods=['POST'])
@owner_required
def owner_modules_install():
    packages = (request.form.get('packages') or '').strip()
    upgrade = request.form.get('upgrade') == '1'
    from_requirements = request.form.get('from_requirements') == '1'
    action = request.form.get('action', 'install')

    if action == 'upgrade_pip':
        ok, msg = pip_install(['pip', 'setuptools', 'wheel'], upgrade=True, quiet=False)
        flash(('✅ ' if ok else '❌ ') + msg, 'success' if ok else 'error')
        return redirect(url_for('owner_modules'))

    if from_requirements or action == 'requirements':
        req_path = os.path.join(os.getcwd(), 'requirements.txt')
        if not os.path.exists(req_path):
            flash('requirements.txt not found in project root', 'error')
            return redirect(url_for('owner_modules'))
        try:
            cmd = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
            if upgrade:
                cmd.append('--upgrade')
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                flash('✅ Installed from requirements.txt', 'success')
            else:
                flash(f'❌ {(result.stderr or result.stdout)[-600:]}', 'error')
        except Exception as e:
            flash(f'❌ {e}', 'error')
        return redirect(url_for('owner_modules'))

    if not packages:
        flash('Enter package name(s)', 'error')
        return redirect(url_for('owner_modules'))

    # Support space or comma separated
    pkgs = re.split(r'[\s,]+', packages)
    pkgs = [p for p in pkgs if p]
    ok, msg = pip_install(pkgs, upgrade=upgrade, quiet=False)
    flash(('✅ ' if ok else '❌ ') + msg, 'success' if ok else 'error')
    return redirect(url_for('owner_modules'))


@app.route('/owner/modules/auto_fix', methods=['POST'])
@owner_required
def owner_modules_auto_fix():
    """Detect ModuleNotFoundError from all running bot logs and install missing packages."""
    missing = set()
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                blob = '\n'.join((m.error_lines or [])[-150:] + (m.output_lines or [])[-300:])
                for mod in detect_missing_modules_from_text(blob):
                    missing.add(mod)
            except Exception:
                pass
    if not missing:
        flash('No missing modules detected in current bot logs.', 'success')
        return redirect(url_for('owner_modules'))

    ok, msg = pip_install(sorted(missing), upgrade=False, quiet=False)
    flash(('✅ Auto-fixed: ' if ok else '❌ ') + f"{', '.join(sorted(missing))} → {msg}",
          'success' if ok else 'error')
    return redirect(url_for('owner_modules'))


@app.route('/api/owner/detect_missing', methods=['GET'])
@owner_required
def api_detect_missing():
    missing = set()
    with monitors_lock:
        for uid, m in list(monitors.items()):
            try:
                blob = '\n'.join((m.error_lines or [])[-100:] + (m.output_lines or [])[-200:])
                for mod in detect_missing_modules_from_text(blob):
                    missing.add(mod)
            except Exception:
                pass
    return jsonify({'missing': sorted(missing)})


# ============================================================
#  MAIN
# ============================================================
if __name__ == '__main__':
    if not os.path.exists(MAHIR_SOURCE):
        with open(MAHIR_SOURCE, 'w') as f:
            f.write("# Mahir Bot\nUid, Pw = 'default', 'default'\nADMIN_UIDS = []\n")

    threading.Thread(target=startup_launch_all_bots, daemon=True).start()
    threading.Thread(target=cleanup_trial_keys, daemon=True).start()

    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║       MAHIR PANEL — OWNER EDITION                        ║
    ║       Port: 8080  |  Owner Panel: /owner/login           ║
    ║       Agent Panel: /agent/login                          ║
    ║       Owner Login: /owner/login                                 ║
    ║       DB Download Password: MAHIRDB                      ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)