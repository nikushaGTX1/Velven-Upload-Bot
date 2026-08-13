import asyncio
import io
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import qrcode
from telethon import Button, TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from config import API_HASH, API_ID, BOT_TOKEN, TARGET_CHAT, UPLOADS_DIR
from crypto_utils import decrypt_session
from database import delete_user, get_user, init_db, save_user
from listing_import import download_images, scrape_listing, supported_url
from translations import translate_listing_fields

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("velven")

FIELDS = [
    ("city", "📌 Enter the city:"),
    ("district", "🌇 Enter the district:"),
    ("size", "🧱 Enter apartment size:"),
    ("floor", "🏢 Enter floor, for example 5/8:"),
    ("building", "🏠 Enter building type, for example new:"),
    ("rooms", "🛋️ Enter number of rooms:"),
    ("bedrooms", "🛏️ Enter number of bedrooms:"),
    ("elevator", "🏗️ Enter number of elevators:"),
    ("price", "💸 Enter the price:"),
    ("pets", "🐶 Are pets allowed? Enter yes or no:"),
]


@dataclass
class Listing:
    photos: list[Path] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
    step: int = -1


states: dict[int, Listing] = {}
qr_tasks: dict[int, asyncio.Task] = {}
schedule_tasks: dict[int, asyncio.Task] = {}
photo_locks: dict[int, asyncio.Lock] = {}
bot = TelegramClient("velven_bot", API_ID, API_HASH)


def menu_buttons(connected: bool):
    return [[Button.inline("➕ New Listing", b"new")], [Button.inline("👤 Account", b"account")]] if connected else [[Button.inline("🔗 Connect Telegram", b"connect")]]


async def show_menu(event, edit=False):
    user = get_user(event.sender_id)
    if user:
        username = f" (@{user['telegram_username']})" if user["telegram_username"] else ""
        text = f"🏠 Velven Upload Bot\n\n✅ Connected as: {user['telegram_name']}{username}\n\nCreate a listing below, or send a public MyHome.ge or SS.ge listing link to import it automatically."
    else:
        text = "🏠 Velven Upload Bot\n\nConnect your Telegram account before creating a listing."
    method = event.edit if edit else event.respond
    await method(text, buttons=menu_buttons(bool(user)))


def cleanup(user_id: int, cancel_schedule: bool = True):
    task = schedule_tasks.pop(user_id, None) if cancel_schedule else None
    if task and task is not asyncio.current_task():
        task.cancel()
    state = states.pop(user_id, None)
    if state:
        shutil.rmtree(UPLOADS_DIR / str(user_id), ignore_errors=True)


def caption(values: dict[str, str]) -> str:
    price = values["price"].strip()
    if price.replace(".", "", 1).isdigit():
        price += " $"
    return "\n".join([
        f"📌 Город: {values['city']}", f"🌇 Район: {values['district']}",
        f"🧱 Кв : {values['size']}", f"🏢 Этаж: {values['floor']}",
        f"🏠 Здание: {values['building']}", f"🛋️ Комнаты: {values['rooms']}",
        f"🛏️ Спальни: {values['bedrooms']}", f"🏗️ Лифт: {values['elevator']}",
        f"💸 Цена: {price}", f"🐶 Животные: {values['pets']}",
    ])


def is_image_upload(event) -> bool:
    if event.photo:
        return True
    mime_type = (getattr(event.file, "mime_type", None) or "").lower()
    filename = (getattr(event.file, "name", None) or "").lower()
    return bool(event.document) and (
        mime_type.startswith("image/")
        or filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
    )


async def ask_field(event, state: Listing):
    _, prompt = FIELDS[state.step]
    await event.respond(f"Step {state.step + 1}/10\n\n{prompt}", buttons=[[Button.inline("❌ Cancel", b"cancel")]])


async def continue_form(event, state: Listing):
    while state.step < len(FIELDS) and state.values.get(FIELDS[state.step][0]):
        state.step += 1
    if state.step < len(FIELDS):
        await ask_field(event, state)
    else:
        await translate_listing_fields(state.values)
        await event.respond(f"👀 Preview\n\n{caption(state.values)}\n\nPublish this listing?", buttons=[[Button.inline("✅ Publish", b"publish"), Button.inline("❌ Cancel", b"cancel")]])


