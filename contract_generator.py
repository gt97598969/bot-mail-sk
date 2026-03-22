from __future__ import annotations

import os
import requests
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr
from dotenv import load_dotenv

from dossier_manager import save_dossier
from whatsapp_notify import send_whatsapp_admin

load_dotenv()

CRAFTMYPDF_API_KEY     = os.getenv("CRAFTMYPDF_API_KEY")
CRAFTMYPDF_TEMPLATE_ID = os.getenv("CRAFTMYPDF_TEMPLATE_ID")
CRAFTMYPDF_API_URL     = "https://api.craftmypdf.com/v1/create"

SMTP_HOST   = os.getenv("SMTP_HOST")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
EMAIL_USER  = os.getenv("EMAIL_USER")
EMAIL_PASS  = os.getenv("EMAIL_PASS")
SENDER_NAME = os.getenv("SENDER_NAME", "Andrea L.")

CONTRACTS_DIR = "contracts"
os.makedirs(CONTRACTS_DIR, exist_ok=True)


# ============================================================
# FORMATAGE
# ============================================================
def fmt_amount(value) -> str:
    """2000.0 → '2 000,00'  (sans EUR)"""
    try:
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(value) if value else "—"


def fmt_duree(value) -> str:
    """48 → '48' (sans mesiacov)"""
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value) if value else "—"


def fmt_date() -> str:
    """Date du jour dynamique."""
    return datetime.now().strftime("%d/%m/%Y")


# ============================================================
# PAYLOAD CRAFTMYPDF
# ============================================================
def build_payload(dossier: dict) -> dict:
    nom_complet = f"{dossier.get('prenom') or ''} {dossier.get('nom') or ''}".strip()

    return {
        "data": {
            "nom_client":     nom_complet,
            "adresse_client": dossier.get("adresse") or "—",
            "description":    dossier.get("telephone") or "—",  # téléphone
            "montant":        fmt_amount(dossier.get("montant")),
            "telephone":      dossier.get("iban") or "—",        # IBAN
            "montant_total":  fmt_amount(dossier.get("total_mensualites")),
            "numero_facture": fmt_duree(dossier.get("duree")),
            "email_client":   fmt_amount(dossier.get("mensualite")),
            "date":           fmt_date(),
        },
        "template_id": CRAFTMYPDF_TEMPLATE_ID,
        "export_type":  "json",
        "expiration":   60,
    }


# ============================================================
# GÉNÉRATION PDF
# ============================================================
def generate_pdf(dossier: dict) -> str | None:
    payload = build_payload(dossier)
    headers = {
        "X-API-KEY":    CRAFTMYPDF_API_KEY,
        "Content-Type": "application/json",
    }

    print(f"  [PDF] 🔄 Génération contrat pour {dossier['id']}...")

    try:
        response = requests.post(
            CRAFTMYPDF_API_URL,
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.Timeout:
        print("  [PDF] ❌ Timeout CraftMyPDF.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  [PDF] ❌ Erreur API : {e}")
        return None

    pdf_url = result.get("file") or result.get("pdf_url") or result.get("url")
    if not pdf_url:
        print(f"  [PDF] ❌ Pas d'URL dans la réponse : {result}")
        return None

    print(f"  [PDF] ✅ URL générée : {pdf_url[:60]}...")

    pdf_path = f"{CONTRACTS_DIR}/{dossier['id']}.pdf"
    try:
        pdf_response = requests.get(pdf_url, timeout=30)
        pdf_response.raise_for_status()
        with open(pdf_path, "wb") as f:
            f.write(pdf_response.content)
        print(f"  [PDF] 💾 PDF sauvegardé → {pdf_path}")
        return pdf_path
    except Exception as e:
        print(f"  [PDF] ❌ Erreur téléchargement PDF : {e}")
        return None


# ============================================================
# EMAIL AVEC PDF EN PIÈCE JOINTE
# ============================================================
def send_contract_email(dossier: dict, pdf_path: str) -> bool:
    recipient_email = dossier.get("email")
    if not recipient_email:
        print("  [EMAIL] ❌ Pas d'email client dans le dossier.")
        return False

    nom_complet = f"{dossier.get('prenom') or ''} {dossier.get('nom') or ''}".strip() \
                  or "Client"
    prenom = dossier.get("prenom") or nom_complet
    subject = f"Zmluva o pôžičke — {dossier['id']}"

    body = (
        f"Dobrý deň {prenom},\n\n"
        f"V prílohe nájdete vašu zmluvu o pôžičke č. {dossier['id']}.\n\n"
        f"Prosíme, prečítajte si zmluvu a podpíšte ju.\n"
        f"Podpísanú zmluvu zašlite späť na túto e-mailovú adresu.\n\n"
        f"Ak nemáte tlačiareň, môžete postupovať takto:\n"
        f"  1. Vezmite čistý list papiera\n"
        f"  2. Napíšte svoje meno a priezvisko\n"
        f"  3. Napíšte dnešný dátum\n"
        f"  4. Podpíšte list\n"
        f"  5. Odfotte alebo naskenujte a zašlite nám späť na túto adresu\n\n"
        f"S pozdravom,\n{SENDER_NAME}"
    )

    msg = MIMEMultipart()
    msg["From"]    = formataddr((SENDER_NAME, EMAIL_USER))
    msg["To"]      = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = f"Zmluva_{dossier['id']}.pdf"
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        msg.attach(part)
    except Exception as e:
        print(f"  [EMAIL] ❌ Impossible de joindre le PDF : {e}")
        return False

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, recipient_email, msg.as_bytes())
        server.quit()
        print(f"  [EMAIL] ✅ Contrat envoyé à {recipient_email}")
        return True
    except Exception as e:
        print(f"  [EMAIL] ❌ Erreur SMTP : {e}")
        return False


# ============================================================
# POINT D'ENTRÉE
# ============================================================
def process_contract(dossier: dict) -> bool:
    dossier_id  = dossier.get("id", "?")
    nom_complet = f"{dossier.get('prenom') or ''} {dossier.get('nom') or ''}".strip()

    print(f"\n  {'─'*45}")
    print(f"  [CONTRAT] 📄 Traitement → {dossier_id} | {nom_complet}")

    pdf_path = generate_pdf(dossier)
    if not pdf_path:
        dossier["statut"] = "erreur_pdf"
        save_dossier(dossier)
        return False

    sent = send_contract_email(dossier, pdf_path)
    if not sent:
        dossier["statut"] = "erreur_envoi"
        save_dossier(dossier)
        return False

    dossier["statut"]            = "contrat_envoye"
    dossier["contrat_pdf"]       = pdf_path
    dossier["contrat_envoye_le"] = datetime.now().isoformat()
    save_dossier(dossier)

    send_whatsapp_admin(dossier, "contrat_envoye")

    print(f"  [CONTRAT] ✅ {dossier_id} | {nom_complet} | contrat envoyé")
    return True
