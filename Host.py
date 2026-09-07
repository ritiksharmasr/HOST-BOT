import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit

from flask import Flask
from threading import Thread

# ===== FLASK KEEP-ALIVE SERVER =====
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("🌐 Flask Keep-Alive server started.")

# ===== BOT UPTIME TRACKING =====
BOT_START_TIME = datetime.now()

def get_uptime():
    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"⏱️ {days}d {hours}h {minutes}m {seconds}s"

# ===== BOT CONFIGURATION =====
BOT_TOKEN = '8614578060:AAHnZhzwLGRhmvok-rW6C3LL_LkwL3n80w8'
OWNER_ID = 8685475945
ADMIN_ID = 8685475945
YOUR_USERNAME = '@DMcredit'
UPDATE_CHANNEL = 'https://t.me/DMcredit'

# ===== DIRECTORY SETUP =====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

# ===== USER LIMITS =====
FREE_USER_LIMIT = 4
SUBSCRIBED_USER_LIMIT = 25
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

# ===== CREATE DIRECTORIES =====
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

# ===== BOT INITIALIZATION =====
bot = telebot.TeleBot(BOT_TOKEN)

# ===== DATA STORAGE =====
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False
user_clones = {}

# ===== LOGGING SETUP =====
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== DATABASE LOCK =====
DB_LOCK = threading.Lock()

# ===== KEYBOARD LAYOUTS =====
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["🤖 Clone Bot", "📞 Contact Owner"]
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Run All Scripts"],
    ["👑 Admin Panel", "🤖 Clone Bot"],
    ["📢 Updates Channel", "📞 Contact Owner"]
]

# ===== DATABASE FUNCTIONS =====
def init_db():
    logger.info(f"🗄️ Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS clone_bots
                     (user_id INTEGER PRIMARY KEY, bot_username TEXT, token TEXT, create_time TEXT)''')
        
      
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                     (user_id INTEGER PRIMARY KEY, 
                      banned_by INTEGER,
                      banned_at TEXT)''')
        
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

