r"""
aufteilen – teilt eine von pdf2md erzeugte Heft-.md in Aufgaben, Lösungen und Lerntext.

Aufruf:
    python aufteilen.py                      -> alle Hefte im output-Ordner
    python aufteilen.py "output\Skripte"     -> nur dieser Ordner (rekursiv)
    python aufteilen.py pfad\Skript01.md     -> nur dieses Heft

Ergebnis (neben der Volltext-.md, die unverändert bleibt):
    <Heft> - Aufgaben.md   Übungen im Text, Aufgaben zur Selbstüberprüfung, Übungsfälle, Einsendeaufgabe
    <Heft> - Lösungen.md   Lösungs-/Bearbeitungshinweise aus dem Anhang
    <Heft> - Lerntext.md   Kapiteltext inkl. Beispiele, Definitionen, Kapitel-Zusammenfassungen, Glossar
Verworfen werden Vorspann (Titelseiten), Inhalts-, Literatur-, Abbildungs-, Tabellen-, Abkürzungs-
und Sachwortverzeichnis. Jede Zeile des Volltexts landet in genau einer Kategorie.
"""

import re
import sys
from pathlib import Path

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
TEILE = {"aufgaben": "Aufgaben", "loesungen": "Lösungen", "lerntext": "Lerntext"}
VERWORFEN = "verworfen"

SEITE = re.compile(r"^<!-- Seite (\d+) -->\s*$")
UEBERSCHRIFT = re.compile(r"^#{1,6}\s")
# „#### **1.2.2 Arten von Bedürfnissen**“ – die Nummer muss im Fettdruck stehen,
# sonst wären Zeilen wie „##### 12 500 Stück pro Monat“ Kapitel
KAPITEL = re.compile(r"^#{1,6}\s+(?:\S+\s+){0,2}?\*\*(\d+(?:\.\d+)*)\.?\s+[A-ZÄÖÜ]")
# Anhang: „### **B. Lösungen der Aufgaben …**“, auch mit Heftkürzel davor („ABC 1 E. Abbildungs…“)
ANHANG = re.compile(r"(?:^|\s)([A-H])\.\s+([A-ZÄÖÜ].*)$")
FETT_START = re.compile(r"^\*\*[A-ZÄÖÜ]")
INLINE_AUFGABE = re.compile(r"^(übung\s*\d|aufgaben?\s*(\d|:))", re.I)
BLOCK_ENDE = re.compile(r"^(beispiel|hinweis|definition|merke|übung|aufgabe)", re.I)