async def import_listing(event, url: str):
    uid = event.sender_id
    if not get_user(uid):
        await event.respond("Connect your Telegram account before importing a listing.")
        return
    if uid in schedule_tasks:
        await event.respond("Stop your active automatic listing before importing another one.")
        return
    cleanup(uid)
    progress = await event.respond("🔎 Importing the listing and its photos. This may take a moment...")
    try:
        values, image_urls = await asyncio.to_thread(scrape_listing, url)
        photos = await asyncio.to_thread(download_images, image_urls, UPLOADS_DIR / str(uid))
    except Exception:
        log.exception("Could not import listing for bot user %s from %s", uid, url)
        await progress.edit("❌ Could not read this listing. Make sure the link is public and still available.")
        return
    state = Listing(photos=photos, values={key: value for key, value in values.items() if value})
    states[uid] = state
    missing = [key for key, _ in FIELDS if not state.values.get(key)]
    if not state.photos:
        state.step = -1
        await progress.edit("The details were imported, but no listing photos could be downloaded. Send up to 10 photos, then press Done.", buttons=[[Button.inline("✅ Done", b"done"), Button.inline("❌ Cancel", b"cancel")]])
    elif missing:
        state.step = next(i for i, (key, _) in enumerate(FIELDS) if key in missing)
        await progress.edit(f"✅ Imported {len(state.photos)} photo(s) and available details. Please enter the missing information.")
        await ask_field(event, state)
    else:
        state.step = len(FIELDS)
        await translate_listing_fields(state.values)
        await progress.edit(f"👀 Imported Preview\n\n{caption(state.values)}\n\nPublish this listing?", buttons=[[Button.inline("✅ Publish", b"publish"), Button.inline("❌ Cancel", b"cancel")]])


async def connect_qr(event):
    uid = event.sender_id
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    qr_message = None
    try:
        await client.connect()
        qr = await client.qr_login()
        login_deadline = time.monotonic() + 5 * 60
        while True:
            image = qrcode.make(qr.url)
            data = io.BytesIO()
            image.save(data, format="PNG")
            data.seek(0)
            data.name = "telegram-login.png"
            if qr_message:
                try:
                    await qr_message.delete()
                except Exception:
                    log.warning("Could not remove expired QR for bot user %s", uid)
            qr_message = await event.respond(
                "Scan this QR now in Telegram: Settings → Devices → Link Desktop Device.\n\nIt refreshes automatically when it expires. Never send login codes or passwords here.",
                file=data,
            )
            try:
                await qr.wait()
                break
            except asyncio.TimeoutError:
                if time.monotonic() >= login_deadline:
                    await event.respond("❌ QR login timed out after 5 minutes. Press Connect Telegram to try again.")
                    return
                await qr.recreate()
            except SessionPasswordNeededError:
                await event.respond("❌ This account requires a 2FA password. For security, passwords cannot be entered in this bot chat. Disable 2FA temporarily or connect using a trusted local setup, then try again.")
                return
        me = await client.get_me()
        name = " ".join(filter(None, [me.first_name, me.last_name])) or "Telegram user"
        save_user(uid, me.id, me.username, name, client.session.save())
        await event.respond("✅ Telegram account connected successfully.")
        await show_menu(event)
    except Exception:
        log.exception("QR login failed for bot user %s", uid)
        await event.respond("❌ Could not connect Telegram. Please try again.")
    finally:
        await client.disconnect()
        qr_tasks.pop(uid, None)


def countdown_text(seconds: int) -> str:
    minutes, seconds = divmod(max(0, seconds), 60)
    return f"⏳ Next post in {minutes:02d}:{seconds:02d}.\n\nThis listing will be posted every 18 minutes."