# ===== LOAD DATA FROM DATABASE =====
def load_data():
    logger.info("📥 Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        c.execute('SELECT user_id, bot_username, token, create_time FROM clone_bots')
        for user_id, bot_username, token, create_time in c.fetchall():
            try:
                user_clones[user_id] = {
                    'bot_username': bot_username,
                    'token': token,
                    'create_time': datetime.fromisoformat(create_time)
                }
                logger.info(f"✅ Loaded clone bot @{bot_username} for user {user_id}")
            except ValueError:
                logger.warning(f"⚠️ Invalid create_time for clone bot of user {user_id}")

        conn.close()
        logger.info(f"✅ Data loaded: 👥 {len(active_users)} users, 💳 {len(user_subscriptions)} subscriptions, 👑 {len(admin_ids)} admins, 🤖 {len(user_clones)} clones.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

# ===== BAN DATABASE FUNCTIONS =====
def ban_user_db(user_id, banned_by):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO banned_users (user_id, banned_by, banned_at) VALUES (?, ?, ?)',
                     (user_id, banned_by, datetime.now().isoformat()))
            conn.commit()
            logger.info(f"🔒 User {user_id} banned by {banned_by}")
            return True
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            return False
        finally:
            conn.close()

def unban_user_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
            conn.commit()
            if c.rowcount > 0:
                logger.info(f"🔓 User {user_id} unbanned")
                return True
            return False
        except Exception as e:
            logger.error(f"Error unbanning user {user_id}: {e}")
            return False
        finally:
            conn.close()

def is_user_banned(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
            return c.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking ban status {user_id}: {e}")
            return False
        finally:
            conn.close()

def get_banned_users():
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
         
            c.execute('SELECT user_id, banned_by, banned_at FROM banned_users ORDER BY banned_at DESC')
            return c.fetchall()
        except Exception as e:
            logger.error(f"Error getting banned users: {e}")
            return []
        finally:
            conn.close()

# ===== ADMIN PANEL BAN/UNBAN =====
def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    markup.row(
        types.InlineKeyboardButton('🔒 Ban', callback_data='ban_user'),
        types.InlineKeyboardButton('🔓 Unban', callback_data='unban_user')
    )
    markup.row(
        types.InlineKeyboardButton('📋 Banned Users List', callback_data='banned_list')
    )   
    return markup

# ===== CLONE BOT FUNCTIONS =====
def save_clone_info(user_id, bot_username, token):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO clone_bots (user_id, bot_username, token, create_time) VALUES (?, ?, ?, ?)',
                      (user_id, bot_username, token, datetime.now().isoformat()))
            conn.commit()
            user_clones[user_id] = {
                'bot_username': bot_username,
                'token': token,
                'create_time': datetime.now()
            }
            logger.info(f"✅ Saved clone bot @{bot_username} for user {user_id}")
        except sqlite3.Error as e:
            logger.error(f"❌ SQLite error saving clone bot for {user_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error saving clone bot for {user_id}: {e}", exc_info=True)
        finally:
            conn.close()

def remove_clone_info(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM clone_bots WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_clones:
                del user_clones[user_id]
            logger.info(f"🗑️ Removed clone bot for user {user_id} from DB")
        except sqlite3.Error as e:
            logger.error(f"❌ SQLite error removing clone bot for {user_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error removing clone bot for {user_id}: {e}", exc_info=True)
        finally:
            conn.close()

# ===== INITIALIZE DATABASE AND LOAD DATA =====
init_db()
load_data()

# ===== USER FOLDER MANAGEMENT =====
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                logger.warning(f"⚠️ Process {script_info['process'].pid} for {script_key} not running/zombie. Cleaning up.")
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except Exception as log_e:
                        logger.error(f"❌ Error closing log file during zombie cleanup {script_key}: {log_e}")
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            logger.warning(f"⚠️ Process for {script_key} not found. Cleaning up.")
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                    script_info['log_file'].close()
                except Exception as log_e:
                    logger.error(f"❌ Error closing log file during cleanup {script_key}: {log_e}")
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"❌ Error checking process status for {script_key}: {e}", exc_info=True)
            return False
    return False

def kill_process_tree(process_info):
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')

    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
                logger.info(f"📜 Closed log file for {script_key}")
            except Exception as log_e:
                logger.error(f"❌ Error closing log file during kill for {script_key}: {log_e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.info(f"🔪 Killing process tree for {script_key} (PID: {pid})")

                    for child in children:
                        try:
                            child.terminate()
                        except:
                            try:
                                child.kill()
                            except:
                                pass

                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try:
                            p.kill()
                        except:
                            pass

                    try:
                        parent.terminate()
                        try:
                            parent.wait(timeout=1)
                        except:
                            parent.kill()
                    except:
                        pass

                except:
                    pass
    except Exception as e:
        logger.error(f"❌ Error killing process tree for {script_key}: {e}")

# ===== PYTHON MODULES MAPPING =====
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'psutil': 'psutil',
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False
    try:
        bot.reply_to(message, f"⚠️ Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Package `{package_name}` installed.", parse_mode='Markdown')
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install `{package_name}`.", parse_mode='Markdown')
            return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing: {str(e)}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"⚠️ Node package `{module_name}` not found. Installing...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Node package `{module_name}` installed.", parse_mode='Markdown')
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install Node package `{module_name}`.", parse_mode='Markdown')
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ Error: 'npm' not found.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
        return False

# ===== RUN PYTHON SCRIPT =====
def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"🐍 Attempt {attempt} to run Python script: {script_path}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"⚠️ File not found.")
            return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            bot.reply_to(message_obj_for_reply, f"✅ Install successful. Retrying '{file_name}'...")
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ Install failed. Cannot run '{file_name}'.")
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"⚠️ Error in script:\n```\n{error_summary}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                logger.info("⏱️ Python Pre-check timed out (>5s), imports likely OK.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except Exception as e:
                logger.error(f"❌ Error in Python pre-check: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        logger.info(f"🚀 Starting long-running Python process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"❌ Failed to open log file: {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file.")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"✅ Started Python process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting Python script: {str(e)}"
            logger.error(error_msg)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        bot.reply_to(message_obj_for_reply, f"❌ Error: {str(e)}")

# ===== RUN JAVASCRIPT SCRIPT =====
def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"📜 Attempt {attempt} to run JS script: {script_path}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"⚠️ File not found.")
            return

        if attempt == 1:
            check_command = ['node', script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                bot.reply_to(message_obj_for_reply, f"✅ NPM Install successful. Retrying '{file_name}'...")
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"❌ NPM Install failed. Cannot run '{file_name}'.")
                                return
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"⚠️ Error in JS script:\n```\n{error_summary}\n```", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                logger.info("⏱️ JS Pre-check timed out (>5s), imports likely OK.")
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, "❌ Error: 'node' not found.")
                return
            except Exception as e:
                logger.error(f"❌ Error in JS pre-check: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        logger.info(f"🚀 Starting long-running JS process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"❌ Failed to open log file: {e}")
            bot.reply_to(message_obj_for_reply, f"❌ Failed to open log file.")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"✅ Started JS process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            if log_file and not log_file.closed:
                log_file.close()
            bot.reply_to(message_obj_for_reply, "❌ Error: 'node' not found.")
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            error_msg = f"❌ Error starting JS script: {str(e)}"
            logger.error(error_msg)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        bot.reply_to(message_obj_for_reply, f"❌ Error: {str(e)}")