def klartext(zeile: str) -> str:
    """Überschrift/fette Zeile ohne Markdown-Zeichen."""
    t = re.sub(r"^#{1,6}\s*", "", zeile)
    t = re.sub(r"</?u>|\*\*|__|(?<!\w)_|_(?!\w)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def gehoert_zur_uebung(zeile: str, block: dict) -> bool:
    """Gehört dieser Absatz noch zur Übung im Fließtext? Sonst geht dort der Lehrtext weiter.
    Eine Übung ist meist nur die Frage – plus ggf. Lückenlinien, Tabelle/Schema zum Ausfüllen,
    Teilaufgaben a), b) oder eine kurze Nachfrage."""
    vorher = block["letzter"]
    angekuendigt = vorher.endswith(":") or bool(re.search(r"folgend|schema|vorlage|unten|tabelle", vorher, re.I))
    if block["n"] == 0:
        return True                                          # die Aufgabenstellung selbst
    if re.search(r"_{5,}", zeile):
        return True                                          # Lückenlinien zum Ausfüllen
    if zeile.startswith("|"):
        return vorher.startswith("|") or angekuendigt        # Tabelle zum Ausfüllen
    if zeile.startswith("!["):                               # Schema/Vorlage zum Ausfüllen
        return vorher.endswith(":") or bool(re.search(r"schema|vorlage|unten", vorher, re.I))
    if zeile.startswith("<!-- Bildtext") or re.match(r"(\*\*)?Abb\.", zeile):
        return vorher.startswith(("![", "<!--"))             # Bildtext/Beschriftung zum Bild
    if re.match(r"(- )?([a-z]|\d{1,2})\)\s", zeile):
        return True                                          # Teilaufgaben a), b) / 1), 2)
    if zeile.startswith("- ") or re.match(r"\d+\.\s", zeile):
        return block["liste"] or vorher.endswith(":")        # Auswahl-/Aufzählungsliste
    if vorher.endswith(":"):
        return True                                          # „… wie folgt zusammen:“
    if (re.match(r"[A-ZÄÖÜ]\w+n Sie\b", zeile) and len(zeile) < 160
            and (vorher.startswith("|") or "___" in vorher or block["liste"])):
        return True                                          # Arbeitsauftrag nach Tabelle/Liste („Ermitteln Sie …“)
    return zeile.endswith("?") and len(zeile) < 160          # kurze Nachfrage


def anhang_kategorie(titel: str) -> str:
    t = titel.lower()
    if "lösung" in t or "bearbeitungshinweis" in t:
        return "loesungen"
    if "einsendeaufgabe" in t or "übung" in t or "aufgabe" in t or "fälle" in t:
        return "aufgaben"
    if any(w in t for w in ("verzeichnis", "literatur", "quellen", "abkürzungen")):
        return VERWORFEN
    return "lerntext"   # Glossar, Gesetzesauszüge, Formulare …


def front_matter(zeilen):
    """Liefert (Daten aus dem YAML-Kopf, Index der ersten Inhaltszeile)."""
    daten, i = {}, 0
    if zeilen and zeilen[0].strip() == "---":
        for i in range(1, len(zeilen)):
            if zeilen[i].strip() == "---":
                break
            if ":" in zeilen[i]:
                k, v = zeilen[i].split(":", 1)
                daten[k.strip()] = v.strip().strip('"')
        i += 1
    # Konvertierungshinweise von pdf2md gehören nur in den Volltext
    while i < len(zeilen) and (not zeilen[i].strip() or zeilen[i].startswith(">")):
        i += 1
    return daten, i


def klassifizieren(zeilen, start):
    """Ordnet jede Zeile ab `start` einer Kategorie zu. Rückgabe: Liste (kategorie, zeile, kontext)."""
    koepfe = [(i, klartext(z)) for i, z in enumerate(zeilen) if i >= start and UEBERSCHRIFT.match(z)]

    # Reines Aufgaben- oder Lösungsheft? (steht im Titel auf den ersten Seiten)
    ganzes_heft = None
    for i, t in koepfe[:8]:
        if re.search(r"aufgabenheft", t, re.I):
            ganzes_heft = "aufgaben"
        elif re.search(r"lösungsheft", t, re.I):
            ganzes_heft = "loesungen"

    # Inhaltsverzeichnis und Anhangsbeginn suchen
    toc = next((i for i, t in koepfe if re.fullmatch(r"(inhaltsverzeichnis|inhaltsübersicht|inhalt)", t, re.I)), None)
    toc_ende = None
    if toc is not None:
        nach_toc = [i for i, _ in koepfe if i > toc]
        toc_ende = next((i for i in nach_toc if KAPITEL.match(zeilen[i]) or re.match(
            r"(einleitung|einführung|vorwort|vorbemerkung)", klartext(zeilen[i]), re.I)),
            nach_toc[0] if nach_toc else None)
    anhang_start = next((i for i, t in koepfe if (toc_ende is None or i > toc_ende)
                         and (m := ANHANG.search(t)) and m.group(1) == "A"
                         and anhang_kategorie(m.group(2)) != "lerntext"), None)

    ergebnis = []
    kategorie = VERWORFEN if toc is not None else (ganzes_heft or "lerntext")   # Vorspann/Titelseiten
    block = None            # laufende Übung im Fließtext
    kapitel = None          # Hauptkapitel als Kontext für Aufgaben/Lösungen
    letzter_buchstabe = "@"  # Anhangsbuchstaben müssen aufsteigen (A, B, D …)

    for i in range(start, len(zeilen)):
        z = zeilen[i]
        ist_kopf = bool(UEBERSCHRIFT.match(z))
        text = klartext(z) if ist_kopf or FETT_START.match(z) else ""
        im_anhang = anhang_start is not None and i >= anhang_start

        if z.strip() == "---":                      # Trennlinie vor „Markierungen & Kommentare“
            ergebnis.append((None, z, kapitel))
            continue

        # Inline-Übung: endet bei Überschrift, neuem Block oder sobald wieder Lehrtext kommt
        if block:
            if ist_kopf or (text and BLOCK_ENDE.match(text)):
                block = None
            elif z.strip() and not SEITE.match(z):
                if gehoert_zur_uebung(z.strip(), block):
                    block["n"] += 1
                    block["liste"] |= bool(re.match(r"(- |\d+\.\s)", z.strip()))
                    block["letzter"] = z.strip()
                else:
                    block = None

        if ist_kopf:
            m_anhang = ANHANG.search(text) if im_anhang else None
            if text.lower() == "markierungen & kommentare":
                kategorie, kapitel = "lerntext", None
            elif ganzes_heft:
                if i == toc:
                    kategorie = VERWORFEN
                elif i == toc_ende:
                    kategorie = ganzes_heft
                if (m := KAPITEL.match(z)) and "." not in m.group(1):
                    kapitel = text
            elif i == toc:
                kategorie = VERWORFEN
            elif i == toc_ende:
                kategorie = "lerntext"
                if (m := KAPITEL.match(z)) and "." not in m.group(1):
                    kapitel = text
            elif m_anhang and m_anhang.group(1) > letzter_buchstabe and (
                    anhang_kategorie(m_anhang.group(2)) != "lerntext"
                    or ord(m_anhang.group(1)) == ord(letzter_buchstabe) + 1):
                letzter_buchstabe = m_anhang.group(1)
                kategorie, kapitel = anhang_kategorie(m_anhang.group(2)), None
            elif not im_anhang:
                if re.search(r"aufgaben? zur selbstüberprüfung", text, re.I):
                    kategorie = "aufgaben"
                elif re.fullmatch(r"zusammenfassung", text, re.I) or re.match(
                        r"(einleitung|einführung|vorwort|vorbemerkung)", text, re.I):
                    kategorie = "lerntext"
                elif m := KAPITEL.match(z):
                    kategorie = "lerntext"
                    if "." not in m.group(1):
                        kapitel = text

        # Neue Inline-Übung (nur im normalen Lerntext, nicht in Lösungen/Anhang)
        if text and kategorie == "lerntext" and not ganzes_heft and INLINE_AUFGABE.match(text):
            # Steht die Frage schon in der Zeile („Übung 2.3: Warum steigt der Preis?“)? Sonst folgt sie.
            rest = re.sub(r"^(übung|aufgaben?)\s*[\d.]*\s*:?\s*", "", text, flags=re.I)
            frage_in_zeile = len(rest) >= 10 and rest.endswith(("?", ".", ":"))
            block = {"n": int(frage_in_zeile), "letzter": rest if frage_in_zeile else text, "liste": False}
            ergebnis.append(("aufgaben", z, kapitel))
            continue

        ergebnis.append(("aufgaben" if block else kategorie, z, kapitel))
    return ergebnis


def aufteilen(md: Path) -> dict:
    """Teilt eine Volltext-.md auf. Rückgabe: Anzahl Inhaltszeilen je Kategorie."""
    zeilen = md.read_text(encoding="utf-8").splitlines()
    kopf, start = front_matter(zeilen)
    heft = md.stem
    titel = kopf.get("titel") or heft

    ausgaben = {k: [] for k in TEILE}
    seite_in = {k: None for k in TEILE}       # zuletzt geschriebene Seite je Datei
    kontext_in = {k: None for k in TEILE}     # zuletzt geschriebenes Kapitel je Datei
    zaehler = {k: 0 for k in (*TEILE, VERWORFEN)}
    seite = None

    for kat, z, kapitel in klassifizieren(zeilen, start):
        if m := SEITE.match(z):
            seite = m.group(1)
            continue
        if kat is None:
            continue
        if not z.strip():
            if kat in ausgaben and ausgaben[kat] and ausgaben[kat][-1].strip():
                ausgaben[kat].append("")
            continue
        zaehler[kat] += 1
        if kat == VERWORFEN:
            continue
        aus = ausgaben[kat]
        if kat != "lerntext" and kapitel and kontext_in[kat] != kapitel:
            aus += ["", f"## {kapitel}", ""]          # Kapitel als Orientierung für Aufgaben/Lösungen
            kontext_in[kat] = kapitel
        if seite and seite_in[kat] != seite:
            aus += ["", f"<!-- Seite {seite} -->", ""]
            seite_in[kat] = seite
        aus.append(z)

    for kat, name in TEILE.items():
        ziel = md.with_name(f"{heft} - {name}.md")
        if zaehler[kat] == 0:
            ziel.unlink(missing_ok=True)              # veraltete Datei aus früherem Lauf entfernen
            continue
        inhalt = ["---", f'quelle: "{kopf.get("quelle", "")}"', f'titel: "{titel}"',
                  f'teil: "{name}"', f'volltext: "{md.name}"', "---", "", f"# {heft} – {name}", ""]
        text = "\n".join(inhalt + ausgaben[kat]).strip() + "\n"
        ziel.write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")
    return zaehler


def statistik(zaehler: dict) -> str:
    gesamt = sum(zaehler.values()) or 1
    namen = {**TEILE, VERWORFEN: "verworfen"}
    return " · ".join(f"{namen[k]} {zaehler[k] * 100 / gesamt:.0f} %" for k in namen if zaehler[k])


def volltexte(pfad: Path):
    """Alle Volltext-.md unterhalb von `pfad` (erkennbar daran, dass sie wie ihr Ordner heißen)."""
    if pfad.is_file():
        return [pfad]
    return sorted(p for p in pfad.rglob("*.md") if p.stem == p.parent.name)


def main():
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(errors="replace")
        except Exception:
            pass
    pfade = [Path(a) for a in sys.argv[1:]] or [OUTPUT_ROOT]
    dateien = [d for p in pfade for d in volltexte(p)]
    if not dateien:
        print("Keine Hefte gefunden.")
        return
    breite = max(len(d.stem) for d in dateien)
    for md in dateien:
        try:
            z = aufteilen(md)
            warnung = ""
            if z["aufgaben"] and not z["loesungen"] and z["lerntext"]:
                warnung = "  ⚠ Aufgaben, aber keine Lösungen gefunden"
            elif z["lerntext"] < 0.3 * sum(z.values()) and (z["aufgaben"] or z["loesungen"]) and z["lerntext"]:
                warnung = "  ⚠ auffällig wenig Lerntext"
            print(f"{md.stem:<{breite}}  {statistik(z)}{warnung}")
        except Exception as e:
            print(f"{md.stem:<{breite}}  FEHLER: {e}")


if __name__ == "__main__":
    main()
