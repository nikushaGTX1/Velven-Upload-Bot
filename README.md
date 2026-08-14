# Velven Upload Bot

A Telethon bot that lets users securely connect their own Telegram account by QR, compose a Russian apartment listing, and publish it to `@tbilisi_arendaa` from that account.

## Windows setup

1. Install Python 3.11.
2. Create a virtual environment: `py -3.11 -m venv venv`
3. Activate it: `.\venv\Scripts\Activate.ps1`
4. Install packages: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env`.
6. Get `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org).
7. Get `BOT_TOKEN` from BotFather.
8. Generate a Fernet encryption key:

   ```powershell
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Put the result in `SESSION_ENCRYPTION_KEY` in `.env`.

9. Run: `python main.py`
10. Open `@velven_upload_bot` and send `/start`.
11. Connect Telegram by scanning the QR from Telegram Settings → Devices → Link Desktop Device.
12. Create a listing, then use **Add another listing** to build an unlimited queue.
13. Start automatic posting. The bot sends each listing in order with an 18-minute cooldown, then repeats from the first listing.

The connected user account must have permission to post in the target channel. Login codes and 2FA passwords are never accepted in bot chat. Stored `StringSession` values are encrypted in SQLite.

## Railway persistence

Railway's normal deployment filesystem is temporary. To keep connected Telegram accounts across restarts and deployments:

1. Add a Railway Volume to the bot service.
2. Set its mount path to `/data`.
3. Add the Railway variable `DATA_DIR=/data`.
4. Keep `SESSION_ENCRYPTION_KEY` unchanged. Changing it makes previously stored sessions unreadable.

The encrypted SQLite database will then be stored at `/data/velven.db`. Run only one service replica when using SQLite.
"# Velven-Upload-Bot" 