# ===== SAVE USER FILE =====
def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
            logger.info(f"💾 Saved file '{file_name}' for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Error saving file: {e}")
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
            logger.info(f"🗑️ Removed file '{file_name}' for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Error removing file: {e}")
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"❌ Error adding active user: {e}")
        finally:
            conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
            logger.info(f"💳 Saved subscription for {user_id}")
        except Exception as e:
            logger.error(f"❌ Error saving subscription: {e}")
        finally:
            conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions:
                del user_subscriptions[user_id]
            logger.info(f"🗑️ Removed subscription for {user_id}")
        except Exception as e:
            logger.error(f"❌ Error removing subscription: {e}")
        finally:
            conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
            logger.info(f"👑 Added admin {admin_id}")
        except Exception as e:
            logger.error(f"❌ Error adding admin: {e}")
        finally:
            conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        logger.warning("⚠️ Attempted to remove OWNER_ID from admins.")
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            if c.rowcount > 0:
                admin_ids.discard(admin_id)
                logger.info(f"🗑️ Removed admin {admin_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error removing admin: {e}")
            return False
        finally:
            conn.close()

# ===== CREATE MAIN MENU KEYBOARD =====
def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row_buttons_text in layout_to_use:
        markup.add(*[types.KeyboardButton(text) for text in row_buttons_text])
    return markup

# ===== CREATE CONTROL BUTTONS =====
def create_control_buttons(script_owner_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(
            types.InlineKeyboardButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='check_files'))
    return markup

# ===== CREATE SUBSCRIPTION PANEL =====
def create_subscription_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add', callback_data='add_subscription'),
        types.InlineKeyboardButton('➖ Remove', callback_data='remove_subscription')
    )
    markup.row(
        types.InlineKeyboardButton('📋 Subscriptions Users List', callback_data='list_subscriptions')
    )
    return markup

# ===== HANDLE ZIP FILE =====
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        logger.info(f"📦 Temp dir for zip: {temp_dir}")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"⚠️ Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)
            logger.info(f"📂 Extracted zip to {temp_dir}")

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"⚠️ Installing Python deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Python deps from `{req_file}` installed.")
            except Exception as e:
                bot.reply_to(message, f"❌ Failed to install Python deps: {e}")
                return

        if pkg_json:
            bot.reply_to(message, f"⚠️ Installing Node deps from `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Node deps from `{pkg_json}` installed.")
            except Exception as e:
                bot.reply_to(message, f"❌ Failed to install Node deps: {e}")
                return

        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files:
                main_script_name = p
                file_type = 'py'
                break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p
                    file_type = 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]
                file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]
                file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return

        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            elif os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src_path, dest_path)

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')

        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        logger.error(f"❌ Error processing zip: {e}")
        bot.reply_to(message, f"❌ Error processing zip: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

# ===== LOGIC FUNCTIONS =====
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if is_user_banned(user_id):
        bot.send_message(chat_id, "❌ **You are banned from using this bot!**\n\nContact admin if this is a mistake.", parse_mode='Markdown')
        return
    
    user_name = message.from_user.first_name
    user_last_name = message.from_user.last_name or ""
    
    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin. Try later.")
        return
    
    if user_id not in active_users:
        add_active_user(user_id)
    
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    
    if user_id == OWNER_ID:
        user_status = "👑 Owner"
    elif user_id in admin_ids:
        user_status = "⚜️ Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "💎 Premium"
            days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⌛️ Expires in: {days_left} days"
        else:
            user_status = "🆓 Free User"
            remove_subscription_db(user_id)
    else:
        user_status = "🆓 Free User"
    
    full_name = user_name
    if user_last_name:
        full_name += f" {user_last_name}"
    
    welcome_msg_text = (f"〽️ Welcome, {full_name} !\n\n"
                        f"🆔 Your User ID: `{user_id}`\n"
                        f"🔰 Your Status: {user_status}{expiry_info}\n"
                        f"📁 Files Uploaded: {current_files} / {limit_str}\n\n"
                        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"   Upload single scripts or `.zip` archives.\n\n"
                        f"👇 Use buttons or type commands.")
    
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')

def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    bot.reply_to(message, "📢 Visit our Updates Channel:", reply_markup=markup)

# ===== UPLOAD BUTTON HANDLER =====
@bot.message_handler(func=lambda message: message.text == "📤 Upload File")
def upload_file_button(message):
    user_id = message.from_user.id
    
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot!")
        return
    
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked by admin, cannot accept files.")
        return
    
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    
    msg = bot.reply_to(
    message, 
    "📤 Send your Python (`.py`), JS (`.js`), or    ZIP (`.zip`) file.",
    parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_uploaded_file)

def process_uploaded_file(message):
    user_id = message.from_user.id
    
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Upload cancelled.")
        return
    
    if not message.document:
        bot.reply_to(message, "⚠️ Please send a valid file.")
  
        return
    
    doc = message.document
    file_name = doc.file_name
    
    if not file_name:
        bot.reply_to(message, "❌ No file name.")
        return
    
    file_ext = os.path.splitext(file_name)[1].lower()
    
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Unsupported type! Only `.py`, `.js`, `.zip` allowed.")
        # Dobara poochhein
        msg = bot.reply_to(message, "📤 Send your file or type `/cancel`")
        bot.register_next_step_handler(msg, process_uploaded_file)
        return
    
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ File too large (Max: 20 MB).")
        msg = bot.reply_to(message, "📤 Send your file or type `/cancel`")
        bot.register_next_step_handler(msg, process_uploaded_file)
        return
    
    try:
        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", message.chat.id, download_wait_msg.message_id)
        
        user_folder = get_user_folder(user_id)
        
        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file_content)
            
            if file_ext == '.js':
                save_user_file(user_id, file_name, 'js')
                threading.Thread(target=run_js_script, args=(file_path, user_id, user_folder, file_name, message)).start()
            elif file_ext == '.py':
                save_user_file(user_id, file_name, 'py')
                threading.Thread(target=run_script, args=(file_path, user_id, user_folder, file_name, message)).start()
                
    except Exception as e:
        logger.error(f"❌ Error handling file: {e}")
        bot.reply_to(message, f"⚠️ Error: {str(e)}")

