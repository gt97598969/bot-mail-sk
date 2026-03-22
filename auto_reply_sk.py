from __future__ import annotations

import imaplib
import smtplib
import email
import os
import json
import time
import re
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from email.header import decode_header as _decode_header
from datetime import datetime
from dotenv import load_dotenv
from html.parser import HTMLParser

from dossier_manager import (
    get_or_create_dossier,
    update_dossier,
    save_dossier,
    check_duplicate,
    is_dossier_complete,
    get_dossier_summary,
    list_all_dossiers,
)
from extractor import extract_all, extract_proposal
from contract_generator import process_contract
from whatsapp_notify import send_whatsapp_admin

load_dotenv()

# ============================================================
# CONFIG
# ============================================================
IMAP_HOST   = os.getenv("IMAP_HOST")
IMAP_PORT   = int(os.getenv("IMAP_PORT", 993))
SMTP_HOST   = os.getenv("SMTP_HOST")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
EMAIL_USER  = os.getenv("EMAIL_USER")
EMAIL_PASS  = os.getenv("EMAIL_PASS")
SENDER_NAME = os.getenv("SENDER_NAME", "Andrea L.")
SENT_FOLDER = os.getenv("SENT_FOLDER", "Sent")

PROCESSED_FILE = "processed_ids.json"
KEYWORDS_FILE  = "keywords.json"

LOAN_REPLY_SUBJECTS = [
    "navrh uveru", "zmluva", "uver", "pozicka", "re:"
]

KEYWORDS_GROUP1_DEFAULT = [
    "Dobrý deň je tam nejaký poplatok",
    "platí sa aj nejaký poplatok",
    "kolko sa plati",
    "Sú uvas poplatky",
    "Pred prevodom peňazí na môj účet sa platí poplatok",
    "Sú nejaké poplatky vopred",
    "poplatky",
    "poplatok",
]
KEYWORDS_GROUP2_DEFAULT = [
    "Anoo mám záujem",
    "Áno vyhovujú mi tieto podmienky",
    "Áno súhlasím",
    "Dobrý deň, súhlasím",
    "súhlasím",
    "Ano vyhovujú",
    "mám záujem",
    "záujem",
    "Áno",
    "Ano",
    "Qno",
]


# ============================================================
# RÉPONSES AUTO EN SLOVAQUE
# ============================================================
def load_keywords() -> tuple:
    try:
        with open(KEYWORDS_FILE, "r") as f:
            kw = json.load(f)
        g1 = kw["GROUP1"]["keywords"]
        g2 = kw["GROUP2"]["keywords"]
        print(f"  [KEYWORDS] ✅ {len(g1)} GROUP1 / {len(g2)} GROUP2 chargés")
        return g1, g2
    except Exception as e:
        print(f"  [KEYWORDS] ⚠️  Fallback valeurs par défaut ({e})")
        return KEYWORDS_GROUP1_DEFAULT, KEYWORDS_GROUP2_DEFAULT


def get_replies() -> tuple:
    name = SENDER_NAME
    r1 = (
        "Dobrý deň,\n\n"
        "Nie, pred získaním úveru nemusíte platiť žiadne poplatky.\n\n"
        f"S pozdravom,\n{name}"
    )
    r2 = (
        "Dobrý deň,\n\n"
        "Prosím, zašlite nám ďalšie informácie, aby sme mohli dohodu okamžite finalizovať.\n\n"
        "Vaše celé meno:\n\n"
        "Vaša adresa:\n\n"
        "Vaše telefónne číslo:\n\n"
        "Váš mesačný príjem:\n\n"
        "IBAN:\n\n"
        "Priložte prosím kópiu platného preukazu totožnosti alebo pasu a čitateľnú faktúru "
        "za elektrinu, internet alebo vodu vystavenú v priebehu posledných 3 mesiacov.\n\n"
        f"S pozdravom,\n{name}"
    )
    return r1, r2


