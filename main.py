# DON'T CHANGE MY CREDIT   
# DEVELOPER BY @shinchan
#!/usr/bin/env python3
# Telegram Hosting Bot - Premium Project Hosting Solution
# All configurations are managed via environment variables and bot commands

import os
import logging
import json
import time
import shutil
import asyncio
import zipfile
import subprocess
import threading
import re
import secrets
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

# Telegram Bot Library (python-telegram-bot v20+)
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InputFile, Chat
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ChatType, ParseMode
from telegram.helpers import escape_markdown

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============= CONFIGURATION =============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "YOUR_OWNER_ID"))
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id]
ADMIN_IDS.append(OWNER_ID)

FORCE_JOIN_CHANNELS = [
    os.environ.get("CHANNEL_1", "https://t.me/Shinchan_Sama_ton"),
    os.environ.get("CHANNEL_2", "https://t.me/End_Era_Guild"),
    os.environ.get("CHANNEL_3", "https://t.me/autolikegiveaway"),
]
FORCE_JOIN_CHANNELS = [ch for ch in FORCE_JOIN_CHANNELS if ch and ch != "@channel1"]

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
PROJECTS_META_FILE = BASE_DIR / "projects_meta.json"  # renamed from files_db
BANNED_USERS_FILE = BASE_DIR / "banned_users.json"
PROJECTS_DIR = BASE_DIR / "projects"
os.makedirs(PROJECTS_DIR, exist_ok=True)

# Additional config files for project management
CONFIG_FILE = BASE_DIR / "config.json"
VOTES_FILE = BASE_DIR / "votes_data.json"
BOT_LOCK_FILE = BASE_DIR / "bot_lock.json"
PENDING_FILE = BASE_DIR / "pending_approvals.json"

# ============= DATA MANAGER =============
class DataManager:
    @staticmethod
    def load_json(file_path: Path, default: dict = None) -> dict:
        if default is None:
            default = {}
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return default
        except (json.JSONDecodeError, IOError):
            return default

    @staticmethod
    def save_json(file_path: Path, data: dict) -> bool:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except IOError:
            return False

# ============= DATABASE ACCESS =============
def get_users_db():
    return DataManager.load_json(USERS_FILE, {"users": {}})

def save_users_db(data):
    return DataManager.save_json(USERS_FILE, data)

def get_projects_db():
    """Load projects metadata (formerly files_db)"""
    return DataManager.load_json(PROJECTS_META_FILE, {"projects": {}})

def save_projects_db(data):
    return DataManager.save_json(PROJECTS_META_FILE, data)

def get_banned_users() -> set:
    data = DataManager.load_json(BANNED_USERS_FILE, {"banned": []})
    return set(data.get("banned", []))

def save_banned_users(banned_set: set) -> bool:
    return DataManager.save_json(BANNED_USERS_FILE, {"banned": list(banned_set)})

# ============= USER MANAGEMENT =============
def register_user(user_id: int, username: str = "", first_name: str = ""):
    db = get_users_db()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_date": datetime.now().isoformat(),
            "is_admin": user_id in ADMIN_IDS,
            "is_owner": user_id == OWNER_ID,
            "projects_count": 0,
        }
        save_users_db(db)
        return True
    return False

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_banned(user_id: int) -> bool:
    return user_id in get_banned_users()

def ban_user(user_id: int) -> bool:
    banned = get_banned_users()
    if user_id in banned:
        return False
    banned.add(user_id)
    save_banned_users(banned)
    return True

def unban_user(user_id: int) -> bool:
    banned = get_banned_users()
    if user_id not in banned:
        return False
    banned.discard(user_id)
    save_banned_users(banned)
    return True

# ============= PROJECT MANAGEMENT (MERGED FROM SECOND FILE) =============
def load_meta():
    return get_projects_db()

def save_meta(data):
    return save_projects_db(data)

# Active processes dict: proj_id -> {process, log_file, start_time, cmd_used, port}
active_processes = {}

# Pending approvals system
def load_pending():
    return DataManager.load_json(PENDING_FILE, {})

def save_pending(data):
    return DataManager.save_json(PENDING_FILE, data)

def add_pending_approval(proj_id, user_id, proj_data):
    pending = load_pending()
    pending[proj_id] = {
        "user_id": user_id,
        "proj_data": proj_data,
        "timestamp": time.time(),
        "status": "pending"
    }
    save_pending(pending)
    return True

def approve_project(proj_id):
    pending = load_pending()
    if proj_id in pending:
        pending[proj_id]["status"] = "approved"
        save_pending(pending)
        return True
    return False

def reject_project(proj_id):
    pending = load_pending()
    if proj_id in pending:
        pending[proj_id]["status"] = "rejected"
        save_pending(pending)
        return True
    return False

def get_pending_approvals():
    pending = load_pending()
    return {k: v for k, v in pending.items() if v.get("status") == "pending"}

def cleanup_pending(proj_id):
    pending = load_pending()
    if proj_id in pending:
        del pending[proj_id]
        save_pending(pending)
        return True
    return False

# Bot lock system
def load_bot_lock():
    return DataManager.load_json(BOT_LOCK_FILE, {"locked": False}).get("locked", False)

def save_bot_lock(locked):
    DataManager.save_json(BOT_LOCK_FILE, {"locked": locked})

BOT_LOCKED = load_bot_lock()

def is_bot_locked():
    return BOT_LOCKED

def toggle_bot_lock():
    global BOT_LOCKED
    BOT_LOCKED = not BOT_LOCKED
    save_bot_lock(BOT_LOCKED)
    return BOT_LOCKED

# Port utilities
def find_free_port():
    return 8080  # simple fallback, can be enhanced

# File index mapping
def update_project_files_map(proj_id, proj_dir):
    all_files = []
    for root, dirs, files_in_dir in os.walk(proj_dir):
        for f in files_in_dir:
            if f == "output.log":
                continue
            rel_path = os.path.relpath(os.path.join(root, f), proj_dir)
            all_files.append(rel_path)
    all_files.sort()
    files_map = {str(idx): path for idx, path in enumerate(all_files)}
    meta = load_meta()
    if proj_id in meta["projects"]:
        meta["projects"][proj_id]["files"] = files_map
        save_meta(meta)
    return files_map