def _logic_check_files(message):
    user_id = message.from_user.id
    
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot!")
        return
    
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Active" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot!")
        return
    
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "⏱️ Testing speed...")
    try:
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "⚜️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "💎 Premium"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n"
                     f"⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n"
                     f"👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"❌ Error during speed test: {e}")
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "📞 Click to contact Owner:", reply_markup=markup)

def _logic_statistics(message):
    user_id = message.from_user.id
    
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot!")
        return
    
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())
    running_bots_count = 0
    
    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id, _ = script_key_iter.split('_', 1)
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
    
    stats_msg = (f"📊 Bot Live Statistics:\n\n"
                 f"👥 Total Users: {total_users}\n"
                 f"🚫 Banned Users: {len(get_banned_users())}\n"
                 f"📂 Total File Records: {total_files_records}\n"
                 f"🟢 Total Active Bots: {running_bots_count}\n"
                 f"🤖 Clone Bots: {len(user_clones)}")
    
    bot.reply_to(message, stats_msg)

def _logic_subscriptions(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    markup = create_subscription_panel()
    bot.reply_to(message, "💳 **Subscription Management**\n\nManage user subscriptions here.", reply_markup=markup, parse_mode='Markdown')

def _logic_broadcast_init(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(
        message, 
        "📢 Send message to broadcast\n to all active users.\n/Cancel"
    )
    bot.register_next_step_handler(msg, process_broadcast_message)

def _logic_toggle_lock_bot(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    lock_emoji = "🔒" if bot_locked else "✅"
    bot.reply_to(message, f"{lock_emoji} Bot has been {status}.")

def _logic_admin_panel(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(
        message,
        "👑 **Admin Panel**\n\n"
        "🔒 Ban/Unban Users:\n"
        "Select an option:",
        reply_markup=create_admin_panel(),
        parse_mode='Markdown'
    )

def _logic_run_all_scripts(message):
    admin_user_id = message.from_user.id
    admin_chat_id = message.chat.id
    
    if admin_user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    
    bot.reply_to(message, "🚀 Starting process to run all scripts...")
    started_count = 0
    attempted_users = 0
    
    all_user_files_snapshot = dict(user_files)
    
    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user:
            continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)
        
        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, message)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, message)).start()
                            started_count += 1
                    except Exception as e:
                        logger.error(f"❌ Error starting script: {e}")
    
    bot.reply_to(message, f"🚀 All Users' Scripts - Processing Complete:\n\n✅ Started: {started_count} scripts.\n👥 Users processed: {attempted_users}.")