async def publish_once(uid: int) -> tuple[bool, str]:
    state, user = states.get(uid), get_user(uid)
    if not state or not user:
        return False, "Listing or account connection not found."
    client = TelegramClient(StringSession(decrypt_session(user["encrypted_session"])), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            delete_user(uid)
            return False, "Your Telegram authorization has expired. Please reconnect Telegram."
        await client.send_file(TARGET_CHAT, [str(p) for p in state.photos], caption=caption(state.values))
        return True, ""
    except Exception:
        log.exception("Publishing failed for bot user %s", uid)
        return False, f"Could not publish the listing. Make sure your Telegram account has permission to post in {TARGET_CHAT}."
    finally:
        await client.disconnect()


async def repeat_listing(event):
    uid = event.sender_id
    status = None
    try:
        while True:
            ok, error = await publish_once(uid)
            if not ok:
                await event.respond(f"❌ {error}")
                break
            next_send = time.monotonic() + 18 * 60
            if status is None:
                status = await event.respond(
                    f"✅ Listing published to {TARGET_CHAT}.\n\n{countdown_text(18 * 60)}",
                    buttons=[[Button.inline("⏹ Stop automatic posting", b"stop_schedule")]],
                )
            while True:
                remaining = max(0, round(next_send - time.monotonic()))
                if remaining <= 0:
                    break
                try:
                    await status.edit(
                        f"✅ Automatic posting is active for {TARGET_CHAT}.\n\n{countdown_text(remaining)}",
                        buttons=[[Button.inline("⏹ Stop automatic posting", b"stop_schedule")]],
                    )
                except Exception:
                    log.exception("Could not update countdown for bot user %s", uid)
                await asyncio.sleep(min(60, remaining))
    except asyncio.CancelledError:
        raise
    finally:
        schedule_tasks.pop(uid, None)
        cleanup(uid, cancel_schedule=False)


@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start(event):
    if event.sender_id not in schedule_tasks:
        cleanup(event.sender_id)
    await show_menu(event)


@bot.on(events.CallbackQuery)
async def callbacks(event):
    uid, action = event.sender_id, event.data
    await event.answer()
    if action == b"connect":
        if uid not in qr_tasks:
            qr_tasks[uid] = asyncio.create_task(connect_qr(event))
        else:
            await event.respond("A Telegram connection is already waiting for a QR scan.")
    elif action == b"account":
        user = get_user(uid)
        if not user:
            await show_menu(event)
            return
        username = f"@{user['telegram_username']}" if user["telegram_username"] else "Not set"
        await event.respond(f"👤 Connected Telegram Account\n\nName: {user['telegram_name']}\nUsername: {username}\nTelegram ID: {user['telegram_account_id']}", buttons=[[Button.inline("🔌 Disconnect", b"disconnect")], [Button.inline("⬅️ Back", b"back")]])
    elif action == b"disconnect":
        delete_user(uid)
        cleanup(uid)
        await event.respond("✅ Telegram account disconnected.")
        await show_menu(event)
    elif action == b"back":
        await show_menu(event)
    elif action == b"new":
        if not get_user(uid):
            await event.respond("Connect your Telegram account first.")
            return
        if uid in schedule_tasks:
            await event.respond("An automatic listing is already active. Stop it before creating another listing.", buttons=[[Button.inline("⏹ Stop automatic posting", b"stop_schedule")]])
            return
        cleanup(uid)
        states[uid] = Listing()
        await event.respond("📸 Send the apartment photos.\n\nYou can send up to 10 photos.\nWhen you're finished, press Done.", buttons=[[Button.inline("✅ Done", b"done"), Button.inline("❌ Cancel", b"cancel")]])
    elif action == b"done":
        state = states.get(uid)
        if not state or not state.photos:
            await event.respond("Please send at least one photo before pressing Done.")
            return
        state.step = 0
        await continue_form(event, state)
    elif action == b"cancel":
        cleanup(uid)
        await event.respond("❌ Listing cancelled.")
        await show_menu(event)
    elif action == b"publish":
        if uid in schedule_tasks:
            await event.answer("Automatic posting is already active.", alert=True)
            return
        schedule_tasks[uid] = asyncio.create_task(repeat_listing(event))
    elif action == b"stop_schedule":
        task = schedule_tasks.pop(uid, None)
        if task:
            task.cancel()
            cleanup(uid, cancel_schedule=False)
            await event.respond("⏹ Automatic posting stopped. The listing will not be posted again.")
            await show_menu(event)
        else:
            await event.respond("No automatic listing is currently active.")


@bot.on(events.NewMessage)
async def messages(event):
    if event.raw_text.startswith("/start"):
        return
    url = supported_url(event.raw_text)
    if url:
        await import_listing(event, url)
        return
    uid, state = event.sender_id, states.get(event.sender_id)
    if not state:
        return
    if state.step == -1:
        if not is_image_upload(event):
            await event.respond("Please send a photo or an image file (JPG, PNG, or WebP), or use Done or Cancel.")
            return
        lock = photo_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            # Album items arrive concurrently, so enforce the limit inside
            # the per-user lock and recheck that this listing is still active.
            if states.get(uid) is not state or state.step != -1:
                return
            if len(state.photos) >= 10:
                await event.respond("You already added the maximum of 10 photos.")
                return
            folder = UPLOADS_DIR / str(uid)
            folder.mkdir(parents=True, exist_ok=True)
            suffix = Path(getattr(event.file, "name", "") or "").suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".jpg"
            path = folder / f"{uuid.uuid4().hex}{suffix}"
            await event.download_media(file=str(path))
            state.photos.append(path)
            await event.respond(f"📸 Photo added ({len(state.photos)}/10)")
        return
    if not event.raw_text:
        await event.respond("Please enter a text value.")
        return
    key, _ = FIELDS[state.step]
    state.values[key] = event.raw_text.strip()
    state.step += 1
    await continue_form(event, state)


async def main():
    init_db()
    UPLOADS_DIR.mkdir(exist_ok=True)
    await bot.start(bot_token=BOT_TOKEN)
    log.info("Velven Upload Bot started")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
