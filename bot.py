#!/usr/bin/env python3
"""
NEXA TASKS — single-file Telegram task/rewards bot.

Safety design:
- Never asks for or stores passwords, Instagram 2FA/TOTP secrets, session cookies,
  access tokens, or other authentication secrets.
- Instagram/Facebook tasks accept a non-sensitive proof description or public URL.
- Uses Telegram long polling and a local JSON database.
- This is a starter implementation; review deployment, payment, fraud, and legal
  requirements before using it with real money.
"""
import csv
import html
import io
import json
import os
import re
import time
import uuid
import logging
from pathlib import Path

import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
DB_PATH = Path(os.getenv("DB_PATH", "database.json"))
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}/"
FILE_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()
session.headers.update({"User-Agent": "NexaTasksBot/1.0"})

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🧭 ᴡᴏʀᴋ"}, {"text": "💰 ʙᴀʟᴀɴᴄᴇ"}],
        [{"text": "💸 ᴡɪᴛʜᴅʀᴀᴡ"}, {"text": "🎁 ʀᴇғᴇʀʀᴀʟs"}],
        [{"text": "💬 sᴜᴘᴘᴏʀᴛ"}, {"text": "🆕 ɢᴜɪᴅᴇ"}],
    ],
    "resize_keyboard": True,
}
CANCEL_KEYBOARD = {"keyboard": [[{"text": "✖️ ᴄᴀɴᴄᴇʟ"}]], "resize_keyboard": True}
PLATFORM_KEYBOARD = {
    "keyboard": [
        [{"text": "📸 ɪɴsᴛᴀɢʀᴀᴍ ᴡᴏʀᴋ"}, {"text": "📘 ғᴀᴄᴇʙᴏᴏᴋ ᴡᴏʀᴋ"}],
        [{"text": "📢 ᴛᴇʟᴇɢʀᴀᴍ ᴛᴀsᴋ"}, {"text": "✖️ ᴄᴀɴᴄᴇʟ"}],
    ],
    "resize_keyboard": True,
}
ADMIN_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "👥 ᴜsᴇʀs", "callback_data": "admin:users"},
         {"text": "📣 ʙʀᴏᴀᴅᴄᴀsᴛ", "callback_data": "admin:broadcast"}],
        [{"text": "✅ ᴀᴘᴘʀᴏᴠᴇ ɪɢ", "callback_data": "admin:approve:ig"},
         {"text": "✅ ᴀᴘᴘʀᴏᴠᴇ ғʙ", "callback_data": "admin:approve:fb"}],
        [{"text": "📤 ᴇxᴘᴏʀᴛ ɪɢ", "callback_data": "admin:export:ig"},
         {"text": "📤 ᴇxᴘᴏʀᴛ ғʙ", "callback_data": "admin:export:fb"}],
        [{"text": "💵 sᴇᴛ ʀᴀᴛᴇs", "callback_data": "admin:rates"},
         {"text": "💬 sᴜᴘᴘᴏʀᴛ ᴜʀʟ", "callback_data": "admin:support"}],
        [{"text": "💸 ᴡɪᴛʜᴅʀᴀᴡ ᴍᴇᴛʜᴏᴅs", "callback_data": "admin:methods"},
         {"text": "🆕 ɴᴇᴡ ᴜsᴇʀ ɢᴜɪᴅᴇ", "callback_data": "admin:guide:new"}],
        [{"text": "📸 sᴇᴛ ɪɢ ɢᴜɪᴅᴇ", "callback_data": "admin:guide:ig"},
         {"text": "📘 sᴇᴛ ғʙ ɢᴜɪᴅᴇ", "callback_data": "admin:guide:fb"}],
        [{"text": "🎁 ʀᴇғᴇʀʀᴀʟ sᴇᴛᴛɪɴɢs", "callback_data": "admin:ref"},
         {"text": "📌 ғᴏʀᴄᴇ sᴜʙ", "callback_data": "admin:forcesub"}],
        [{"text": "📥 ᴅᴏᴡɴʟᴏᴀᴅ ᴅʙ", "callback_data": "admin:db:download"},
         {"text": "📤 ᴜᴘʟᴏᴀᴅ ᴅʙ", "callback_data": "admin:db:upload"}],
    ]
}
users_states = {}
current_tasks = {}
bot_username = "NexaTasksBot"


def defaults():
    return {
        "users": {},
        "submissions": [],
        "referral_commissions": [],
        "rates": {"ig_2fa": 3.0, "fb_cookies": 4.5, "telegram_task": 2.0},
        "admin_settings": {
            "supportUrl": "https://t.me/",
            "withdrawMethods": [{"name": "bKash", "minAmount": 50.0},
                                {"name": "Nagad", "minAmount": 50.0}],
            "newUserGuide": {"type": "text", "text": "Welcome to NEXA TASKS. Complete tasks using only non-sensitive proof. Never send passwords, 2FA keys, cookies, or login codes.", "fileId": None, "caption": ""},
            "igGuide": {"type": "text", "text": "Complete the assigned legitimate task, then submit a public URL or short description as proof. Never share a password or 2FA secret.", "fileId": None, "caption": ""},
            "fbGuide": {"type": "text", "text": "Submit a public URL or non-sensitive proof description only. Never share Facebook cookies, access tokens, passwords, or login codes.", "fileId": None, "caption": ""},
            "referralTasksRequired": 5,
            "referralBonusAmount": 10.0,
            "referralPayoutMode": "on_join",
            "admins": [],
            "must_join_channel": "",
            "demoSeedVersion": 1,
        },
    }


