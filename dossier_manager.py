from __future__ import annotations

import json
import os
import random
from datetime import datetime

DOSSIERS_DIR = "clients"
INDEX_FILE   = "clients_index.json"
os.makedirs(DOSSIERS_DIR, exist_ok=True)


# ============================================================
# INDEX
# ============================================================

def _load_index() -> dict:
    """
    Charge l'index. Si manquant ou incomplet (après suppression pour tests),
    reconstruit la structure avec toutes les clés nécessaires.
    """
    base = {
        "last_id": 0,
        "by_email": {},
        "by_iban": {},
        "by_phone": {},
        "used_rf": [],
    }
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return base
            base.update({k: v for k, v in data.items() if k in base})
            return base
        except (json.JSONDecodeError, ValueError):
            print("  [INDEX] ⚠️ clients_index.json corrompu → réinitialisé")
            return base
    return base


def _save_index(index: dict):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _next_id(index: dict) -> str:
    """
    Format : KRD-YYYY-RFXXX
    XXX = nombre aléatoire entre 459 et 9999, jamais réutilisé.
    """
    used = set(index.get("used_rf", []))
    while True:
        number = random.randint(459, 9999)
        if number not in used:
            used.add(number)
            index["used_rf"] = list(used)
            year = datetime.now().year
            return f"KRD-{year}-RF{number}"


# ============================================================
# CRÉER OU RETROUVER UN DOSSIER
# ============================================================
def get_or_create_dossier(email: str) -> dict:
    """
    Retourne le dossier existant OU crée un nouveau.
    Supporte le cas où l'index a été supprimé pour tests.
    """
    index = _load_index()
    email = (email or "").lower().strip()

    # Assurer que les clés existent même si ancien index
    index.setdefault("by_email", {})
    index.setdefault("by_iban", {})
    index.setdefault("by_phone", {})
    index.setdefault("used_rf", [])

    # Dossier existant
    if email in index["by_email"]:
        dossier_id = index["by_email"][email]
        path = f"{DOSSIERS_DIR}/{dossier_id}.json"

        if not os.path.exists(path):
            print(f"  [DOSSIER] ⚠️  Fichier manquant pour {dossier_id} → recréation.")
            dossier = _empty_dossier(dossier_id, email)
            _write_dossier(dossier)
            print(f"  [DOSSIER] 🔄 Dossier recréé → {dossier_id}")
            return dossier

        with open(path) as f:
            dossier = json.load(f)
        dossier["_is_new"] = False
        print(f"  [DOSSIER] 📂 Client connu → {dossier_id}")
        return dossier

    # Nouveau dossier
    dossier_id = _next_id(index)
    dossier = _empty_dossier(dossier_id, email)
    index["by_email"][email] = dossier_id
    _save_index(index)
    _write_dossier(dossier)
    print(f"  [DOSSIER] 🆕 Nouveau dossier créé → {dossier_id}")
    return dossier


def _empty_dossier(dossier_id: str, email: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "id":                dossier_id,
        "email":             email,
        "nom":               None,
        "prenom":            None,
        "telephone":         None,
        "iban":              None,
        "adresse":           None,
        "revenu":            None,
        "montant":           None,
        "mensualite":        None,
        "total_mensualites": None,
        "duree":             None,
        "statut":            "nouveau",
        "documents":         [],
        "emails_recus":      [],
        "created_at":        now,
        "updated_at":        now,
        "_is_new":           True,
    }


# ============================================================
# METTRE À JOUR UN DOSSIER
# ============================================================
def update_dossier(dossier: dict, extracted: dict) -> bool:
    updated = False
    for field, value in extracted.items():
        if field.startswith("_"):
            continue
        if value is None:
            continue
        if dossier.get(field) is None:
            dossier[field] = value
            print(f"  [DOSSIER] ✏️  {field} ← {value}")
            updated = True
    return updated


# ============================================================
# SAUVEGARDE
# ============================================================
def save_dossier(dossier: dict):
    dossier["updated_at"] = datetime.now().isoformat()
    clean = {k: v for k, v in dossier.items() if not k.startswith("_")}
    _write_dossier(clean)

    index = _load_index()
    index.setdefault("by_email", {})
    index.setdefault("by_iban", {})
    index.setdefault("by_phone", {})
    index.setdefault("used_rf", [])

    if dossier.get("email"):
        index["by_email"][dossier["email"].lower().strip()] = dossier["id"]
    if dossier.get("iban"):
        index["by_iban"][dossier["iban"].replace(" ", "")] = dossier["id"]
    if dossier.get("telephone"):
        index["by_phone"][dossier["telephone"]] = dossier["id"]
    _save_index(index)


def _write_dossier(dossier: dict):
    path = f"{DOSSIERS_DIR}/{dossier['id']}.json"
    os.makedirs(DOSSIERS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(dossier, f, indent=2, ensure_ascii=False)


# ============================================================
# DÉTECTION DOUBLON
# ============================================================
def check_duplicate(iban: str = None, phone: str = None) -> str | None:
    index = _load_index()
    iban_map  = index.get("by_iban", {}) or {}
    phone_map = index.get("by_phone", {}) or {}
    if iban:
        iban_clean = iban.replace(" ", "")
        if iban_clean in iban_map:
            return iban_map[iban_clean]
    if phone:
        if phone in phone_map:
            return phone_map[phone]
    return None


# ============================================================
# COMPLÉTUDE
# ============================================================
def is_dossier_complete(dossier: dict) -> bool:
    required = ["nom", "montant", "duree", "mensualite"]
    return all(dossier.get(f) for f in required)


# ============================================================
# RÉSUMÉ
# ============================================================
def get_dossier_summary(dossier: dict) -> str:
    nom_complet = f"{dossier.get('prenom') or ''} {dossier.get('nom') or ''}".strip()
    if not nom_complet:
        nom_complet = "Inconnu"
    statut = dossier.get("statut", "?")
    champs = ["nom", "telephone", "iban", "adresse", "revenu", "montant"]
    remplis = sum(1 for c in champs if dossier.get(c))
    pct = remplis * 100 // len(champs)
    return f"{dossier['id']} | {nom_complet} | {statut} | {pct}% complet"


# ============================================================
# LISTE / GET
# ============================================================
def list_all_dossiers() -> list:
    dossiers = []
    if not os.path.exists(DOSSIERS_DIR):
        return dossiers
    for filename in os.listdir(DOSSIERS_DIR):
        if filename.endswith(".json"):
            try:
                with open(f"{DOSSIERS_DIR}/{filename}") as f:
                    dossiers.append(json.load(f))
            except json.JSONDecodeError:
                pass
    dossiers.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return dossiers


def get_dossier_by_id(dossier_id: str) -> dict | None:
    path = f"{DOSSIERS_DIR}/{dossier_id}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None