def _logic_clone_bot(message):
    user_id = message.from_user.id
    
    if is_user_banned(user_id):
        bot.reply_to(message, "❌ You are banned from using this bot!")
        return
    
    clone_text = f"🤖 Clone Bot Service\n\n"
    clone_text += f"📊 Total Clones: {len(user_clones)}\n\n"
    clone_text += f"🎯 Features in your clone:\n"
    clone_text += f"• 📁 Unlimited file hosting\n"
    clone_text += f"• 🛡️ Security scanning\n"
    clone_text += f"• 💾 File hosting\n"
    clone_text += f"• ⚡ Auto-restart\n\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("🚀 Clone", callback_data="clone_create"),
        types.InlineKeyboardButton("🗑️ Remove", callback_data="clone_remove")
    )
    
    bot.reply_to(message, clone_text, reply_markup=markup, parse_mode="Markdown")

# ===== BROADCAST FUNCTIONS =====
def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⛔ Not authorized.")
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Broadcast cancelled.")
        return
    
    broadcast_content = message.text
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_broadcast_{message.message_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
    )
    
    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"📢 Confirm Broadcast:\n\n```\n{preview_text}\n```\nTo **{target_count}** users. Sure?", reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only.", show_alert=True)
        return
    try:
        original_message = call.message.reply_to_message
        if not original_message:
            raise ValueError("Could not retrieve original message.")
        
        broadcast_text = original_message.text if original_message.text else None
        
        bot.answer_callback_query(call.id, "📢 Starting broadcast...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...", chat_id, call.message.message_id, reply_markup=None)
        
        thread = threading.Thread(target=execute_broadcast, args=(broadcast_text, chat_id))
        thread.start()
    except Exception as e:
        logger.error(f"❌ Error in broadcast confirm: {e}")
        bot.edit_message_text(f"❌ Error starting broadcast: {e}", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "📢 Broadcast cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def execute_broadcast(broadcast_text, admin_chat_id):
    sent_count = 0
    failed_count = 0
    total_users = len(active_users)
    
    for user_id_bc in list(active_users):
        try:
            if is_user_banned(user_id_bc):
                continue
            bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            sent_count += 1
        except Exception as e:
            failed_count += 1
        time.sleep(0.1)
    
    result_msg = f"📢 **Broadcast Complete!**\n\n✅ Sent: {sent_count}\n❌ Failed: {failed_count}\n🎯 Targets: {total_users}"
    try:
        bot.send_message(admin_chat_id, result_msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"❌ Failed to send broadcast result: {e}")

# ===== BAN/UNBAN CALLBACK HANDLERS =====
@bot.callback_query_handler(func=lambda call: call.data == 'ban_user')
def ban_user_callback(call):

    user_id = call.from_user.id
    
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        "🔒 **Ban User**\n\n"
        "Send User ID to ban:\n"
        "Example: `123456789`\n"
        "Or /cancel",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_ban_user)

def process_ban_user(message):

    user_id = message.from_user.id
    
    if user_id not in admin_ids:
        return
    
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    
    try:
        target_user = int(message.text.strip())
        
        if target_user == OWNER_ID:
            bot.reply_to(message, "❌ Cannot ban owner!")
            return
        
        if target_user in admin_ids:
            bot.reply_to(message, "❌ Cannot ban admin!")
            return
        
        if is_user_banned(target_user):
            bot.reply_to(message, f"⚠️ User {target_user} already banned!")
            return
        
    
        ban_user_db(target_user, user_id)
        
        bot.reply_to(message, f"✅ User `{target_user}` banned!")
        
   
        try:
            bot.send_message(
                target_user,
                "❌ **You have been banned!**\n\n"
                "Contact admin if this is a mistake.",
                parse_mode='Markdown'
            )
        except:
            pass
            
    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'unban_user')
def unban_user_callback(call):

    user_id = call.from_user.id
    
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        "🔓 **Unban User**\n\n"
        "Send User ID to unban:\n"
        "Example: `123456789`\n"
        "Or /cancel",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_unban_user)