# Process runner
def run_project_process(proj_id, proj_data):
    proj_dir = proj_data["dir"]
    main_file = proj_data["main_file"]
    log_file_path = os.path.join(proj_dir, "output.log")
    
    if os.path.exists(log_file_path):
        try:
            os.remove(log_file_path)
        except:
            pass
        
    log_file = open(log_file_path, 'w', encoding='utf-8')
    
    port = find_free_port()
    meta = load_meta()
    if proj_id in meta["projects"]:
        meta["projects"][proj_id]["port"] = port
        save_meta(meta)
            
    if main_file.endswith('.py'):
        cmd = [sys.executable, '-u', main_file]
    elif main_file.endswith('.js'):
        cmd = ['node', main_file]
    elif main_file.endswith('.sh'):
        cmd = ['bash', main_file]
    elif main_file.endswith(('.html', '.htm')):
        cmd = [sys.executable, '-u', '-m', 'http.server', str(port)]
    else:
        cmd = [sys.executable, '-u', main_file]
    
    env = os.environ.copy()
    env['PORT'] = str(port)
    env_file = os.path.join(proj_dir, '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env[k.strip()] = v.strip()
                    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=proj_dir,
            env=env,
            text=True
        )
        active_processes[proj_id] = {
            "process": process,
            "log_file": log_file,
            "start_time": time.time(),
            "cmd_used": " ".join(cmd),
            "port": port
        }
        return True, "Success"
    except FileNotFoundError as e:
        err_msg = f"Error: {cmd[0]} engine is not installed or not in system PATH."
        log_file.write(err_msg)
        log_file.close()
        return False, err_msg
    except Exception as e:
        err_msg = str(e)
        log_file.write(f"Error starting process: {err_msg}")
        log_file.close()
        return False, err_msg

def stop_project_process(proj_id):
    if proj_id in active_processes:
        proc_info = active_processes[proj_id]
        try:
            proc_info["process"].terminate()
        except:
            pass
        try:
            proc_info["log_file"].close()
        except:
            pass
        del active_processes[proj_id]

def get_project_status(proj_id, proj_data):
    log_path = os.path.join(proj_data["dir"], "output.log")
    if proj_id in active_processes:
        poll = active_processes[proj_id]["process"].poll()
        if poll is None:
            uptime = int(time.time() - active_processes[proj_id]["start_time"])
            mins, secs = divmod(uptime, 60)
            hrs, mins = divmod(mins, 60)
            return f"🟢 RUNNING (Uptime: {hrs}h {mins}m {secs}s)"
        else:
            missing = get_missing_module(log_path)
            if missing:
                return f"⚠️ CRASHED (Missing Module: {missing})"
            return "🔴 STOPPED"
    else:
        missing = get_missing_module(log_path)
        if missing:
            return f"⚠️ CRASHED (Missing Module: {missing})"
        return "🔴 STOPPED"

def get_missing_module(log_path):
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        py_match = re.search(r"(?:ModuleNotFoundError|ImportError): No module named ([^\s]+)", content)
        if py_match:
            return py_match.group(1)
        node_match = re.search(r"Error: Cannot find module ([^\s]+)", content)
        if node_match:
            return node_match.group(1)
    except:
        pass
    return None

def get_process_resource_usage(proj_id):
    # Simpler version without psutil
    return "N/A"

# Auto-restart monitor thread
def bg_project_monitor():
    while True:
        time.sleep(8)
        try:
            meta = load_meta()
            for proj_id, proj_data in meta["projects"].items():
                if proj_data.get("auto_restart") is True:
                    if proj_id in active_processes:
                        poll = active_processes[proj_id]["process"].poll()
                        if poll is not None:
                            log_path = os.path.join(proj_data["dir"], "output.log")
                            if not get_missing_module(log_path):
                                run_project_process(proj_id, proj_data)
        except Exception:
            pass

threading.Thread(target=bg_project_monitor, daemon=True).start()

# ============= FORCE JOIN CHECK =============
async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not FORCE_JOIN_CHANNELS:
        return True
    if user_id == OWNER_ID:
        return True
    for channel in FORCE_JOIN_CHANNELS:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if chat_member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Force join check error for channel {channel}: {e}")
            return False
    return True

def get_force_join_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for channel in FORCE_JOIN_CHANNELS:
        buttons.append([InlineKeyboardButton(
            text=f"Join {channel}",
            url=f"https://t.me/{channel.replace('@', '')}"
        )])
    buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="force_join_check")])
    return InlineKeyboardMarkup(buttons)