CONFIRM_SIGNATURE_REPLY = (
    "Dobrý deň,\n\n"
    "Potvrdzujeme prijatie vášho e-mailu.\n\n"
    "Zaregistrujte sa, prosím, na webovej stránke partnerskej banky, "
    "aby mohli byť finančné prostriedky prevedené na váš účet.\n\n"
    "https://groups.olakred.com/sk/register\n\n"
    "Prosím, vyplňte príslušné polia.\n\n"
    "Po vyplnení formulára nás prosím informujte.\n\n"
    f"S pozdravom,\n{SENDER_NAME}"
)


# ============================================================
# NORMALISATION
# ============================================================
def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ============================================================
# DÉTECTION MOT-CLÉ ANTI-FAUX-POSITIFS
# ============================================================
def keyword_matches(kw: str, text_normalized: str) -> bool:
    kw_norm = normalize(kw)
    if len(kw_norm.replace(" ", "")) <= 4:
        return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", text_normalized))
    return kw_norm in text_normalized


def detect_group(text: str, kw_g1: list, kw_g2: list) -> str | None:
    normalized = normalize(text)
    for kw in kw_g1:
        if keyword_matches(kw, normalized):
            print(f"  [MATCH GROUP1] mot-clé : '{kw}'")
            return "GROUP1"
    for kw in kw_g2:
        if keyword_matches(kw, normalized):
            print(f"  [MATCH GROUP2] mot-clé : '{kw}'")
            return "GROUP2"
    return None


# ============================================================
# DÉCODAGE EN-TÊTES EMAIL
# ============================================================
def decode_str(value: str) -> str:
    if not value:
        return ""
    parts = _decode_header(value)
    decoded = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded += part.decode(charset or "utf-8", errors="replace")
        else:
            decoded += part
    return decoded


# ============================================================
# EXTRACTION DU CORPS (brut + HTML)
# ============================================================
class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, d):
        self.result.append(d)

    def get_text(self):
        return " ".join(self.result)


def html_to_text(html: str) -> str:
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def get_body(msg) -> str:
    plain_text = ""
    html_text  = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype   = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                decoded = payload.decode(charset, errors="replace")
                if ctype == "text/plain":
                    plain_text += decoded
                elif ctype == "text/html":
                    html_text  += decoded
            except Exception:
                pass
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                decoded = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_text = decoded
                else:
                    plain_text = decoded
        except Exception:
            pass
    if plain_text.strip():
        return plain_text
    elif html_text.strip():
        return html_to_text(html_text)
    return ""


# ============================================================
# STRIP DES CITATIONS
# ============================================================
def strip_quoted_text(body: str) -> str:
    separators = [
        r"^>",
        r"^On .+ wrote:",
        r"^Le .+ a écrit",
        r"^-{5,}$",
        r"^_{5,}$",
        r"^From:\s",
        r"^De\s*:\s",
        r"^Sent\s*:\s",
        r"^Envoyé\s*:\s",
        r"^Dňa .+ napísal",
        r"^> Od:",
    ]
    lines = body.splitlines()
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if any(re.match(pat, stripped, re.IGNORECASE) for pat in separators):
            break
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