def process_unban_user(message):

    user_id = message.from_user.id
    
    if user_id not in admin_ids:
        return
    
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    
    try:
        target_user = int(message.text.strip())
        
        if not is_user_banned(target_user):
            bot.reply_to(message, f"ℹ️ User {target_user} is not banned!")
            return
        
        unban_user_db(target_user)
        
        bot.reply_to(message, f"✅ User `{target_user}` unbanned!")
        
        try:
            bot.send_message(
                target_user,
                "✅ **You have been unbanned!**\n\n"
                "You can now use the bot again.",
                parse_mode='Markdown'
            )
        except:
            pass
            
    except ValueError:
        bot.reply_to(message, "❌ Invalid User ID!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'banned_list')
def banned_list_callback(call):

    user_id = call.from_user.id
    
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    
    banned_users = get_banned_users()
    
    if not banned_users:
        bot.edit_message_text(
            "🔓 **No Banned Users**\n\n"
            "😕 All users are active.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_admin_panel(),
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)
        return
    
    text = "🔒 **Banned Users List**\n\n"
    for uid, banned_by, banned_at in banned_users:
        date_only = banned_at.split('T')[0]
        text += f"🆔 User: `{uid}`\n"
        text += f"📅 Date: {date_only}\n"
        text += "─" * 20 + "\n"
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=create_admin_panel(),
        parse_mode='Markdown'
    )
    bot.answer_callback_query(call.id)

# ===== SUBSCRIPTION CALLBACK HANDLERS =====
@bot.callback_query_handler(func=lambda call: call.data == 'add_subscription')
def add_subscription_init_callback(call):
    user_id = call.from_user.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        "🔢 Enter User ID & days\n"
        "Example: `123456789 30`\n"
        "Or /cancel",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_add_subscription_details)

def process_add_subscription_details(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids:
        bot.reply_to(message, "⛔ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Incorrect format")
        sub_user_id = int(parts[0].strip())
        days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0:
            raise ValueError("User ID/days must be positive")
        
        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now()
        if current_expiry and current_expiry > start_date_new_sub:
            start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)
        
        bot.reply_to(message, f"✅ Sub for `{sub_user_id}` by {days} days.\nNew expiry: {new_expiry.strftime('%Y-%m-%d')}")
        try:
            bot.send_message(sub_user_id, f"💎 Sub activated/extended by {days} days! Expires: {new_expiry.strftime('%Y-%m-%d')}")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'remove_subscription')
def remove_subscription_init_callback(call):
    user_id = call.from_user.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        "🔢 Enter User ID to remove subscription\nOr /cancel"
    )
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids:
        bot.reply_to(message, "⛔ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ Cancelled.")
        return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"ℹ️ User `{sub_user_id_remove}` no active sub.")
            return
        remove_subscription_db(sub_user_id_remove)
        bot.reply_to(message, f"✅ Sub for `{sub_user_id_remove}` removed.")
        try:
            bot.send_message(sub_user_id_remove, "❌ Your subscription removed by admin.")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ===== SUBSCRIPTION LIST CALLBACK =====
@bot.callback_query_handler(func=lambda call: call.data == 'list_subscriptions')
def list_subscriptions_callback(call):
    user_id = call.from_user.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    
    if not user_subscriptions:
        bot.edit_message_text(
            "😕 No active subscriptions found.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_subscription_panel()
        )
        return
    
    text = "**💳 Active Subscriptions:**\n\n"
    for uid, sub_info in list(user_subscriptions.items())[:20]:
        expiry = sub_info.get('expiry')
        if expiry:
            text += f"🆔 User: `{uid}`\n"
            text += f"📅 Expiry: {expiry.strftime('%Y-%m-%d')}\n"
            text += "────────────────────\n"
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=create_subscription_panel(),
        parse_mode='Markdown'
    )
    bot.answer_callback_query(call.id)

# ==== CLONE BOT CALLBACK HANDLERS ====
@bot.callback_query_handler(func=lambda call: call.data == 'clone_create')
def clone_create_callback(call):

    user_id = call.from_user.id
    
    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "❌ You are banned!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("❌ Cancel", callback_data="back_to_main"))
    
    bot.edit_message_text(
        f"🚀 **Create Clone Bot**\n\n"
        f"Send your bot token from @BotFather\n"
        f"Format: `1234567890:ABCdefGHi`",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id,
        lambda msg: handle_token_input(msg, call.message.chat.id, call.message.message_id)
    )