# ============= KEYBOARDS =============
def get_user_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    keyboard = [
        ["🚀 Deploy New", "📁 My Projects"],
        ["🖥️ Server Status", "❔ Help"],
        ["📞 Contact Owner"],
        ["📊 My Stats"]
    ]
    if user_id and (is_admin(user_id) or is_owner(user_id)):
        keyboard.append(["🛠️ Admin Panel"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["📊 Dashboard", "👥 Users"],
        ["📢 Broadcast", "⛔ Ban Management"],
        ["👑 Admin Management"],
        ["⏳ Pending Approvals"],
        ["🔙 Back to User"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_owner_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["📊 Dashboard", "👥 Users"],
        ["📢 Broadcast", "👑 Admin Management"],
        ["⛔ Ban Management", "⏳ Pending Approvals"],
        ["🔙 Back to User"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============= CONVERSATION STATES =============
DEPLOY_STATE = 1
BROADCAST_STATE = 2
ADD_ENV_STATE = 3
EDIT_FILE_STATE = 4
REPLACE_FILE_STATE = 5
ADD_ADMIN_STATE = 6
REMOVE_ADMIN_STATE = 7
BAN_USER_STATE = 8
UNBAN_USER_STATE = 9
ADD_CHANNEL_STATE = 10
REMOVE_CHANNEL_STATE = 11

# ============= COMMAND HANDLERS =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    if is_banned(user_id):
        await update.message.reply_text("⛔ You are banned from using this bot.")
        return
    if not await check_force_join(user_id, context):
        await update.message.reply_text(
            "Please join our channels first.",
            reply_markup=get_force_join_keyboard()
        )
        return
    register_user(user_id, user.username or "", user.first_name or "")
    if is_owner(user_id):
        keyboard = get_owner_keyboard()
        welcome = "👑 Owner Panel"
    elif is_admin(user_id):
        keyboard = get_admin_keyboard()
        welcome = "👨‍💼 Admin Panel"
    else:
        keyboard = get_user_keyboard(user_id)
        welcome = "📁 User Panel"

    await update.message.reply_text(
        f"Welcome {user.first_name}!\n\n"
        f"You are now in {welcome}.\n"
        "Use the buttons below to manage your projects.",
        reply_markup=keyboard
    )

async def force_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if is_banned(user_id):
        await query.edit_message_text("⛔ You are banned.")
        return
    if await check_force_join(user_id, context):
        register_user(user_id, query.from_user.username or "", query.from_user.first_name or "")
        await query.message.delete()
        if is_owner(user_id):
            keyboard = get_owner_keyboard()
            welcome = "👑 Owner Panel"
        elif is_admin(user_id):
            keyboard = get_admin_keyboard()
            welcome = "👨‍💼 Admin Panel"
        else:
            keyboard = get_user_keyboard(user_id)
            welcome = "📁 User Panel"
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Welcome {query.from_user.first_name}!\n\n"
                 f"You are now in {welcome}.\n"
                 "Use the buttons below to manage your projects.",
            reply_markup=keyboard
        )
    else:
        await query.answer("❌ Please join all channels first.", show_alert=True)

# ============= DEPLOY CONVERSATION =============
async def deploy_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("⛔ You are banned.")
        return ConversationHandler.END
    if not await check_force_join(user.id, context):
        await update.message.reply_text(
            "Please join our channels first.",
            reply_markup=get_force_join_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📤 Please send me your project ZIP archive to deploy.\n"
        "I will extract it and guide you to select the main file.\n\n"
        "⚠️ Your deployment will need admin approval before it goes live.\n"
        "Send /cancel to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )
    return DEPLOY_STATE

async def handle_deploy_zip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    message = update.message
    if is_banned(user.id):
        await message.reply_text("⛔ You are banned.")
        return ConversationHandler.END
    if not await check_force_join(user.id, context):
        await message.reply_text("Please join our channels first.")
        return ConversationHandler.END

    if not message.document or not message.document.file_name.endswith('.zip'):
        await message.reply_text("❌ Please send a valid .zip file.")
        return DEPLOY_STATE

    file_name = message.document.file_name
    status_msg = await message.reply_text("⏳ Downloading and extracting project...")

    try:
        file_obj = await context.bot.get_file(message.document.file_id)
        timestamp = int(time.time())
        proj_id = secrets.token_hex(3)
        proj_dir = PROJECTS_DIR / f"proj_{user.id}_{timestamp}"
        proj_dir.mkdir(parents=True, exist_ok=True)
        zip_path = proj_dir / "temp_archive.zip"
        await file_obj.download_to_drive(zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(proj_dir)
        zip_path.unlink()

        meta = load_meta()
        meta["projects"][proj_id] = {
            "name": file_name.replace('.zip', ''),
            "dir": str(proj_dir),
            "main_file": '',
            "chat_id": user.id,
            "auto_restart": False,
            "files": {},
            "pending_approval": True
        }
        save_meta(meta)

        files_map = update_project_files_map(proj_id, proj_dir)

        # Save pending approval
        pending_data = {
            "file_name": file_name,
            "files": list(files_map.values())
        }
        add_pending_approval(proj_id, user.id, pending_data)

        # Notify admins
        await send_approval_request(proj_id, user.id, file_name, list(files_map.values()), context)

        # Show main file selection
        PRIORITY_NAMES = ['main.py', 'app.py', 'bot.py', 'run.py', 'server.py', 'index.py',
                          'index.js', 'app.js', 'server.js', 'main.js', 'bot.js', 'start.js']

        def entry_sort_key(item):
            idx, f = item
            base = os.path.basename(f).lower()
            if base in PRIORITY_NAMES:
                return (0, PRIORITY_NAMES.index(base))
            return (1, base)

        code_files = [(idx, f) for idx, f in files_map.items() if f.endswith(('.py', '.js', '.sh', '.html', '.htm'))]
        code_files.sort(key=entry_sort_key)

        keyboard = InlineKeyboardMarkup([])
        count = 0
        for idx, f in code_files:
            if count >= 10:
                break
            base = os.path.basename(f).lower()
            star = "⭐ " if base in PRIORITY_NAMES else "📄 "
            keyboard.inline_keyboard.append([InlineKeyboardButton(f"{star}{f}", callback_data=f"select_main:{proj_id}:{idx}")])
            count += 1

        if count == 0:
            for idx, f in files_map.items():
                if count < 10:
                    keyboard.inline_keyboard.append([InlineKeyboardButton(f"📄 {f}", callback_data=f"select_main:{proj_id}:{idx}")])
                    count += 1

        await status_msg.edit_text(
            f"✅ Archive extracted: `{file_name}`\n\n"
            f"⏳ Your deployment is pending approval.\n"
            f"🆔 Request ID: `{proj_id}`\n\n"
            f"Select the entry point (main file) for your project:\n"
            f"(Deployment will start after admin approval)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Deploy error: {e}")
        await status_msg.edit_text(f"❌ Deployment failed: {str(e)}")

    return ConversationHandler.END

async def send_approval_request(proj_id, user_id, file_name, files_list, context):
    pending = load_pending()
    proj_data = pending.get(proj_id, {})
    users_db = get_users_db()
    user_info = users_db["users"].get(str(user_id), {})
    first_name = user_info.get("first_name", "Unknown")
    username = user_info.get("username", "No username")

    files_str = "\n".join([f"  • {f}" for f in files_list[:10]])
    if len(files_list) > 10:
        files_str += f"\n  ... and {len(files_list) - 10} more"

    approval_text = (
        f"╔═══════════════════════════════════╗\n"
        f"║      ⏳ NEW DEPLOYMENT REQUEST ⏳      ║\n"
        f"╚═══════════════════════════════╝\n\n"
        f"📄 Project: `{file_name.replace('.zip', '')}`\n"
        f"👤 User: `{escape_markdown(first_name)}`\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📛 Username: @{escape_markdown(username)}\n"
        f"📅 Requested at: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 Files in archive:\n{files_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Project ID: `{proj_id}`\n\n"
        f"⚠️ Action Required: Please approve or reject this deployment."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve:{proj_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject:{proj_id}")],
        [InlineKeyboardButton("📂 View Files", callback_data=f"view_pending:{proj_id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=approval_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to send approval to admin {admin_id}: {e}")

    # Notify user
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏳ Your deployment request has been sent for approval.\n\n"
             f"📄 Project: `{file_name.replace('.zip', '')}`\n"
             f"🆔 Request ID: `{proj_id}`\n\n"
             f"Please wait for an admin to approve your deployment.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await update.message.reply_text(
        "❌ Cancelled.",
        reply_markup=get_user_keyboard(user.id)
    )
    return ConversationHandler.END

# ============= PROJECT DASHBOARD =============
async def my_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("⛔ You are banned.")
        return
    if not await check_force_join(user.id, context):
        await update.message.reply_text("Please join our channels first.")
        return

    meta = load_meta()
    user_projects = {k: v for k, v in meta["projects"].items() if v.get("chat_id") == user.id}
    if not user_projects:
        await update.message.reply_text("📭 You have no projects yet. Deploy a new one using Deploy New.")
        return

    text = "📁 Your Projects:\n\n"
    keyboard = InlineKeyboardMarkup([])
    for proj_id, pdata in user_projects.items():
        status = get_project_status(proj_id, pdata)
        symbol = "🟢" if "RUNNING" in status else "🔴"
        if "CRASHED" in status:
            symbol = "⚠️"
        # Check pending status
        pending = load_pending()
        if proj_id in pending and pending[proj_id].get("status") == "pending":
            symbol = "⏳"
        elif proj_id in pending and pending[proj_id].get("status") == "rejected":
            symbol = "❌"
        text += f"{symbol} `{pdata['name']}`\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(f"📦 {pdata['name']} ({symbol})", callback_data=f"proj_view:{proj_id}")])

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

# ============= SERVER STATUS =============
async def server_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Simple stats, can be expanded
    meta = load_meta()
    total_projects = len(meta["projects"])
    running = 0
    for pid, pdata in meta["projects"].items():
        if "RUNNING" in get_project_status(pid, pdata):
            running += 1
    text = (
        f"🖥️ Server Status\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Projects: {total_projects}\n"
        f"🟢 Running: {running}\n"
        f"🔴 Stopped: {total_projects - running}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ============= HELP =============
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 Help Center\n\n"
        "🚀 Deploy New – Upload a .zip of your project.\n"
        "📁 My Projects – View and manage your projects.\n"
        "🖥️ Server Status – Show server stats.\n"
        "📞 Contact Owner – Contact the bot owner.\n"
        "📊 My Stats – Your personal statistics.\n\n"
        "🔧 Admin Features (if applicable):\n"
        "- 📊 Dashboard: Bot statistics\n"
        "- 👥 Users: Manage users\n"
        "- 📢 Broadcast: Send messages to all users\n"
        "- ⛔ Ban Management: Ban/unban users\n"
        "- 👑 Admin Management: Add/remove admins\n"
        "- ⏳ Pending Approvals: Approve/reject deployments\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# ============= MY STATS =============
async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    meta = load_meta()
    user_projects = {k: v for k, v in meta["projects"].items() if v.get("chat_id") == user.id}
    total = len(user_projects)
    running = 0
    for pid, pdata in user_projects.items():
        if "RUNNING" in get_project_status(pid, pdata):
            running += 1
    text = (
        f"📊 My Statistics\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 User ID: `{user.id}`\n"
        f"📦 Projects: {total}\n"
        f"🟢 Running: {running}\n"
        f"🔴 Stopped: {total - running}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ============= ADMIN PANEL =============
async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    meta = load_meta()
    users_db = get_users_db()
    total_users = len(users_db["users"])
    total_projects = len(meta["projects"])
    running = sum(1 for pid, pdata in meta["projects"].items() if "RUNNING" in get_project_status(pid, pdata))
    pending = len(get_pending_approvals())
    text = (
        f"📊 Dashboard\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: {total_users}\n"
        f"📦 Total Projects: {total_projects}\n"
        f"🟢 Running: {running}\n"
        f"🔴 Stopped: {total_projects - running}\n"
        f"⏳ Pending Approvals: {pending}\n"
        f"🔒 Bot Lock: {'🔒 LOCKED' if is_bot_locked() else '🔓 UNLOCKED'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    users_db = get_users_db()
    users = users_db["users"]
    if not users:
        await update.message.reply_text("No users registered.")
        return
    text = "👥 Users List\n\n"
    for uid, uinfo in list(users.items())[:20]:
        text += f"• `{uid}` – {uinfo.get('first_name', 'Unknown')} (@{uinfo.get('username', 'N/A')})\n"
    if len(users) > 20:
        text += f"\n... and {len(users)-20} more"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_all_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    meta = load_meta()
    if not meta["projects"]:
        await update.message.reply_text("No projects found.")
        return
    text = "📋 All Projects\n\n"
    for pid, pdata in list(meta["projects"].items())[:20]:
        status = get_project_status(pid, pdata)
        text += f"• `{pdata['name']}` – {status} (by {pdata.get('chat_id', 'N/A')})\n"
    if len(meta["projects"]) > 20:
        text += f"\n... and {len(meta['projects'])-20} more"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    await update.message.reply_text("⚙️ Settings panel (placeholder)")

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 Send me the message to broadcast to all users.\n"
        "Send /cancel to cancel."
    )
    return BROADCAST_STATE

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    users_db = get_users_db()
    users = users_db["users"].keys()
    progress = await update.message.reply_text(f"⏳ Broadcasting to {len(users)} users...")
    success = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=int(uid),
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            success += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed += 1
    await progress.edit_text(f"✅ Broadcast completed!\n\n📨 Sent: {success}\n❌ Failed: {failed}")
    return ConversationHandler.END

async def ban_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    banned = get_banned_users()
    if banned:
        text = "⛔ Banned Users\n" + "\n".join(f"• `{uid}`" for uid in list(banned)[:20])
        if len(banned) > 20:
            text += f"\n... and {len(banned)-20} more"
    else:
        text = "✅ No users banned."
    text += "\n\nUse /ban <user_id> and /unban <user_id> to manage."
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def admin_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("⛔ Only owner can manage admins.")
        return
    text = "👑 Admin Management\n\n"
    text += f"Current admins: {[uid for uid in ADMIN_IDS if uid != OWNER_ID]}\n"
    text += "\nUse /addadmin <user_id> and /removeadmin <user_id>"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def lock_unlock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    new_status = toggle_bot_lock()
    await update.message.reply_text(f"🔒 Bot is now {'LOCKED' if new_status else 'UNLOCKED'}")

async def pending_approvals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    pending = get_pending_approvals()
    if not pending:
        await update.message.reply_text("📭 No pending approvals.")
        return
    text = "⏳ Pending Approvals\n\n"
    for pid, pdata in list(pending.items())[:20]:
        text += f"• `{pid}` – {pdata.get('proj_data', {}).get('file_name', 'Unknown')} (by {pdata.get('user_id', 'N/A')})\n"
    if len(pending) > 20:
        text += f"\n... and {len(pending)-20} more"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    # Same as dashboard
    await admin_dashboard(update, context)

async def back_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    keyboard = get_user_keyboard(user.id)
    await update.message.reply_text("🔙 Switched to User Panel.", reply_markup=keyboard)

# ============= PROJECT CALLBACKS =============
async def project_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    chat_id = query.message.chat.id
    message_id = query.message.message_id

    # Check ban, lock, force join (simplified)
    if is_banned(user_id):
        await query.edit_message_text("⛔ You are banned.")
        return
    if is_bot_locked() and not is_admin(user_id):
        await query.edit_message_text("🔒 Bot is locked.")
        return
    if not await check_force_join(user_id, context):
        await query.edit_message_text("Please join our channels first.", reply_markup=get_force_join_keyboard())
        return

    # Handle approval/rejection
    if data.startswith("approve:"):
        if not is_admin(user_id):
            await query.answer("⛔ Admin access required.", show_alert=True)
            return
        proj_id = data.split(":")[1]
        pending = load_pending()
        if proj_id not in pending:
            await query.edit_message_text("❌ Request expired.")
            return
        approve_project(proj_id)
        user_id_owner = pending[proj_id]["user_id"]
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id_owner,
                text=f"✅ Your deployment `{pending[proj_id]['proj_data']['file_name']}` has been APPROVED!",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        await query.edit_message_text("✅ Project approved.")
        return

    if data.startswith("reject:"):
        if not is_admin(user_id):
            await query.answer("⛔ Admin access required.", show_alert=True)
            return
        proj_id = data.split(":")[1]
        pending = load_pending()
        if proj_id not in pending:
            await query.edit_message_text("❌ Request expired.")
            return
        reject_project(proj_id)
        user_id_owner = pending[proj_id]["user_id"]
        try:
            await context.bot.send_message(
                chat_id=user_id_owner,
                text=f"❌ Your deployment `{pending[proj_id]['proj_data']['file_name']}` has been REJECTED.",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        await query.edit_message_text("❌ Project rejected.")
        return

    if data.startswith("view_pending:"):
        if not is_admin(user_id):
            await query.answer("⛔ Admin access required.", show_alert=True)
            return
        proj_id = data.split(":")[1]
        pending = load_pending()
        if proj_id not in pending:
            await query.edit_message_text("❌ Request not found.")
            return
        pdata = pending[proj_id]
        files = pdata.get("proj_data", {}).get("files", [])
        files_str = "\n".join(f"• {f}" for f in files[:15])
        text = (
            f"📂 Pending Details\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{proj_id}`\n"
            f"👤 User: `{pdata['user_id']}`\n"
            f"📄 Project: {pdata.get('proj_data', {}).get('file_name', 'Unknown')}\n"
            f"📁 Files:\n{files_str}\n"
            f"📅 Requested: {datetime.fromtimestamp(pdata['timestamp']).strftime('%Y-%m-%d %H:%M')}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    # Project actions
    if data.startswith("select_main:"):
        _, proj_id, file_idx = data.split(":")
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        if meta["projects"][proj_id].get("chat_id") != user_id and not is_admin(user_id):
            await query.answer("🔒 Access denied.", show_alert=True)
            return
        files_map = meta["projects"][proj_id].get("files", {})
        if file_idx not in files_map:
            await query.edit_message_text("❌ File not found.")
            return
        filename = files_map[file_idx]
        meta["projects"][proj_id]["main_file"] = filename
        save_meta(meta)

        # Check if project is approved
        pending = load_pending()
        if proj_id in pending and pending[proj_id].get("status") == "approved":
            # Start project
            success, err_msg = run_project_process(proj_id, meta["projects"][proj_id])
            cleanup_pending(proj_id)
            if success:
                await query.edit_message_text(f"✅ Project deployed and running!\nMain file: {filename}")
            else:
                await query.edit_message_text(f"❌ Failed to start: {err_msg}")
        else:
            await query.edit_message_text(
                f"✅ Main file set to `{filename}`.\n"
                f"⏳ Waiting for admin approval before starting.",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    if data.startswith("proj_view:"):
        proj_id = data.split(":")[1]
        await show_project_dashboard(update, context, proj_id, message_id)
        return

    if data.startswith("proj_start:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        stop_project_process(proj_id)
        success, err_msg = run_project_process(proj_id, meta["projects"][proj_id])
        if success:
            await query.edit_message_text("🟢 Project started.")
        else:
            await query.edit_message_text(f"❌ Failed: {err_msg}")
        await show_project_dashboard(update, context, proj_id, message_id)
        return

    if data.startswith("proj_stop:"):
        proj_id = data.split(":")[1]
        stop_project_process(proj_id)
        await query.edit_message_text("🔴 Project stopped.")
        await show_project_dashboard(update, context, proj_id, message_id)
        return

    if data.startswith("proj_restart:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        stop_project_process(proj_id)
        success, err_msg = run_project_process(proj_id, meta["projects"][proj_id])
        if success:
            await query.edit_message_text("🔄 Project restarted.")
        else:
            await query.edit_message_text(f"❌ Failed: {err_msg}")
        await show_project_dashboard(update, context, proj_id, message_id)
        return

    if data.startswith("proj_autorestart_toggle:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        current = meta["projects"][proj_id].get("auto_restart", False)
        meta["projects"][proj_id]["auto_restart"] = not current
        save_meta(meta)
        await query.edit_message_text(f"🔄 Auto-restart {'ENABLED' if not current else 'DISABLED'}.")
        await show_project_dashboard(update, context, proj_id, message_id)
        return

    if data.startswith("proj_logs:"):
        proj_id = data.split(":")[1]
        await show_logs(update, context, proj_id, message_id)
        return

    if data.startswith("proj_download_logs:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        log_path = Path(meta["projects"][proj_id]["dir"]) / "output.log"
        if log_path.exists():
            with open(log_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename=f"{meta['projects'][proj_id]['name']}_logs.txt"),
                    reply_to_message_id=message_id
                )
        else:
            await query.edit_message_text("📭 No logs found.")
        return

    if data.startswith("proj_env:"):
        proj_id = data.split(":")[1]
        await show_env_editor(update, context, proj_id, message_id)
        return

    if data.startswith("proj_add_env:"):
        proj_id = data.split(":")[1]
        context.user_data['add_env_project'] = proj_id
        await query.edit_message_text(
            f"📝 Send environment variable in format `KEY=VALUE`\n"
            f"Project: {proj_id}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("proj_clear_env:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        env_file = Path(meta["projects"][proj_id]["dir"]) / ".env"
        if env_file.exists():
            env_file.unlink()
        await query.edit_message_text("🗑️ .env cleared.")
        await show_env_editor(update, context, proj_id, message_id)
        return

    if data.startswith("proj_fm:"):
        proj_id = data.split(":")[1]
        await show_file_manager(update, context, proj_id, message_id)
        return

    if data.startswith("vf:"):
        _, proj_id, file_idx = data.split(":")
        await view_file(update, context, proj_id, file_idx, message_id)
        return

    if data.startswith("ef:"):
        _, proj_id, file_idx = data.split(":")
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        files_map = meta["projects"][proj_id].get("files", {})
        if file_idx not in files_map:
            await query.edit_message_text("❌ File not found.")
            return
        rel_path = files_map[file_idx]
        context.user_data['edit_file'] = (proj_id, rel_path)
        await query.edit_message_text(
            f"✏️ Editing `{rel_path}`\n"
            f"Send the new content of the file.\n"
            f"Send /cancel to cancel.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("rf:"):
        _, proj_id, file_idx = data.split(":")
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        files_map = meta["projects"][proj_id].get("files", {})
        if file_idx not in files_map:
            await query.edit_message_text("❌ File not found.")
            return
        rel_path = files_map[file_idx]
        context.user_data['replace_file'] = (proj_id, rel_path)
        await query.edit_message_text(
            f"📥 Replace `{rel_path}`\n"
            f"Send the new file as a document.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data.startswith("df:"):
        _, proj_id, file_idx = data.split(":")
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        files_map = meta["projects"][proj_id].get("files", {})
        if file_idx not in files_map:
            await query.edit_message_text("❌ File not found.")
            return
        rel_path = files_map[file_idx]
        target = Path(meta["projects"][proj_id]["dir"]) / rel_path
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            await query.edit_message_text("🗑️ File deleted.")
        await show_file_manager(update, context, proj_id, message_id)
        return

    if data.startswith("proj_backup:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        proj_data = meta["projects"][proj_id]
        backup_zip = Path(BASE_DIR) / f"{proj_data['name']}_backup.zip"
        try:
            with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(proj_data["dir"]):
                    for file in files:
                        if file == "output.log":
                            continue
                        full_p = Path(root) / file
                        rel_p = full_p.relative_to(proj_data["dir"])
                        zipf.write(full_p, rel_p)
            with open(backup_zip, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename=f"{proj_data['name']}_backup.zip"),
                    reply_to_message_id=message_id
                )
            backup_zip.unlink()
        except Exception as e:
            await query.edit_message_text(f"❌ Backup failed: {e}")
        return

    if data.startswith("proj_install:"):
        _, proj_id, module_name = data.split(":")
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        main_file = meta["projects"][proj_id]["main_file"]
        is_node = main_file.endswith('.js')
        installer = "npm" if is_node else "pip"
        msg = await query.edit_message_text(f"⏳ Installing {module_name} with {installer}...")
        try:
            if is_node:
                cmd = ["npm", "install", module_name]
            else:
                cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", module_name]
            result = subprocess.run(cmd, cwd=meta["projects"][proj_id]["dir"], capture_output=True, text=True, timeout=80)
            if result.returncode == 0:
                await msg.edit_text(f"✅ {module_name} installed.")
            else:
                await msg.edit_text(f"❌ Installation failed:\n{result.stderr[:200]}")
        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")
        return

    if data.startswith("proj_delete:"):
        proj_id = data.split(":")[1]
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await query.edit_message_text("❌ Project not found.")
            return
        if meta["projects"][proj_id].get("chat_id") != user_id and not is_admin(user_id):
            await query.answer("🔒 Access denied.", show_alert=True)
            return
        stop_project_process(proj_id)
        shutil.rmtree(meta["projects"][proj_id]["dir"], ignore_errors=True)
        del meta["projects"][proj_id]
        save_meta(meta)
        await query.edit_message_text("🗑️ Project deleted.")
        await my_projects(update, context)
        return

    if data == "btn_deploy":
        await deploy_start(update, context)
        return

    if data == "btn_my_files":
        await my_projects(update, context)
        return

    if data == "btn_back_home":
        await start(update, context)
        return

    # Default
    await query.answer("Invalid action.", show_alert=True)

# ============= PROJECT DASHBOARD DISPLAY =============
async def show_project_dashboard(update, context, proj_id, message_id=None):
    query = update.callback_query if update.callback_query else None
    chat_id = update.effective_chat.id
    meta = load_meta()
    if proj_id not in meta["projects"]:
        text = "❌ Project not found."
        if query:
            await query.edit_message_text(text)
        else:
            await context.bot.send_message(chat_id, text)
        return
    proj_data = meta["projects"][proj_id]
    status = get_project_status(proj_id, proj_data)
    auto_r = "🟢 Enabled" if proj_data.get("auto_restart") else "🔴 Disabled"
    port = proj_data.get("port", None)
    mem = get_process_resource_usage(proj_id)

    text = (
        f"⚙️ Project Dashboard\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 Name: `{proj_data['name']}`\n"
        f"🚀 Main: `{proj_data['main_file']}`\n"
        f"📈 Status: {status}\n"
        f"⚙️ Memory: `{mem}`\n"
        f"🔌 Port: `{port}`\n"
        f"🔄 Auto-Restart: {auto_r}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 Manage your project:"
    )

    keyboard = InlineKeyboardMarkup(row_width=2)
    if "RUNNING" in status:
        keyboard.add(InlineKeyboardButton("⏸ Stop", callback_data=f"proj_stop:{proj_id}"))
    else:
        keyboard.add(InlineKeyboardButton("▶ Start", callback_data=f"proj_start:{proj_id}"))
    keyboard.add(
        InlineKeyboardButton("🔄 Restart", callback_data=f"proj_restart:{proj_id}"),
        InlineKeyboardButton("📋 Logs", callback_data=f"proj_logs:{proj_id}")
    )
    keyboard.add(
        InlineKeyboardButton("📝 .env", callback_data=f"proj_env:{proj_id}"),
        InlineKeyboardButton("📁 Files", callback_data=f"proj_fm:{proj_id}")
    )
    keyboard.add(
        InlineKeyboardButton("📦 Backup", callback_data=f"proj_backup:{proj_id}"),
        InlineKeyboardButton("🔄 Auto-Restart Toggle", callback_data=f"proj_autorestart_toggle:{proj_id}")
    )
    missing = get_missing_module(Path(proj_data["dir"]) / "output.log")
    if missing:
        keyboard.add(InlineKeyboardButton(f"📦 Install {missing}", callback_data=f"proj_install:{proj_id}:{missing}"))
    keyboard.add(
        InlineKeyboardButton("🗑 Delete", callback_data=f"proj_delete:{proj_id}"),
        InlineKeyboardButton("🔙 Back to Projects", callback_data="btn_my_files")
    )

    if query:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

async def show_logs(update, context, proj_id, message_id):
    meta = load_meta()
    if proj_id not in meta["projects"]:
        await context.bot.edit_message_text("❌ Project not found.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    log_path = Path(meta["projects"][proj_id]["dir"]) / "output.log"
    if log_path.exists():
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            content = "".join(lines[-25:]) if lines else "No logs."
    else:
        content = "No logs yet."
    if len(content) > 3700:
        content = content[-3700:]
    text = (
        f"📊 Logs for {meta['projects'][proj_id]['name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"```text\n{content}\n```"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"proj_logs:{proj_id}"),
         InlineKeyboardButton("📥 Download", callback_data=f"proj_download_logs:{proj_id}")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data=f"proj_view:{proj_id}")]
    ])
    await context.bot.edit_message_text(
        text, chat_id=update.effective_chat.id, message_id=message_id,
        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )

async def show_env_editor(update, context, proj_id, message_id):
    meta = load_meta()
    if proj_id not in meta["projects"]:
        await context.bot.edit_message_text("❌ Project not found.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    env_file = Path(meta["projects"][proj_id]["dir"]) / ".env"
    content = "No .env file."
    if env_file.exists():
        with open(env_file, 'r') as f:
            content = f.read().strip() or "Empty."
    text = (
        f"📝 Environment Variables\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Project: `{meta['projects'][proj_id]['name']}`\n\n"
        f"```text\n{content}\n```"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add", callback_data=f"proj_add_env:{proj_id}"),
         InlineKeyboardButton("🗑 Clear", callback_data=f"proj_clear_env:{proj_id}")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data=f"proj_view:{proj_id}")]
    ])
    await context.bot.edit_message_text(
        text, chat_id=update.effective_chat.id, message_id=message_id,
        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )

async def show_file_manager(update, context, proj_id, message_id):
    meta = load_meta()
    if proj_id not in meta["projects"]:
        await context.bot.edit_message_text("❌ Project not found.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    proj_dir = Path(meta["projects"][proj_id]["dir"])
    files_map = update_project_files_map(proj_id, proj_dir)
    text = f"📁 File Manager – `{meta['projects'][proj_id]['name']}`\n\n"
    keyboard = InlineKeyboardMarkup(row_width=4)
    count = 0
    for idx, rel_path in list(files_map.items())[:20]:
        text += f"• `{rel_path}`\n"
        keyboard.add(
            InlineKeyboardButton("👁", callback_data=f"vf:{proj_id}:{idx}"),
            InlineKeyboardButton("✏️", callback_data=f"ef:{proj_id}:{idx}"),
            InlineKeyboardButton("🔄", callback_data=f"rf:{proj_id}:{idx}"),
            InlineKeyboardButton("🗑", callback_data=f"df:{proj_id}:{idx}")
        )
        count += 1
    if len(files_map) > 20:
        text += f"\n... and {len(files_map)-20} more files."
    keyboard.add(InlineKeyboardButton("🔙 Dashboard", callback_data=f"proj_view:{proj_id}"))
    await context.bot.edit_message_text(
        text, chat_id=update.effective_chat.id, message_id=message_id,
        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )

async def view_file(update, context, proj_id, file_idx, message_id):
    meta = load_meta()
    if proj_id not in meta["projects"]:
        await context.bot.edit_message_text("❌ Project not found.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    files_map = meta["projects"][proj_id].get("files", {})
    if file_idx not in files_map:
        await context.bot.edit_message_text("❌ File not found.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    rel_path = files_map[file_idx]
    target = Path(meta["projects"][proj_id]["dir"]) / rel_path
    if not target.exists():
        await context.bot.edit_message_text("❌ File not found on disk.", chat_id=update.effective_chat.id, message_id=message_id)
        return
    try:
        with open(target, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(1500)
            if len(content) >= 1500:
                content += "\n\n... [truncated]"
    except Exception as e:
        content = f"Error reading file: {e}"
    text = f"📄 {rel_path}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n```text\n{content}\n```"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit", callback_data=f"ef:{proj_id}:{file_idx}"),
         InlineKeyboardButton("🔙 Files", callback_data=f"proj_fm:{proj_id}")]
    ])
    await context.bot.edit_message_text(
        text, chat_id=update.effective_chat.id, message_id=message_id,
        parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )

# ============= TEXT AND DOCUMENT HANDLERS =============
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text
    if is_banned(user.id):
        await update.message.reply_text("⛔ You are banned.")
        return
    if not await check_force_join(user.id, context):
        await update.message.reply_text("Please join our channels first.", reply_markup=get_force_join_keyboard())
        return
    register_user(user.id, user.username or "", user.first_name or "")

    # Handle state-based inputs
    if 'add_env_project' in context.user_data:
        proj_id = context.user_data.pop('add_env_project')
        if '=' in text:
            env_file = Path(load_meta()["projects"][proj_id]["dir"]) / ".env"
            with open(env_file, 'a') as f:
                f.write(f"\n{text}")
            await update.message.reply_text("✅ Environment variable added.")
        else:
            await update.message.reply_text("❌ Invalid format. Use KEY=VALUE")
        return

    if 'edit_file' in context.user_data:
        proj_id, rel_path = context.user_data.pop('edit_file')
        target = Path(load_meta()["projects"][proj_id]["dir"]) / rel_path
        try:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(text)
            await update.message.reply_text(f"✅ File `{rel_path}` updated.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    if 'replace_file' in context.user_data:
        # Handled by document handler
        pass

    # Main menu buttons
    if text == "🚀 Deploy New":
        await deploy_start(update, context)
    elif text == "📁 My Projects":
        await my_projects(update, context)
    elif text == "🖥️ Server Status":
        await server_status(update, context)
    elif text == "❔ Help":
        await help_command(update, context)
    elif text == "📞 Contact Owner":
        await update.message.reply_text("📞 Contact: @Shihab_71S")
    elif text == "📊 My Stats":
        await my_stats(update, context)
    elif text == "🛠️ Admin Panel" and (is_admin(user.id) or is_owner(user.id)):
        await update.message.reply_text(
            "🛠️ Admin Panel",
            reply_markup=get_admin_keyboard() if not is_owner(user.id) else get_owner_keyboard()
        )
    elif text == "📊 Dashboard" and is_admin(user.id):
        await admin_dashboard(update, context)
    elif text == "👥 Users" and is_admin(user.id):
        await admin_users(update, context)
    elif text == "📢 Broadcast" and is_admin(user.id):
        await broadcast_start(update, context)
    elif text == "⛔ Ban Management" and is_admin(user.id):
        await ban_management(update, context)
    elif text == "👑 Admin Management" and is_owner(user.id):
        await admin_management(update, context)
    elif text == "⏳ Pending Approvals" and is_admin(user.id):
        await pending_approvals(update, context)
    elif text == "🔙 Back to User":
        await back_to_user(update, context)
    else:
        await update.message.reply_text("Use the buttons below.", reply_markup=get_user_keyboard(user.id))

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("⛔ You are banned.")
        return
    if not await check_force_join(user.id, context):
        await update.message.reply_text("Please join our channels first.")
        return

    # Check if we are in replace file state
    if 'replace_file' in context.user_data:
        proj_id, rel_path = context.user_data.pop('replace_file')
        meta = load_meta()
        if proj_id not in meta["projects"]:
            await update.message.reply_text("❌ Project not found.")
            return
        target = Path(meta["projects"][proj_id]["dir"]) / rel_path
        try:
            file_obj = await context.bot.get_file(update.message.document.file_id)
            await file_obj.download_to_drive(target)
            await update.message.reply_text(f"✅ File `{rel_path}` replaced.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    # Otherwise, treat as deploy if in deploy state? But we use conversation for deploy.
    # If not in deploy state, ignore.
    await update.message.reply_text("Please use the Deploy New button to upload a zip.")

# ============= ADMIN COMMANDS =============
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Only owner can add admins.")
        return
    try:
        user_id = int(context.args[0])
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
            await update.message.reply_text(f"✅ User {user_id} added as admin.")
        else:
            await update.message.reply_text(f"ℹ️ User {user_id} is already admin.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addadmin <user_id>")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Only owner can remove admins.")
        return
    try:
        user_id = int(context.args[0])
        if user_id == OWNER_ID:
            await update.message.reply_text("❌ Cannot remove owner.")
            return
        if user_id in ADMIN_IDS:
            ADMIN_IDS.remove(user_id)
            await update.message.reply_text(f"✅ User {user_id} removed from admins.")
        else:
            await update.message.reply_text(f"ℹ️ User {user_id} is not an admin.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /removeadmin <user_id>")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    try:
        target = int(context.args[0])
        if target == OWNER_ID:
            await update.message.reply_text("❌ Cannot ban owner.")
            return
        if target == update.effective_user.id:
            await update.message.reply_text("❌ Cannot ban yourself.")
            return
        if ban_user(target):
            await update.message.reply_text(f"✅ User {target} banned.")
        else:
            await update.message.reply_text(f"ℹ️ User {target} already banned.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ban <user_id>")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    try:
        target = int(context.args[0])
        if unban_user(target):
            await update.message.reply_text(f"✅ User {target} unbanned.")
        else:
            await update.message.reply_text(f"ℹ️ User {target} not banned.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /unban <user_id>")

# ============= MAIN =============
async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Error: Please set BOT_TOKEN environment variable.")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CallbackQueryHandler(force_join_callback, pattern="force_join_check"))
    application.add_handler(CallbackQueryHandler(project_callback, pattern="^(approve:|reject:|view_pending:|select_main:|proj_|vf:|ef:|rf:|df:|btn_)"))

    # Deploy conversation
    deploy_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🚀 Deploy New$"), deploy_start)],
        states={
            DEPLOY_STATE: [
                MessageHandler(filters.Document.ALL, handle_deploy_zip),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(deploy_conv)

    # Broadcast conversation
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), broadcast_start)],
        states={
            BROADCAST_STATE: [
                MessageHandler(filters.TEXT | filters.Document.ALL | filters.PHOTO, broadcast_send),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(broadcast_conv)

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    await application.initialize()
    # Check bot membership in channels
    await check_force_join(OWNER_ID, application.bot)  # just a dummy call to log errors
    await application.start()
    await application.updater.start_polling()

    print("Bot is running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
    
 
