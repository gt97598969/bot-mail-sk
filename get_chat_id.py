from dotenv import load_dotenv
import os, requests

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # on va le mettre dans .env après

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
resp = requests.get(url, timeout=10)
print(resp.status_code)
print(resp.text)