@bot.callback_query_handler(func=lambda call: call.data == 'clone_remove')
def clone_remove_callback(call):

    user_id = call.from_user.id
    
    if user_id not in user_clones:
        bot.answer_callback_query(call.id, f"⚠️ No Clone bot found.", show_alert=True)
        return
    
    bot_username = user_clones[user_id]['bot_username']
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("✅ Remove", callback_data="clone_remove_confirm"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
    )
    
    bot.edit_message_text(
        f"🗑️ **Remove Clone Bot**\n\n"
        f"⚠️ Remove your clone bot?\n\n"
        f"🤖 Bot: @{bot_username}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'clone_remove_confirm')
def clone_remove_confirm_callback(call):
    user_id = call.from_user.id
    
    if user_id not in user_clones:
        bot.answer_callback_query(call.id, f"⚠️ No clone bot found.", show_alert=True)
        return
    
    bot_username = user_clones[user_id]['bot_username']
    clone_dir = os.path.join(BASE_DIR, f'clone_{user_id}')
    if os.path.exists(clone_dir):
        try:
            shutil.rmtree(clone_dir)
        except:
            pass
    
    remove_clone_info(user_id)
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"✅ **Clone Bot Removed!**\n\n🤖 Bot @{bot_username} removed.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None,
        parse_mode="Markdown"
    )