def load_db():
    if not DB_PATH.exists():
        data = defaults()
        save_db(data)
        return data
    try:
        data = json.loads(DB_PATH.read_text(encoding="utf-8"))
        base = defaults()
        for key, value in base.items():
            if key not in data:
                data[key] = value
        for key, value in base["admin_settings"].items():
            data["admin_settings"].setdefault(key, value)
        for key, value in base["rates"].items():
            data["rates"].setdefault(key, value)
        return data
    except Exception:
        logging.exception("Database could not be read; preserving the old file and using defaults.")
        raise RuntimeError("database.json is invalid. Restore a valid backup before restarting.")


def save_db(data=None):
    global db
    if data is not None:
        db = data
    tmp = DB_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DB_PATH)
    except Exception:
        logging.exception("Database save failed")
        raise


def clean_payload(value):
    """Recursively remove custom emoji metadata/tags from outgoing payloads."""
    if isinstance(value, dict):
        return {k: clean_payload(v) for k, v in value.items()
                if k != "icon_custom_emoji_id"}
    if isinstance(value, list):
        return [clean_payload(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', r'\1', value, flags=re.I | re.S)
        return value
    return value


def api(method, payload=None, files=None, timeout=60):
    if not BOT_TOKEN:
        return {}
    try:
        response = session.post(API_BASE + method, data=clean_payload(payload or {}),
                                files=files, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        return body if body.get("ok") else {}
    except Exception:
        logging.exception("Telegram API call failed: %s", method)
        return {}


def send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api("sendMessage", payload).get("result", {})


def answer_callback(callback_id, text="", alert=False):
    api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text,
                                "show_alert": alert})


def edit_text(chat_id, message_id, text, markup=None):
    p = {"chat_id": chat_id, "message_id": message_id, "text": text,
         "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        p["reply_markup"] = markup
    return api("editMessageText", p)


def is_admin(uid):
    return int(uid) == ADMIN_ID or int(uid) in [int(x) for x in db["admin_settings"].get("admins", [])]


def safe(s):
    return html.escape(str(s or ""), quote=False)


def init_user(tg_user, referrer=None):
    uid = str(tg_user["id"])
    if uid in db["users"]:
        u = db["users"][uid]
        u["username"] = tg_user.get("username", u.get("username", ""))
        u["first_name"] = tg_user.get("first_name", u.get("first_name", ""))
        save_db()
        return False
    valid_ref = str(referrer) if referrer and str(referrer) in db["users"] and str(referrer) != uid else None
    db["users"][uid] = {
        "id": int(uid), "username": tg_user.get("username", ""),
        "first_name": tg_user.get("first_name", ""), "balance": 0.0,
        "totalEarned": 0.0, "joinedAt": int(time.time()), "referredBy": valid_ref,
        "referralBonusPaid": False, "referralCommissionPaid": False, "isDemo": False,
    }
    save_db()
    if valid_ref and db["admin_settings"].get("referralPayoutMode", "on_join") == "on_join":
        pay_referral_commission(valid_ref, uid, notify=True)
    return True


def pay_referral_commission(referrer_id, referred_id, notify=True):
    referred = db["users"].get(str(referred_id))
    referrer = db["users"].get(str(referrer_id))
    if not referred or not referrer or referred.get("referralCommissionPaid"):
        return False
    amount = float(db["admin_settings"].get("referralBonusAmount", 10.0))
    referrer["balance"] = round(float(referrer.get("balance", 0)) + amount, 2)
    referrer["totalEarned"] = round(float(referrer.get("totalEarned", 0)) + amount, 2)
    referred["referralCommissionPaid"] = True
    referred["referralBonusPaid"] = True
    db["referral_commissions"].append({
        "id": "REF" + uuid.uuid4().hex[:12].upper(),
        "referrerId": int(referrer_id), "referredUserId": int(referred_id),
        "amount": amount, "status": "paid", "paidAt": int(time.time()), "legacy": False,
    })
    save_db()
    if notify:
        send(int(referrer_id), f"🎁 Referral reward: <b>৳{amount:.2f}</b> credited for a new referral.")
    return True


def migrate_referral_commissions():
    changed = False
    for uid, user in list(db["users"].items()):
        ref = user.get("referredBy")
        if not ref or user.get("referralCommissionPaid"):
            continue
        if user.get("referralBonusPaid"):
            user["referralCommissionPaid"] = True
            db["referral_commissions"].append({
                "id": "REF" + uuid.uuid4().hex[:12].upper(),
                "referrerId": int(ref), "referredUserId": int(uid),
                "amount": float(db["admin_settings"].get("referralBonusAmount", 10.0)),
                "status": "paid", "paidAt": int(time.time()), "legacy": True,
            })
            changed = True
        elif db["admin_settings"].get("referralPayoutMode", "on_join") == "on_join":
            changed = pay_referral_commission(ref, uid, notify=False) or changed
    if changed:
        save_db()


def check_force_sub(uid):
    channel = db["admin_settings"].get("must_join_channel", "").strip()
    if not channel:
        return True
    result = api("getChatMember", {"chat_id": channel, "user_id": uid})
    member = result.get("result", {})
    return member.get("status") in ("member", "administrator", "creator")


def ask_force_sub(chat_id):
    channel = db["admin_settings"].get("must_join_channel", "").strip()
    channel_url = "https://t.me/" + channel.lstrip("@")
    send(chat_id, "ᴛᴏ ᴜsᴇ ᴛʜɪs ʙᴏᴛ, ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғɪʀsᴛ.",
         {"inline_keyboard": [
             [{"text": "📢 Join channel", "url": channel_url}],
             [{"text": "✅ ɪ'ᴠᴇ ᴊᴏɪɴᴇᴅ", "callback_data": "check_sub"}],
         ]})


def main_menu(chat_id, text="ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɴᴇxᴀ ᴛᴀsᴋs\nsᴍᴀʀᴛ ᴡᴏʀᴋ • sɪᴍᴘʟᴇ ʀᴇᴡᴀʀᴅs"):
    users_states[chat_id] = "main"
    current_tasks.pop(chat_id, None)
    send(chat_id, text, MAIN_KEYBOARD)


def send_guide(chat_id, key):
    guide = db["admin_settings"].get(key, {}) or {}
    typ = guide.get("type", "text")
    text = guide.get("text", "") if typ == "text" else guide.get("caption", "")
    if typ == "text":
        send(chat_id, text or "Guide not configured.")
    elif typ in ("photo", "video", "audio", "voice", "document") and guide.get("fileId"):
        api("send" + typ.title(), {"chat_id": chat_id, typ: guide["fileId"],
            "caption": text, "parse_mode": "HTML"})
    else:
        send(chat_id, "Guide not configured yet.")


def task_menu(chat_id, platform):
    if platform == "ig":
        rate = float(db["rates"].get("ig_2fa", 3.0))
        current_tasks[chat_id] = {"platform": "Instagram 2FA", "reward": rate}
        send(chat_id, f"📸 <b>Instagram task</b>\nReward: <b>৳{rate:.2f}</b>\n\nComplete the legitimate task and submit a public URL or a short, non-sensitive proof description. Never send login credentials or 2FA keys.",
             {"keyboard": [[{"text": "📨 sᴜʙᴍɪᴛ ᴘʀᴏᴏғ"}, {"text": "❔ ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs"}],
                           [{"text": "✖️ ᴄᴀɴᴄᴇʟ"}]], "resize_keyboard": True})
        users_states[chat_id] = "task_menu"
    elif platform == "fb":
        rate = float(db["rates"].get("fb_cookies", 4.5))
        current_tasks[chat_id] = {"platform": "Facebook task", "reward": rate}
        send(chat_id, f"📘 <b>Facebook task</b>\nReward: <b>৳{rate:.2f}</b>\n\nSubmit a public URL or non-sensitive proof description only. Do not send cookies, passwords, access tokens, or login codes.",
             {"keyboard": [[{"text": "📨 sᴜʙᴍɪᴛ ᴘʀᴏᴏғ"}, {"text": "❔ ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs"}],
                           [{"text": "✖️ ᴄᴀɴᴄᴇʟ"}]], "resize_keyboard": True})
        users_states[chat_id] = "task_menu"
    else:
        rate = float(db["rates"].get("telegram_task", 2.0))
        current_tasks[chat_id] = {"platform": "Telegram task", "reward": rate}
        send(chat_id, f"📢 <b>Telegram task</b>\nReward: <b>৳{rate:.2f}</b>\nSubmit a public post/channel URL or a short proof description. Reward: ৳{rate:.2f}.",
             {"keyboard": [[{"text": "📨 sᴜʙᴍɪᴛ ᴘʀᴏᴏғ"}, {"text": "✖️ ᴄᴀɴᴄᴇʟ"}]], "resize_keyboard": True})
        users_states[chat_id] = "task_menu"


def create_submission(uid, proof):
    task = current_tasks.get(uid)
    if not task:
        return False
    proof = proof.strip()
    if not proof or len(proof) < 3:
        return False
    # Basic guard against common credential/session-secret formats.
    lower = proof.lower()
    forbidden = ("c_user=", "xs=", "sessionid=", "password:", "passwd:", "totp secret", "access_token=")
    if any(x in lower for x in forbidden):
        return "sensitive"
    db["submissions"].append({
        "id": uuid.uuid4().hex[:10], "userId": int(uid),
        "username": db["users"].get(str(uid), {}).get("username", ""),
        "platform": task["platform"], "providedDetails": "Public proof / task description",
        "userSubmission": proof[:3000], "status": "pending",
        "reward": float(task["reward"]), "submittedAt": int(time.time()),
    })
    save_db()
    return True


def user_balance(chat_id):
    uid = str(chat_id)
    user = db["users"].get(uid, {})
    subs = [s for s in db["submissions"] if str(s["userId"]) == uid]
    pending = sum(s["status"] == "pending" for s in subs)
    approved = sum(s["status"] == "approved" for s in subs)
    send(chat_id, f"💰 <b>ʙᴀʟᴀɴᴄᴇ</b>\nAvailable: <b>৳{user.get('balance', 0):.2f}</b>\nTotal earned: <b>৳{user.get('totalEarned', 0):.2f}</b>\nPending tasks: <b>{pending}</b>\nApproved tasks: <b>{approved}</b>", MAIN_KEYBOARD)


def referral_info(chat_id):
    user = db["users"].get(str(chat_id), {})
    count = sum(1 for u in db["users"].values() if str(u.get("referredBy")) == str(chat_id))
    paid = sum(1 for c in db["referral_commissions"] if str(c.get("referrerId")) == str(chat_id))
    bonus = float(db["admin_settings"].get("referralBonusAmount", 10))
    send(chat_id, f"🎁 <b>ʀᴇғᴇʀʀᴀʟs</b>\nYour link: <code>https://t.me/{safe(bot_username)}?start={chat_id}</code>\nTotal referrals: {count}\nCommissions paid: {paid}\nReward per referral: ৳{bonus:.2f}", MAIN_KEYBOARD)


def withdraw_start(chat_id):
    methods = db["admin_settings"].get("withdrawMethods", [])
    if not methods:
        send(chat_id, "No withdrawal methods are configured.", MAIN_KEYBOARD)
        return
    rows = [[{"text": m["name"]}] for m in methods]
    rows.append([{"text": "✖️ ᴄᴀɴᴄᴇʟ"}])
    users_states[chat_id] = "awaiting_withdraw_method"
    send(chat_id, "Choose a withdrawal method:", {"keyboard": rows, "resize_keyboard": True})


def admin_panel(chat_id):
    send(chat_id, "👑 <b>NEXA TASKS ADMIN</b>", ADMIN_KEYBOARD)


def admin_users(chat_id):
    users = list(db["users"].values())
    pending = sum(s["status"] == "pending" for s in db["submissions"])
    approved = sum(s["status"] == "approved" for s in db["submissions"])
    demo = sum(bool(u.get("isDemo")) for u in users)
    wallet = sum(float(u.get("balance", 0)) for u in users)
    send(chat_id, f"Users: {len(users)}\nDemo users: {demo}\nPending submissions: {pending}\nApproved submissions: {approved}\nTotal wallet balance: ৳{wallet:.2f}", ADMIN_KEYBOARD)


def pending_user_keyboard(platform_key):
    target = "Instagram 2FA" if platform_key == "ig" else "Facebook task"
    counts = {}
    for s in db["submissions"]:
        if s["platform"] == target and s["status"] == "pending":
            counts[str(s["userId"])] = counts.get(str(s["userId"]), 0) + 1
    rows = []
    for uid, count in counts.items():
        user = db["users"].get(uid, {})
        name = user.get("first_name") or user.get("username") or uid
        rows.append([{"text": f"{name} ({count})", "callback_data": f"admin:user:{platform_key}:{uid}"}])
    rows.append([{"text": "⬅️ Admin panel", "callback_data": "admin:home"}])
    return {"inline_keyboard": rows}


def handle_admin_callback(cb, chat_id, data):
    if not is_admin(chat_id):
        answer_callback(cb, "Not authorized.", True)
        return
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "home":
        admin_panel(chat_id)
    elif action == "users":
        admin_users(chat_id)
    elif action == "broadcast":
        users_states[chat_id] = "admin_awaiting_broadcast"
        send(chat_id, "Send the broadcast message. Use /cancel to stop.", CANCEL_KEYBOARD)
    elif action == "approve" and len(parts) == 3:
        platform = parts[2]
        label = "Instagram 2FA" if platform == "ig" else "Facebook task"
        send(chat_id, f"Pending users for {label}:", pending_user_keyboard(platform))
    elif action == "user" and len(parts) == 4:
        platform, uid = parts[2], parts[3]
        label = "Instagram 2FA" if platform == "ig" else "Facebook task"
        count = sum(1 for s in db["submissions"] if str(s["userId"]) == uid and s["platform"] == label and s["status"] == "pending")
        users_states[chat_id] = f"admin_awaiting_appr_count_{uid}_{platform}"
        send(chat_id, f"User {uid} has {count} pending submissions.\nEnter how many to approve (0–{count}); the rest will be rejected.", CANCEL_KEYBOARD)
    elif action == "export" and len(parts) == 3:
        export_submissions(chat_id, parts[2])
    elif action == "rates":
        send(chat_id, f"IG: ৳{db['rates']['ig_2fa']:.2f}\nFB: ৳{db['rates']['fb_cookies']:.2f}\nTelegram: ৳{db['rates'].get('telegram_task', 2):.2f}",
             {"inline_keyboard": [
                 [{"text": "Set IG rate", "callback_data": "admin:setrate:ig"}],
                 [{"text": "Set FB rate", "callback_data": "admin:setrate:fb"}],
                 [{"text": "Set Telegram rate", "callback_data": "admin:setrate:tg"}],
             ]})
    elif action == "setrate" and len(parts) == 3:
        key = {"ig": "ig_2fa", "fb": "fb_cookies", "tg": "telegram_task"}[parts[2]]
        users_states[chat_id] = "admin_awaiting_rate_" + key
        send(chat_id, "Enter the new positive rate in BDT:", CANCEL_KEYBOARD)
    elif action == "support":
        users_states[chat_id] = "admin_awaiting_support_url"
        send(chat_id, "Send the support URL (https://... or https://t.me/...).", CANCEL_KEYBOARD)
    elif action == "methods":
        methods = db["admin_settings"].get("withdrawMethods", [])
        listing = "\n".join(f"• {safe(m['name'])}: minimum ৳{float(m['minAmount']):.2f}" for m in methods) or "No methods."
        send(chat_id, listing, {"inline_keyboard": [
            [{"text": "Add method", "callback_data": "admin:method:add"}],
            [{"text": "Clear all", "callback_data": "admin:method:clear"}],
            [{"text": "Admin panel", "callback_data": "admin:home"}],
        ]})
    elif action == "method" and len(parts) == 3:
        if parts[2] == "add":
            users_states[chat_id] = "admin_awaiting_withdraw_name"
            send(chat_id, "Enter the withdrawal method name:", CANCEL_KEYBOARD)
        elif parts[2] == "clear":
            db["admin_settings"]["withdrawMethods"] = []
            save_db()
            send(chat_id, "Withdrawal methods cleared.", ADMIN_KEYBOARD)
    elif action == "guide" and len(parts) == 3:
        key = {"new": "newUserGuide", "ig": "igGuide", "fb": "fbGuide"}[parts[2]]
        users_states[chat_id] = "admin_awaiting_guide_" + key
        send(chat_id, "Send a text, photo, video, audio, voice, or document to save as this guide.", CANCEL_KEYBOARD)
    elif action == "ref" and len(parts) == 2:
        send(chat_id, f"Referral task requirement: {db['admin_settings']['referralTasksRequired']}\nReferral bonus: ৳{db['admin_settings']['referralBonusAmount']:.2f}",
             {"inline_keyboard": [
                 [{"text": "Set required tasks", "callback_data": "admin:ref:tasks"}],
                 [{"text": "Set referral bonus", "callback_data": "admin:ref:bonus"}],
             ]})
    elif action == "forcesub":
        users_states[chat_id] = "admin_awaiting_channel"
        send(chat_id, "Send channel username (e.g. @mychannel) or 'none' to disable. Bot must be an admin in the channel.", CANCEL_KEYBOARD)
    elif action == "db" and len(parts) == 3:
        if parts[2] == "download":
            try:
                with open(DB_PATH, "rb") as f:
                    api("sendDocument", {"chat_id": chat_id, "caption": "Database backup"}, {"document": f})
            except Exception:
                send(chat_id, "Could not send database backup.")
        else:
            users_states[chat_id] = "admin_awaiting_db"
            send(chat_id, "Upload database.json as a document. Only upload a trusted backup.", CANCEL_KEYBOARD)
    elif action == "ref" and len(parts) == 3:
        if parts[2] == "tasks":
            users_states[chat_id] = "admin_awaiting_ref_tasks"
            send(chat_id, "Enter required approved tasks (integer >= 1):", CANCEL_KEYBOARD)
        elif parts[2] == "bonus":
            users_states[chat_id] = "admin_awaiting_ref_bonus"
            send(chat_id, "Enter referral bonus (positive BDT amount):", CANCEL_KEYBOARD)
    else:
        answer_callback(cb, "Unknown action.", True)


def export_submissions(chat_id, platform_key):
    label = "Instagram 2FA" if platform_key == "ig" else "Facebook task"
    rows = [s for s in db["submissions"] if s["platform"] == label and s["status"] == "pending"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User ID", "Username", "Platform", "Bot Provided Details", "User Submission", "Submitted At"])
    for s in rows:
        writer.writerow([s["userId"], s.get("username", ""), s["platform"], s.get("providedDetails", ""),
                         s.get("userSubmission", ""), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["submittedAt"]))])
    payload = output.getvalue().encode("utf-8-sig")
    api("sendDocument", {"chat_id": chat_id, "caption": f"Pending {label} submissions"},
        {"document": ("pending_submissions.csv", payload, "text/csv")})


def get_message_content(msg):
    if msg.get("text") is not None:
        return {"type": "text", "text": msg["text"], "fileId": None, "caption": ""}
    for typ in ("photo", "video", "audio", "voice", "document"):
        if msg.get(typ):
            item = msg[typ][-1] if typ == "photo" else msg[typ]
            return {"type": typ, "text": "", "fileId": item.get("file_id"),
                    "caption": msg.get("caption", "")}
    return None


def handle_message(msg):
    chat = msg.get("chat", {})
    uid = int(chat.get("id", 0))
    if chat.get("type") != "private":
        return
    user = msg.get("from", {})
    text = (msg.get("text") or "").strip()
    if text.startswith("/start"):
        args = text.split(maxsplit=1)
        ref = args[1].strip() if len(args) > 1 and args[1].strip().isdigit() else None
        init_user(user, ref)
        if not check_force_sub(uid):
            ask_force_sub(uid)
            return
        main_menu(uid)
        return
    if text == "/cancel" or text == "✖️ ᴄᴀɴᴄᴇʟ":
        main_menu(uid, "Cancelled. Main menu:")
        return
    if str(uid) not in db["users"]:
        init_user(user)
    if not is_admin(uid) and not check_force_sub(uid):
        ask_force_sub(uid)
        return
    state = users_states.get(uid, "main")

    if text == "/admin" and is_admin(uid):
        admin_panel(uid)
        return
    if state.startswith("admin_") or state.startswith("owner_"):
        handle_admin_message(msg, uid, state)
        return

    if text == "🧭 ᴡᴏʀᴋ":
        users_states[uid] = "main"
        send(uid, "Choose a task category:", PLATFORM_KEYBOARD)
    elif text == "💰 ʙᴀʟᴀɴᴄᴇ":
        user_balance(uid)
    elif text == "💸 ᴡɪᴛʜᴅʀᴀᴡ":
        withdraw_start(uid)
    elif text == "🎁 ʀᴇғᴇʀʀᴀʟs":
        referral_info(uid)
    elif text == "💬 sᴜᴘᴘᴏʀᴛ":
        url = db["admin_settings"].get("supportUrl", "https://t.me/")
        send(uid, "Contact support using the button below.", {"inline_keyboard": [[{"text": "💬 Support", "url": url}]]})
    elif text == "🆕 ɢᴜɪᴅᴇ":
        send_guide(uid, "newUserGuide")
    elif text == "📸 ɪɴsᴛᴀɢʀᴀᴍ ᴡᴏʀᴋ":
        task_menu(uid, "ig")
    elif text == "📘 ғᴀᴄᴇʙᴏᴏᴋ ᴡᴏʀᴋ":
        task_menu(uid, "fb")
    elif text == "📢 ᴛᴇʟᴇɢʀᴀᴍ ᴛᴀsᴋ":
        task_menu(uid, "tg")
    elif text == "❔ ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs":
        task = current_tasks.get(uid, {})
        send_guide(uid, "igGuide" if task.get("platform") == "Instagram 2FA" else "fbGuide")
    elif text == "📨 sᴜʙᴍɪᴛ ᴘʀᴏᴏғ":
        if uid not in current_tasks:
            send(uid, "Select a task first.", MAIN_KEYBOARD)
            return
        users_states[uid] = "awaiting_task_proof"
        send(uid, "Send a public URL or short proof description only. Do not send passwords, 2FA keys, cookies, access tokens, or login codes.", CANCEL_KEYBOARD)
    elif state == "awaiting_task_proof":
        result = create_submission(uid, text)
        if result == "sensitive":
            send(uid, "This looks like authentication data. For your safety, credentials, 2FA secrets, cookies, and tokens are not accepted. Send a public URL or non-sensitive proof description.")
        elif result:
            current_tasks.pop(uid, None)
            users_states[uid] = "main"
            send(uid, "✅ Proof submitted for review. Your reward will be credited if approved.", MAIN_KEYBOARD)
        else:
            send(uid, "Please submit a valid proof description or public URL (at least 3 characters).")
    elif state == "awaiting_withdraw_method":
        methods = db["admin_settings"].get("withdrawMethods", [])
        chosen = next((m for m in methods if m["name"] == text), None)
        if not chosen:
            send(uid, "Please select a configured method using its keyboard button.")
            return
        current_tasks[uid] = {"withdrawMethod": chosen}
        users_states[uid] = "awaiting_withdraw_amount"
        send(uid, f"Enter amount in BDT (minimum ৳{float(chosen['minAmount']):.2f}):", CANCEL_KEYBOARD)
    elif state == "awaiting_withdraw_amount":
        try:
            amount = round(float(text), 2)
            method = current_tasks[uid]["withdrawMethod"]
            balance = float(db["users"][str(uid)].get("balance", 0))
            if amount < float(method["minAmount"]) or amount > balance or amount <= 0:
                raise ValueError
            # A request record is created for review; funds are reserved by deducting now.
            db.setdefault("withdrawals", [])
            db["users"][str(uid)]["balance"] = round(balance - amount, 2)
            db["withdrawals"].append({"id": uuid.uuid4().hex[:10], "userId": uid,
                "method": method["name"], "amount": amount, "status": "pending", "createdAt": int(time.time())})
            save_db()
            current_tasks.pop(uid, None)
            users_states[uid] = "main"
            send(uid, f"Withdrawal request received: ৳{amount:.2f} via {safe(method['name'])}. Admin review is pending.", MAIN_KEYBOARD)
            send(ADMIN_ID, f"💸 New withdrawal request\nUser: {uid}\nMethod: {safe(method['name'])}\nAmount: ৳{amount:.2f}")
        except (ValueError, TypeError, KeyError):
            send(uid, "Invalid amount. Enter a number that meets the minimum and does not exceed your balance.")
    else:
        main_menu(uid, "Please choose an option from the menu.")


def handle_admin_message(msg, uid, state):
    global db
    text = (msg.get("text") or "").strip()
    settings = db["admin_settings"]
    if state == "admin_awaiting_broadcast":
        content = get_message_content(msg)
        if not content:
            send(uid, "Send text, photo, video, audio, voice, or document.")
            return
        success = 0
        for user_id in list(db["users"].keys()):
            try:
                if content["type"] == "text":
                    r = send(int(user_id), content["text"])
                else:
                    method = "send" + content["type"].title()
                    r = api(method, {"chat_id": int(user_id), content["type"]: content["fileId"],
                                     "caption": content["caption"], "parse_mode": "HTML"})
                success += 1 if r else 0
                time.sleep(0.04)
            except Exception:
                continue
        users_states[uid] = "main"
        send(uid, f"Broadcast complete. Delivered to {success}/{len(db['users'])} users.", ADMIN_KEYBOARD)
    elif state.startswith("admin_awaiting_rate_"):
        key = state.replace("admin_awaiting_rate_", "")
        try:
            rate = float(text)
            if rate <= 0 or rate > 100000:
                raise ValueError
            db["rates"][key] = round(rate, 2)
            save_db()
            users_states[uid] = "main"
            send(uid, f"Rate updated to ৳{rate:.2f}.", ADMIN_KEYBOARD)
        except ValueError:
            send(uid, "Enter a valid positive number.")
    elif state == "admin_awaiting_support_url":
        if not re.match(r"^https?://\S+$", text):
            send(uid, "Enter a valid http:// or https:// URL.")
            return
        settings["supportUrl"] = text
        save_db()
        users_states[uid] = "main"
        send(uid, "Support URL updated.", ADMIN_KEYBOARD)
    elif state.startswith("admin_awaiting_guide_"):
        key = state.replace("admin_awaiting_guide_", "")
        content = get_message_content(msg)
        if not content:
            send(uid, "Unsupported message type. Send text, photo, video, audio, voice, or document.")
            return
        settings[key] = content
        save_db()
        users_states[uid] = "main"
        send(uid, "Guide saved.", ADMIN_KEYBOARD)
    elif state == "admin_awaiting_ref_tasks":
        try:
            n = int(text)
            if n < 1 or n > 10000:
                raise ValueError
            settings["referralTasksRequired"] = n
            settings["referralPayoutMode"] = "after_tasks"
            save_db()
            users_states[uid] = "main"
            send(uid, f"Referral payout now requires {n} approved tasks.", ADMIN_KEYBOARD)
        except ValueError:
            send(uid, "Enter a whole number >= 1.")
    elif state == "admin_awaiting_ref_bonus":
        try:
            amount = float(text)
            if amount <= 0 or amount > 100000:
                raise ValueError
            settings["referralBonusAmount"] = round(amount, 2)
            save_db()
            users_states[uid] = "main"
            send(uid, f"Referral bonus set to ৳{amount:.2f}.", ADMIN_KEYBOARD)
        except ValueError:
            send(uid, "Enter a positive BDT amount.")
    elif state == "admin_awaiting_channel":
        settings["must_join_channel"] = "" if text.lower() == "none" else text
        save_db()
        users_states[uid] = "main"
        send(uid, "Force-subscription setting updated.", ADMIN_KEYBOARD)
    elif state == "admin_awaiting_withdraw_name":
        if not text or len(text) > 40:
            send(uid, "Enter a method name up to 40 characters.")
            return
        current_tasks[uid] = {"newMethodName": text}
        users_states[uid] = "admin_awaiting_withdraw_min"
        send(uid, "Enter minimum withdrawal amount in BDT:")
    elif state == "admin_awaiting_withdraw_min":
        try:
            amount = float(text)
            name = current_tasks[uid]["newMethodName"]
            if amount <= 0:
                raise ValueError
            settings["withdrawMethods"].append({"name": name, "minAmount": round(amount, 2)})
            save_db()
            current_tasks.pop(uid, None)
            users_states[uid] = "main"
            send(uid, "Withdrawal method added.", ADMIN_KEYBOARD)
        except (ValueError, KeyError):
            send(uid, "Enter a positive amount.")
    elif state.startswith("admin_awaiting_appr_count_"):
        try:
            _, _, _, uid_text, platform = state.split("_", 4)  # not used; parsed below robustly
        except Exception:
            pass
        match = re.match(r"admin_awaiting_appr_count_(\d+)_(ig|fb)$", state)
        if not match:
            users_states[uid] = "main"
            send(uid, "Invalid approval state.", ADMIN_KEYBOARD)
            return
        target_uid, platform = match.groups()
        label = "Instagram 2FA" if platform == "ig" else "Facebook task"
        pending = [s for s in db["submissions"] if str(s["userId"]) == target_uid and s["platform"] == label and s["status"] == "pending"]
        try:
            n = int(text)
            if n < 0 or n > len(pending):
                raise ValueError
        except ValueError:
            send(uid, f"Enter an integer from 0 to {len(pending)}.")
            return
        approved = rejected = 0
        reward_total = 0.0
        for i, sub in enumerate(pending):
            if i < n:
                sub["status"] = "approved"
                approved += 1
                reward_total += float(sub["reward"])
            else:
                sub["status"] = "rejected"
                rejected += 1
        target = db["users"].get(target_uid)
        if target:
            target["balance"] = round(float(target.get("balance", 0)) + reward_total, 2)
            target["totalEarned"] = round(float(target.get("totalEarned", 0)) + reward_total, 2)
        if target and target.get("referredBy") and not target.get("referralCommissionPaid"):
            mode = settings.get("referralPayoutMode", "on_join")
            count = sum(1 for s in db["submissions"] if str(s["userId"]) == target_uid and s["status"] == "approved")
            if mode == "after_tasks" and count >= int(settings.get("referralTasksRequired", 5)):
                pay_referral_commission(target["referredBy"], target_uid, notify=True)
        save_db()
        send(int(target_uid), f"Task review complete.\nApproved: {approved}\nRejected: {rejected}\nReward credited: ৳{reward_total:.2f}", MAIN_KEYBOARD)
        users_states[uid] = "main"
        send(uid, f"Review complete. Approved {approved}, rejected {rejected}; credited ৳{reward_total:.2f}.", ADMIN_KEYBOARD)
    elif state == "admin_awaiting_db":
        doc = msg.get("document", {})
        if not doc or doc.get("file_name") != "database.json":
            send(uid, "Please upload a document named database.json.")
            return
        file_info = api("getFile", {"file_id": doc.get("file_id")}).get("result", {})
        file_path = file_info.get("file_path")
        if not file_path:
            send(uid, "Could not download that file.")
            return
        try:
            response = session.get(FILE_BASE + file_path, timeout=30)
            response.raise_for_status()
            new_db = json.loads(response.text)
            if not isinstance(new_db.get("users"), dict) or not isinstance(new_db.get("submissions"), list):
                raise ValueError("invalid database schema")
            backup = DB_PATH.with_suffix(".json.backup")
            if DB_PATH.exists():
                backup.write_bytes(DB_PATH.read_bytes())
            db = new_db
            save_db()
            users_states[uid] = "main"
            send(uid, "Database imported and reloaded. A local backup was kept if a database file existed.", ADMIN_KEYBOARD)
        except Exception:
            logging.exception("DB upload failed")
            send(uid, "Import failed: invalid JSON/schema or file download error. Existing database was not intentionally overwritten.")
    else:
        users_states[uid] = "main"
        send(uid, "Unknown admin input state. Returning to admin panel.", ADMIN_KEYBOARD)


def handle_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = int(msg.get("chat", {}).get("id", 0))
    callback_id = cb.get("id")
    if data == "check_sub":
        if check_force_sub(chat_id):
            answer_callback(callback_id, "Membership verified.")
            try:
                api("deleteMessage", {"chat_id": chat_id, "message_id": msg.get("message_id")})
            except Exception:
                pass
            main_menu(chat_id)
        else:
            answer_callback(callback_id, "You haven't joined yet!", True)
        return
    if data.startswith("admin:"):
        answer_callback(callback_id)
        handle_admin_callback(callback_id, chat_id, data)
        return
    answer_callback(callback_id, "Unknown action.", True)


def main():
    global ADMIN_ID, db, bot_username
    if not BOT_TOKEN or not ADMIN_ID_RAW:
        raise SystemExit("Set BOT_TOKEN and ADMIN_ID environment variables.")
    try:
        ADMIN_ID = int(ADMIN_ID_RAW)
    except ValueError:
        raise SystemExit("ADMIN_ID must be an integer Telegram user ID.")
    db = load_db()
    migrate_referral_commissions()
    me = api("getMe").get("result", {})
    if me.get("username"):
        bot_username = me["username"]
    logging.info("Started @%s; database: %s", bot_username, DB_PATH)
    offset = None
    while True:
        try:
            payload = {"timeout": 50, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                payload["offset"] = offset
            updates = api("getUpdates", payload, timeout=60).get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    if "message" in update:
                        handle_message(update["message"])
                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])
                except Exception:
                    logging.exception("Update handler crashed")
        except KeyboardInterrupt:
            logging.info("Stopping.")
            break
        except Exception:
            logging.exception("Polling error")
            time.sleep(2)


if __name__ == "__main__":
    main()
