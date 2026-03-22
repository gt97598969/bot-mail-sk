from __future__ import annotations

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _send_telegram_text(text: str) -> bool:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("  [TG] ❌ Config Telegram incomplète (TOKEN / CHAT_ID).")
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    print("  [TG-DEBUG] URL     :", TELEGRAM_API_URL)
    print("  [TG-DEBUG] CHAT_ID :", TELEGRAM_CHAT_ID)
    print("  [TG-DEBUG] PAYLOAD :", payload)

    try:
        resp = requests.post(TELEGRAM_API_URL, json=payload, timeout=10)
        print("  [TG-DEBUG] STATUS  :", resp.status_code, resp.text)
        resp.raise_for_status()
        print("  [TG] ✅ Notification envoyée sur Telegram.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"  [TG] ❌ Erreur envoi Telegram : {e}")
        try:
            print("  [TG] Réponse brute :", resp.text)
        except Exception:
            pass
        return False


def send_telegram_admin(dossier: dict, event: str) -> bool:
    """
    Envoie une notif Telegram à l'admin pour un événement sur un dossier.
    event ∈ {"complet", "contrat_envoye", "signe"}
    """
    dossier_id  = dossier.get("id", "?")
    nom         = dossier.get("nom") or ""
    prenom      = dossier.get("prenom") or ""
    nom_client  = (prenom + " " + nom).strip() or "Inconnu"
    statut      = dossier.get("statut", "?")
    montant     = dossier.get("montant")
    duree       = dossier.get("duree")
    mensualite  = dossier.get("mensualite")

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if event == "complet":
        title = "📂 Dossier COMPLET"
    elif event == "contrat_envoye":
        title = "📄 Contrat ENVOYÉ"
    elif event == "signe":
        title = "✍️ Contrat SIGNÉ"
    else:
        title = f"ℹ️ Événement: {event}"

    lines = [
        f"{title}",
        f"Date : {now_str}",
        f"ID   : {dossier_id}",
        f"Client : {nom_client}",
        f"Statut : {statut}",
    ]
    if montant:
        lines.append(f"Montant : {montant}")
    if duree:
        lines.append(f"Durée   : {duree} mois")
    if mensualite:
        lines.append(f"Mensualité : {mensualite}")

    text = "\n".join(lines)

    return _send_telegram_text(text)
