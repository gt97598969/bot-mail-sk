from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ─────────────────────────────────────────────
# TÉLÉPHONE → 421XXXXXXXXX
# ─────────────────────────────────────────────

def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "421" + digits[1:]
    if len(digits) >= 11:
        return digits
    return None


def extract_phone(text: str) -> str | None:
    # Nettoyer formats malformés : 421+944... → 421944...
    text_clean = re.sub(r'(\d{3})\+(\d)', r'\1\2', text)
    patterns = [
        r'(?:\+421|00421)[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}',
        r'(?:\+420|00420)[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}',
        r'\b421\d{9}\b',
        r'\b0\d{3}[\s\-]?\d{3}[\s\-]?\d{3}\b',
    ]
    for p in patterns:
        m = re.search(p, text_clean)
        if m:
            result = normalize_phone(m.group())
            if result:
                return result
    return None


# ─────────────────────────────────────────────
# IBAN
# ─────────────────────────────────────────────

def extract_iban(text: str) -> str | None:
    m = re.search(
        r'\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){4,6}(?:[ ]?[A-Z0-9]{0,4})?)\b',
        text, re.IGNORECASE
    )
    if m:
        candidate = m.group(1).upper().strip()
        if len(candidate.replace(" ", "")) >= 15:
            return re.sub(r'\s+', ' ', candidate)
    return None


# ─────────────────────────────────────────────
# MONTANT EN EUROS
# ─────────────────────────────────────────────

def extract_amount(text: str) -> float | None:
    m = re.search(
        r'(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)',
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw)
            if 100 <= val <= 100000:
                return val
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────
# REVENU MENSUEL
# ─────────────────────────────────────────────

def extract_income(text: str) -> float | None:
    # Avec mot-clé explicite
    m = re.search(
        r'(?:pr[íi]jem|plat|mzda|zar[áa]bam|mesačn[ýy]\s+pr[íi]jem)[^\d]*'
        r'(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)?',
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            pass

    # Fallback : ligne = montant seul (ex: "1500€" ou "1500 EUR")
    for line in text.splitlines():
        line = line.strip()
        m2 = re.fullmatch(
            r'(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)',
            line, re.IGNORECASE
        )
        if m2:
            raw = m2.group(1).replace(" ", "").replace(",", ".")
            try:
                val = float(raw)
                if 300 <= val <= 20000:
                    return val
            except ValueError:
                pass
    return None


# ─────────────────────────────────────────────
# NOM COMPLET → (prénom, nom)
# ─────────────────────────────────────────────

def extract_full_name(text: str) -> tuple:
    patterns = [
        # Formulaire rempli : "Vaše celé meno: Peter Novák"
        r'(?:Va[sš]e\s+cel[eé]\s+meno|meno\s+a\s+priezvisko|meno)[:\s]+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)\s+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)',
        # Salutation : "Dobrý deň, Peter Novák"
        r'Dobr[ýy]\s+de[ňn][,\s]+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)\s+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)',
        # "Volám sa" / "Som"
        r'(?:Vol[áa]m\s+sa|Som)[,\s]+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)\s+'
        r'([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+)',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1), m.group(2)

    # Fallback : première ligne = 2 ou 3 mots capitalisés
    first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
    words = first_line.split()
    if 2 <= len(words) <= 3:
        if all(re.match(
            r'^[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záčďéíľĺňóôŕšťúýž\-]+$', w
        ) for w in words):
            return words[0], words[-1]

    return None, None


# ─────────────────────────────────────────────
# ADRESSE
# ─────────────────────────────────────────────

def extract_address(text: str) -> str | None:
    # Formulaire explicite
    m = re.search(
        r'(?:adresa|bydlisko|ulica)[:\s]+([^\n]{5,100})',
        text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # Fallback : ligne avec rue + numéro
    for line in text.splitlines():
        line = line.strip()
        if re.search(r'[A-Za-záčďéíľĺňóôŕšťúýžÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ]{4,}\s+\d+', line):
            if not any(skip in line.lower() for skip in [
                "iban", "tel", "príjem", "plat", "@", "eur", "€"
            ]):
                return line
    return None


# ─────────────────────────────────────────────
# DURÉE (mois)
# ─────────────────────────────────────────────

def extract_duration(text: str) -> int | None:
    m = re.search(r'(\d+)\s*mesiac(?:ov|e|och)?', text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 360:
            return val
    return None


# ─────────────────────────────────────────────
# DONNÉES DE LA PROPOSITION (dans la citation ou Sent)
# ─────────────────────────────────────────────

def extract_proposal(text: str) -> dict:
    """
    Extrait montant, durée, mensualité et total depuis
    le texte de la proposition envoyée par l'opérateur.

    Format attendu (récap envoyé au client) :
      Suma úveru           2 000,00 EUR
      Doba trvania úveru   36 mesiacov
      Odhadovaná mesačná splátka   58,16 EUR
      Celková suma na zaplatenie   2 093,85 EUR
    """
    result = {}

    m = re.search(
        r'Suma\s+[úu]veru[\s:]+(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)',
        text, re.IGNORECASE
    )
    if m:
        try:
            result["montant"] = float(m.group(1).replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    m = re.search(
        r'Doba\s+trvania\s+[úu]veru[\s:]+(\d+)\s*mesiac',
        text, re.IGNORECASE
    )
    if m:
        result["duree"] = int(m.group(1))

    m = re.search(
        r'mesačn[aá]\s+spl[aá]tka[\s:]+(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)',
        text, re.IGNORECASE
    )
    if m:
        try:
            result["mensualite"] = float(m.group(1).replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    m = re.search(
        r'Celkov[aá]\s+suma\s+na\s+zaplatenie[\s:]+(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:EUR|€)',
        text, re.IGNORECASE
    )
    if m:
        try:
            result["total_mensualites"] = float(
                m.group(1).replace(" ", "").replace(",", ".")
            )
        except ValueError:
            pass

    return result


# ─────────────────────────────────────────────
# POINT D'ENTRÉE UNIQUE
# ─────────────────────────────────────────────

def extract_all(text: str, full_text: str = None) -> dict:
    """
    text      = corps après strip_quoted_text (données client)
    full_text = corps complet avant strip (contient la citation avec la proposition)
    """
    prenom, nom = extract_full_name(text)
    data = {
        "nom":       nom,
        "prenom":    prenom,
        "telephone": extract_phone(text),
        "iban":      extract_iban(text),
        "revenu":    extract_income(text),
        "montant":   extract_amount(text),
        "adresse":   extract_address(text),
        "duree":     extract_duration(text),
    }

    # Enrichir depuis la citation si full_text fourni
    if full_text:
        proposal = extract_proposal(full_text)
        for key, val in proposal.items():
            if data.get(key) is None and val is not None:
                data[key] = val

    return data