# ============================================================
# SAUVEGARDE SIGNATURES (images / PDF)
# ============================================================
def save_signature_attachments(dossier: dict, msg) -> list:
    dossier_id = dossier["id"]
    base_dir = os.path.join("clients", dossier_id, "signatures")
    os.makedirs(base_dir, exist_ok=True)

    saved_files = []

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue

        content_type = part.get_content_type()
        if not (content_type.startswith("image/") or content_type == "application/pdf"):
            continue

        filename = part.get_filename()
        if not filename:
            ext = ".pdf" if content_type == "application/pdf" else ".jpg"
            filename = f"signature_{datetime.now().strftime('%Y%m%d-%H%M%S')}{ext}"

        filename = decode_str(filename).replace("/", "_").replace("\\", "_")
        filepath = os.path.join(base_dir, filename)

        try:
            with open(filepath, "wb") as f:
                f.write(part.get_payload(decode=True))
            saved_files.append(filepath)
            print(f"  [SIGNATURE] 💾 Fichier sauvegardé → {filepath}")
        except Exception as e:
            print(f"  [SIGNATURE] ❌ Erreur sauvegarde '{filename}' : {e}")

    if saved_files:
        existing = dossier.get("signature_files") or []
        dossier["signature_files"] = existing + saved_files
        dossier["signature_recue_le"] = datetime.now().isoformat()

    return saved_files


def is_signature_email(msg, clean_body: str, full_body: str) -> bool:
    has_attachment = False
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        content_type = part.get_content_type()
        if content_type.startswith("image/") or content_type == "application/pdf":
            has_attachment = True
            break

    if not has_attachment:
        return False

    subject = decode_str(msg.get("Subject", "")).lower()
    in_reply_to = (msg.get("In-Reply-To") or "").lower()
    references  = (msg.get("References") or "").lower()

    if "zmluva o pôžičke" in subject or "zmluva" in subject:
        return True

    if in_reply_to or references:
        return True

    return False


# ============================================================
# ANTI-DOUBLON (processed_ids.json)
# ============================================================
def load_processed() -> set:
    if os.path.exists(PROCESSED_FILE):
        try:
            with open(PROCESSED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, ValueError):
            print("  [WARN] processed_ids.json corrompu → réinitialisé")
            return set()
    return set()


def save_processed(ids: set):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(ids), f, indent=2)


# ============================================================
# SAUVEGARDE DANS BOÎTE D'ENVOI
# ============================================================
def save_to_sent(imap, raw_message: bytes):
    try:
        imap.append(
            SENT_FOLDER,
            "\\Seen",
            imaplib.Time2Internaldate(time.time()),
            raw_message
        )
        print("  [SENT] ✅ Copie sauvegardée dans la boîte d'envoi.")
    except Exception as e:
        print(f"  [SENT] ⚠️  Impossible de sauvegarder dans Sent : {e}")


# ============================================================
# ENVOI RÉPONSE
# ============================================================
def send_reply(imap, original_msg, reply_body: str) -> bool:
    _, sender_email = parseaddr(original_msg.get("From", ""))
    subject_original = decode_str(original_msg.get("Subject", ""))
    reply_subject = subject_original if subject_original.lower().startswith("re:") \
        else f"RE: {subject_original}"

    msg = MIMEMultipart()
    msg["From"]        = formataddr((SENDER_NAME, EMAIL_USER))
    msg["To"]          = sender_email
    msg["Subject"]     = reply_subject
    msg["In-Reply-To"] = original_msg.get("Message-ID", "")
    msg["References"]  = original_msg.get("Message-ID", "")
    msg.attach(MIMEText(reply_body, "plain", "utf-8"))

    raw = msg.as_bytes()
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, sender_email, raw)
        server.quit()
        print(f"  [OK] ✅ Réponse envoyée à {sender_email}")
        save_to_sent(imap, raw)
        return True
    except Exception as e:
        print(f"  [ERREUR SMTP] ❌ {e}")
        return False


# ============================================================
# VÉRIFICATION CLIENT CONNU
# ============================================================
def is_known_client(sender_email: str) -> bool:
    if not os.path.exists("clients_index.json"):
        return False
    try:
        with open("clients_index.json") as f:
            index = json.load(f)
        return sender_email.lower().strip() in index.get("by_email", {})
    except Exception:
        return False


