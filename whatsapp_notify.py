from __future__ import annotations

import os
import requests
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

WHATSAPP_TOKEN      = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID   = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ADMIN_NUM  = os.getenv("WHATSAPP_ADMIN_NUMBER")

WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"


def _send_whatsapp_text(to_number: str, text: str) -> bool:
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and to_number):
        print("  [WA] ❌ Config WhatsApp incomplète (TOKEN / PHONE_ID / NUMBER).")
        return False

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": text
        },
    }

    # Debug complet
    print("  [WA-DEBUG] URL       :", WHATSAPP_API_URL)
    print("  [WA-DEBUG] TO        :", to_number)
    print("  [WA-DEBUG] TOKEN deb :", (WHATSAPP_TOKEN or "")[:15])
    print("  [WA-DEBUG] PAYLOAD   :", payload)

    try:
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=10)
        print("  [WA-DEBUG] STATUS    :", resp.status_code, resp.text)
        resp.raise_for_status()
        print(f"  [WA] ✅ Notification envoyée à {to_number}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"  [WA] ❌ Erreur envoi WhatsApp : {e}")
        try:
            print(f"  [WA] Réponse brute : {resp.text}")
        except Exception:
            pass
        return False


def send_whatsapp_admin(dossier: dict, event: str) -> bool:
    """
    Envoie une notif WhatsApp à l'admin pour un événement sur un dossier.
    event ∈ {"complet", "contrat_envoye", "signe"}
    """
    if not WHATSAPP_ADMIN_NUM:
        print("  [WA] ⚠️ Aucun WHATSAPP_ADMIN_NUMBER dans .env")
        return False

    dossier_id = dossier.get("id", "?")
    now_str    = datetime.now().strftime("%d/%m/%Y %H:%M")

    if event == "complet":
        title = "📂 COMPLET"
    elif event == "contrat_envoye":
        title = "📄 ENVOYÉ"
    elif event == "signe":
        title = "✍️ SIGNÉ"
    else:
        title = f"ℹ️ {event}"

    body_lines = [
        title,
        f"ID   : {dossier_id}",
        f"Date : {now_str}",
    ]

    text = "\n".join(body_lines)
    return _send_whatsapp_text(WHATSAPP_ADMIN_NUM, text)