def handle_token_input(message, original_chat_id, original_message_id):
    user_id = message.from_user.id
    
    if message.text == '/cancel':
        _logic_clone_bot(message)
        return
    
    token = message.text.strip()
    
    if not token or len(token) < 35 or ':' not in token:
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("❌ Cancel", callback_data="back_to_main"))
        bot.reply_to(
            message,
            "❌ Invalid bot token! Send valid token from @BotFather",
            reply_markup=markup
        )
        return
    
    processing_msg = bot.reply_to(message, "🔄 Creating your bot clone...")
    
    try:
        test_bot = telebot.TeleBot(token)
        bot_info = test_bot.get_me()
        
        bot.edit_message_text(
            f"✅ Token validated!\nBot: @{bot_info.username}\nCreating clone...",
            processing_msg.chat.id,
            processing_msg.message_id
        )
        
        clone_dir = os.path.join(BASE_DIR, f'clone_{user_id}')
        os.makedirs(clone_dir, exist_ok=True)
        
        current_file = __file__
        clone_file = os.path.join(clone_dir, 'bot.py')
        
        with open(current_file, 'r', encoding='utf-8') as f:
            script_content = f.read()
        
        script_content = script_content.replace(BOT_TOKEN, token)
        script_content = script_content.replace(str(OWNER_ID), str(user_id))
        script_content = script_content.replace(str(ADMIN_ID), str(user_id))
        
        with open(clone_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        clone_process = subprocess.Popen(
            [sys.executable, clone_file],
            cwd=clone_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        
        save_clone_info(user_id, bot_info.username, token)
        
        bot.edit_message_text(
            f"🎉 **Bot Clone Created!**\n\n🤖 Bot: @{bot_info.username}\n🚀 Status: Running\n✨ All features available!",
            processing_msg.chat.id,
            processing_msg.message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Failed to create clone: {str(e)}",
            processing_msg.chat.id,
            processing_msg.message_id
        )

# ===== FILE CONTROL CALLBACKS =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('file_'))
def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ You can only manage your own files.", show_alert=True)
            return
        
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "❓ File not found.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id)
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Active' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        
        bot.edit_message_text(
            f"⚙️ Controls for: `{file_name}` ({file_type})\nStatus: {status_text}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error in file control: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('start_'))
def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
            return
        
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "❓ File not found.", show_alert=True)
            return
        
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ File not found.", show_alert=True)
            return
        
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Script already running.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, f"⏳ Starting {file_name}...")
        
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        
        time.sleep(1)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Active' if is_now_running else '🟡 Starting...'
        bot.edit_message_text(
            f"⚙️ Controls for: `{file_name}` ({file_type})\nStatus: {status_text}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error starting script: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_'))
def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
            return
        
        script_key = f"{script_owner_id}_{file_name}"
        
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"🛑 Script already stopped.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, f"⏳ Stopping {file_name}...")
        
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        
        user_files_list = user_files.get(script_owner_id, [])
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        
        bot.edit_message_text(
            f"⚙️ Controls for: `{file_name}` ({file_type})\nStatus: 🔴 Stopped",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_control_buttons(script_owner_id, file_name, False),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error stopping script: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('restart_'))
def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
            return
        
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "❓ File not found.", show_alert=True)
            return
        
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        script_key = f"{script_owner_id}_{file_name}"
        
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ File not found.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, f"🔄 Restarting {file_name}...")
        
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            time.sleep(1)
        
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        
        time.sleep(1)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Active' if is_now_running else '🟡 Starting...'
        bot.edit_message_text(
            f"⚙️ Controls for: `{file_name}` ({file_type})\nStatus: {status_text}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error restarting script: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
            return
        
        script_key = f"{script_owner_id}_{file_name}"
        
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            time.sleep(0.5)
        
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except:
                pass
        
        remove_user_file_db(script_owner_id, file_name)
        bot.answer_callback_query(call.id, f"🗑️ Deleted {file_name}")
        bot.edit_message_text(
            f"✅ `{file_name}` deleted!",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error deleting script: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('logs_'))
def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        
        if requesting_user_id != script_owner_id and requesting_user_id not in admin_ids:
            bot.answer_callback_query(call.id, "⛔ Permission denied.", show_alert=True)
            return
        
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"📜 No logs for '{file_name}'.", show_alert=True)
            return
        
        bot.answer_callback_query(call.id)
        
        try:
            log_content = ""
            file_size = os.path.getsize(log_path)
            max_tg_msg = 4096
            
            if file_size == 0:
                log_content = "(Log empty)"
            else:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
            
            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                log_content = "...\n" + log_content
            
            bot.send_message(
                call.message.chat.id,
                f"📜 Logs for `{file_name}`:\n```\n{log_content}\n```",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"❌ Error reading log: {e}")
            bot.send_message(call.message.chat.id, f"⚠️ Error reading log for `{file_name}`.")
    except Exception as e:
        logger.error(f"❌ Error in logs callback: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'check_files')
def check_files_callback(call):
    user_id = call.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "📂 No files uploaded.", show_alert=True)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
        bot.edit_message_text("📂 Your files:\n\n(No files uploaded)", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return
    
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Active" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
    bot.edit_message_text("📂 Your files:\nClick to manage.", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    user_name = call.from_user.first_name
    user_last_name = call.from_user.last_name or ""
    
    if user_id == OWNER_ID:
        user_status = "👑 Owner"
    elif user_id in admin_ids:
        user_status = "⚜️ Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "💎 Premium"
            days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⌛️ Expires in: {days_left} days"
        else:
            user_status = "🆓 Free User"
            remove_subscription_db(user_id)
    else:
        user_status = "🆓 Free User"
    
    full_name = user_name
    if user_last_name:
        full_name += f" {user_last_name}"
    
    main_menu_text = (f"〽️ Welcome back, {full_name} !\n\n"
                      f"🆔 Your User ID: `{user_id}`\n"
                      f"🔰 Your Status: {user_status}{expiry_info}\n"
                      f"📁 Files Uploaded: {current_files} / {limit_str}\n\n"
                      f"👇 Use buttons or type commands.")
    
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id, parse_mode='Markdown')
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=main_reply_markup)
    except Exception as e:
        logger.error(f"❌ Error in back_to_main: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'lock_bot')
def lock_bot_callback(call):
    global bot_locked
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot_locked = True
    bot.answer_callback_query(call.id, "🔒 Bot locked.")
    bot.edit_message_text("🔒 Bot has been locked.", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == 'unlock_bot')
def unlock_bot_callback(call):
    global bot_locked
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot_locked = False
    bot.answer_callback_query(call.id, "✅ Bot unlocked.")
    bot.edit_message_text("✅ Bot has been unlocked.", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == 'run_all_scripts')
def run_all_scripts_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    _logic_run_all_scripts(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'broadcast_init')
def broadcast_init_callback(call):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⛔ Admin only!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_broadcast_'))
def handle_confirm_broadcast_callback(call):
    handle_confirm_broadcast(call)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_broadcast')
def handle_cancel_broadcast_callback(call):
    handle_cancel_broadcast(call)
    
@bot.message_handler(commands=['start'])
def command_send_welcome(message):
    _logic_send_welcome(message)

# ===== BUTTON TEXT HANDLERS =====
BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": upload_file_button,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "💳 Subscriptions": _logic_subscriptions,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Run All Scripts": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
    "🤖 Clone Bot": _logic_clone_bot
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func:
        logic_func(message)
        
# ===== CLEANUP =====
def cleanup():
    logger.warning("🧹 Shutting down. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop:
        logger.info("✅ No scripts running. Exiting.")
        return
    for key in script_keys_to_stop:
        if key in bot_scripts:
            logger.info(f"🧹 Stopping: {key}")
            kill_process_tree(bot_scripts[key])
    logger.warning("✅ Cleanup finished.")

atexit.register(cleanup)

# ===== MAIN POINT =====
if __name__ == '__main__':
    logger.info("="*40 + "\n🚀 Bot Starting Up...\n")
    keep_alive()
    logger.info("🔄 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except Exception as e:
            logger.critical(f"❌ Polling error: {e}")
            logger.info("🔄 Restarting polling in 30s...")
            time.sleep(30)