# ============================================================
# RECHERCHE PROPOSITION DANS SENT
# ============================================================
def find_proposal_in_sent(imap, client_email: str) -> dict:
    try:
        imap.select(f'"{SENT_FOLDER}"')
        status, messages = imap.search(None, f'TO "{client_email}"')
        if status != "OK" or not messages[0]:
            imap.select("INBOX")
            return {}

        mail_ids = messages[0].split()
        if not mail_ids:
            imap.select("INBOX")
            return {}

        for mid in reversed(mail_ids):
            status, data = imap.fetch(mid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            raw_email = data[0][1]
            msg_sent  = email.message_from_bytes(raw_email)
            body      = get_body(msg_sent)
            proposal  = extract_proposal(body)
            if proposal.get("montant"):
                print(f"  [SENT SCAN] 📨 Proposition trouvée : {proposal}")
                imap.select("INBOX")
                return proposal

        print(f"  [SENT SCAN] ⚠️  Aucune proposition trouvée pour {client_email}")
        imap.select("INBOX")
        return {}

    except Exception as e:
        print(f"  [SENT SCAN] ❌ Erreur : {e}")
        try:
            imap.select("INBOX")
        except Exception:
            pass
        return {}


# ============================================================
# TRAITEMENT CLIENT (connu OU auto-détecté)
# ============================================================
def handle_known_client_email(imap, msg, message_id: str,
                              sender_email: str, clean_body: str,
                              full_body: str,
                              mail_id, processed_ids: set):
    dossier = get_or_create_dossier(sender_email)

    # 1) On extrait ce que le client vient d'envoyer
    extracted = extract_all(clean_body, full_body)
    updated = update_dossier(dossier, extracted)

    if message_id not in dossier["emails_recus"]:
        dossier["emails_recus"].append(message_id)

    # 2) Doublons IBAN / téléphone
    dup_id = check_duplicate(
        iban=extracted.get("iban"),
        phone=extracted.get("telephone")
    )
    if dup_id and dup_id != dossier["id"]:
        print(f"  [⚠️ DOUBLON] IBAN ou téléphone déjà dans dossier {dup_id}")

    if updated:
        dossier["statut"] = "en_cours"

    # 3) 🔥 NOUVEAU : si montant/durée/mensualité manquent, on scanne Sent
    if not is_dossier_complete(dossier):
        proposal = find_proposal_in_sent(imap, sender_email)
        if proposal:
            print(f"  [AUTO-DOSSIER] 📊 Proposition trouvée dans Sent → merge.")
            updated2 = update_dossier(dossier, proposal)
            if updated2:
                print("  [AUTO-DOSSIER] 🔁 Dossier mis à jour avec la proposition.")

    # 4) Après merge avec la proposition, on re‑teste la complétude
    if is_dossier_complete(dossier):
        dossier["statut"] = "complet"
        save_dossier(dossier)
        print(f"  [✅ COMPLET] Dossier prêt pour contrat → {dossier['id']}")
        send_whatsapp_admin(dossier, "complet")
        process_contract(dossier)
    else:
        save_dossier(dossier)

    imap.store(mail_id, "+FLAGS", "\\Seen")
    processed_ids.add(message_id)
    print(f"  [DOSSIER] 💾 {get_dossier_summary(dossier)}")



# ============================================================
# MAIN
# ============================================================
def run():
    kw_g1, kw_g2 = load_keywords()
    REPLY_G1, REPLY_G2 = get_replies()

    print(f"\n{'='*58}")
    print(f"  Scan démarré : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*58}")

    processed_ids = load_processed()

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(EMAIL_USER, EMAIL_PASS)
        imap.select("INBOX")
        print(f"  Connecté à {IMAP_HOST} en tant que {EMAIL_USER}")
    except Exception as e:
        print(f"  [ERREUR IMAP] ❌ Connexion impossible : {e}")
        return

    status, messages = imap.search(None, "UNSEEN")
    if status != "OK" or not messages[0]:
        print("  Aucun nouveau message non lu.")
        imap.logout()
        return

    mail_ids = messages[0].split()
    print(f"  {len(mail_ids)} message(s) non lu(s) trouvé(s).\n")

    for mail_id in mail_ids:
        status, data = imap.fetch(mail_id, "(BODY.PEEK[])")
        if status != "OK":
            continue

        raw_email = data[0][1]
        msg       = email.message_from_bytes(raw_email)

        message_id           = msg.get("Message-ID", f"no-id-{mail_id.decode()}")
        sender_raw           = msg.get("From", "")
        _, sender_email_addr = parseaddr(sender_raw)
        sender_email_addr    = sender_email_addr.lower().strip()
        sender_display       = decode_str(sender_raw)
        subject              = decode_str(msg.get("Subject", "(sans objet)"))

        # --- NE JAMAIS TOUCHER AUX MAILS "Nouvelle Demande SK" ---
        subj_norm = subject.strip().lower()
        if subj_norm == "nouvelle demande sk":
            print("  [SKIP HARD] ✋ Sujet 'Nouvelle Demande SK' → ignoré par ce bot.")
            # on ne lit pas le corps, on ne modifie pas les flags, on passe au mail suivant
            continue

        print(f"  {'─'*45}")
        print(f"  De      : {sender_display}")
        print(f"  Sujet   : {subject}")
        print(f"  ID      : {message_id}")

        if message_id in processed_ids:
            print("  [SKIP] ⏭️  Déjà traité précédemment.")
            imap.store(mail_id, "+FLAGS", "\\Seen")
            continue

        full_body  = get_body(msg)
        clean_body = strip_quoted_text(full_body)
        print(f"  Corps   : {repr(clean_body[:120])}")

        group = detect_group(clean_body, kw_g1, kw_g2)

        # ── GROUP 1 : question frais ──────────────────────
        if group == "GROUP1":
            success = send_reply(imap, msg, REPLY_G1)
            if success:
                processed_ids.add(message_id)
                imap.store(mail_id, "+FLAGS", "\\Seen")
                print("  [GROUP1] 💬 Réponse frais envoyée.")

        # ── GROUP 2 : accord / intérêt ───────────────────
        elif group == "GROUP2":
            success = send_reply(imap, msg, REPLY_G2)
            if success:
                processed_ids.add(message_id)
                imap.store(mail_id, "+FLAGS", "\\Seen")

                dossier   = get_or_create_dossier(sender_email_addr)
                extracted = extract_all(clean_body, full_body)

                proposal_in_body = any(
                    extracted.get(f) for f in ["montant", "duree", "mensualite"]
                )
                if not proposal_in_body:
                    print("  [GROUP2] 🔍 Pas de proposition → scan Sent...")
                    proposal = find_proposal_in_sent(imap, sender_email_addr)
                    for key, val in proposal.items():
                        if extracted.get(key) is None:
                            extracted[key] = val

                update_dossier(dossier, extracted)

                if message_id not in dossier["emails_recus"]:
                    dossier["emails_recus"].append(message_id)
                if dossier.get("statut") in ["nouveau", None]:
                    dossier["statut"] = "formulaire_envoye"

                if is_dossier_complete(dossier):
                    dossier["statut"] = "complet"
                    save_dossier(dossier)
                    print(f"  [✅ COMPLET] Dossier prêt → {dossier['id']}")
                    send_whatsapp_admin(dossier, "complet")
                    process_contract(dossier)
                else:
                    save_dossier(dossier)

                print("  [GROUP2] 📋 Formulaire envoyé + dossier mis à jour.")
                print(f"  [DOSSIER] 💾 {get_dossier_summary(dossier)}")

        # ── PAS DE MOT-CLÉ ───────────────────────────────
        else:
            subject_norm   = normalize(subject)
            is_loan_reply  = any(kw in subject_norm for kw in LOAN_REPLY_SUBJECTS)
            extracted_peek = extract_all(clean_body, full_body)
            has_data       = any(
                extracted_peek.get(f)
                for f in ["iban", "telephone", "adresse", "nom"]
            )

            print(f"  [DEBUG] email détecté : '{sender_email_addr}'")

            # 1) Réponse avec données → auto-dossier
            if is_loan_reply and has_data:
                print("  [AUTO-DOSSIER] 📥 Réponse avec données → dossier créé/mis à jour.")
                handle_known_client_email(
                    imap, msg, message_id,
                    sender_email_addr, clean_body,
                    full_body, mail_id, processed_ids
                )

            # 2) Mail de signature (avec pièce jointe)
            elif is_signature_email(msg, clean_body, full_body):
                print("[SIGNATURE] ✍️ Mail de signature détecté (avec pièce jointe).")

                dossier = get_or_create_dossier(sender_email_addr)
                handle_signature_logic(
                    imap,
                    msg,
                    dossier,
                    clean_body,
                    full_body,
                    processed_ids,
                    message_id,
                    mail_id,
                )

            # 3) Vrai inconnu, rien de spécial
            else:
                print("  [HUMAIN] 👤 Client inconnu + aucun mot-clé → NON LU.")
                imap.store(mail_id, "-FLAGS", "\\Seen")


    save_processed(processed_ids)
    imap.logout()

    dossiers = list_all_dossiers()
    complets = sum(1 for d in dossiers if d.get("statut") == "complet")
    en_cours = sum(1 for d in dossiers if d.get("statut") in [
        "en_cours", "formulaire_envoye"
    ])
    print(f"\n  {'─'*45}")
    print(f"  ✅ Scan terminé — {len(dossiers)} dossier(s) | "
          f"{complets} complet(s) | {en_cours} en cours")
    print(f"  {'─'*45}\n")

def handle_signature_logic(imap, msg, dossier, clean_body, full_body,
                           processed_ids, message_id, mail_id):
    saved = save_signature_attachments(dossier, msg)
    if not saved:
        print("  [SIGNATURE] ⚠️ Aucune pièce jointe exploitable.")
        imap.store(mail_id, "-FLAGS", "\\Seen")
        return

    print(f"  [SIGNATURE] ✅ {len(saved)} fichier(s) sauvegardé(s).")

    statut_actuel = dossier.get("statut", "")

    # CAS 1 : contrat déjà envoyé -> contrat signé reçu -> lien OLAKRED
    if statut_actuel == "contrat_envoye":
        dossier["statut"] = "signe"
        save_dossier(dossier)
        print("  [SIGNATURE] ✅ Contrat signé reçu → envoi lien OLAKRED.")
        print(f"  [DOSSIER] 💾 {get_dossier_summary(dossier)}")
        send_whatsapp_admin(dossier, "signe")
        send_reply(imap, msg, CONFIRM_SIGNATURE_REPLY)

    # CAS 2 : contrat pas encore envoyé -> données + PJ -> générer contrat
    else:
        extracted = extract_all(clean_body, full_body)
        update_dossier(dossier, extracted)

        if is_dossier_complete(dossier):
            dossier["statut"] = "complet"
            save_dossier(dossier)
            print("  [CONTRAT] 📄 Dossier complet → génération du contrat...")
            send_whatsapp_admin(dossier, "complet")
            try:
                process_contract(dossier)
                dossier["statut"] = "contrat_envoye"
                save_dossier(dossier)
                print("  [CONTRAT] ✅ Contrat généré et envoyé.")
            except Exception as e:
                print(f"  [CONTRAT] ❌ Erreur : {e}")
        else:
            save_dossier(dossier)
            print("  [CONTRAT] ⏳ Données incomplètes → dossier mis à jour, en attente.")
            print(f"  [DOSSIER] 💾 {get_dossier_summary(dossier)}")

    processed_ids.add(message_id)
    imap.store(mail_id, "+FLAGS", "\\Seen")


if __name__ == "__main__":
    run()