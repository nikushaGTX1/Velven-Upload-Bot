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
12. Create a listing.
13. Publish it to `@tbilisi_arendaa`.

The connected user account must have permission to post in the target channel. Login codes and 2FA passwords are never accepted in bot chat. Stored `StringSession` values are encrypted in SQLite.
"# Velven-Upload-Bot" 
