r"""
Prüft die von /zusammenfassen erzeugten Lernskripte („<X> - Zusammenfassung.md“) gegen ihren Lerntext.

Aufruf:
    python tools\zusammenfassung_pruefen.py                      -> alle Hefte unter output
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>"  -> nur dieser Ordner (rekursiv)
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>\…\<Heft>"  -> nur dieses Heft

Fehler (✘): YAML-Kopf, alle Hauptkapitel („## N“), Unterkapitel („### N.M … (S. a–b)“) mit gültigen
Seitenangaben und Unter-Unterkapitel („#### N.M.K“), alle nummerierten Definitionen, keine Übungen/
Aufgaben/Lösungen/Literatur/Quellen in Überschriften (außer echten Kapiteltiteln), jede Zahl (ab 2 Ziffern)
steht im Lerntext, LaTeX-Blöcke in Ordnung, jeder Bildlink zeigt auf eine Datei.
Nur Warnungen: tiefere Kapitel (N.M.K.L), Länge außerhalb 20–45 % (Ziel 25–35 %), Fettbegriffe, die im Lerntext fehlen,
Abschnitte, deren Inhaltswörter nicht auf ihren Seiten stehen, fehlender Selbstcheck.
Danach folgt die Liste der Hefte, die noch keine Zusammenfassung haben. Exit-Code 1 bei Fehlern.
"""
import pathlib
import re
import sys

for strom in (sys.stdout, sys.stderr):      # ✔/✘ dürfen bei umgeleiteter Ausgabe (cp1252) nicht abstürzen
    try:
        strom.reconfigure(errors="replace")
    except Exception:
        pass

PROJEKT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT))
import aufteilen                             # noqa: E402

VERBOTEN = re.compile(r"übung|aufgabe|lösung|literatur|quellen", re.I)
BILD = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")
SEITENMARKE = re.compile(r"<!-- Seite \d+ -->")
# auch Kurzformen „S. 53, 84“ und „S. 53–55, S. 84“
SEITENANGABE = re.compile(r"\(S\.[^)]*\)|\bS\.\s*\d+(?:\s*[–-]\s*\d+)?(?:\s*,\s*(?:S\.\s*)?\d+(?:\s*[–-]\s*\d+)?)*")
SEITENBEREICH = re.compile(r"\(S\.\s*(\d+)(?:\s*[–-]\s*(\d+))?\)")
ZAHL = re.compile(r"\b\d{1,3}(?:[ .\u00a0\u202f]\d{3})+\b|\d+")      # mit Tausendertrennern oder ohne
# Beschriftungen aus dem Format des Lernskripts – keine Fachbegriffe
FORMAT_FETT = {"formel", "rechenbeispiel aus dem heft", "beispiel aus dem heft", "merke", "dabei ist", "hinweis"}


def titel(zeile: str) -> str:
    """Überschrift als „1.2.3 Titel“: ohne Markdown, ohne Punkt nach der Nummer, ohne „(S. …)“ am Ende."""
    t = re.sub(r"\s*\(S\.[^)]*\)$", "", aufteilen.klartext(zeile))
    return re.sub(r"^(\d+(?:\.\d+)*)\.?\s+", r"\1 ", t)


def latex_fehler(md: str) -> int:
    """Fehler in den $$-Formelblöcken: ungerade Anzahl „$$“, unausgeglichene { } in einem Block,
    \\frac/\\text außerhalb eines Blocks."""
    fehler, block, im_block = 0, [], False
    for z in md.splitlines():
        if z.strip() == "$$":
            if im_block:
                ohne_escape = re.sub(r"\\[{}]", "", "\n".join(block))
                fehler += ohne_escape.count("{") != ohne_escape.count("}")
                block = []
            im_block = not im_block
        elif im_block:
            block.append(z)
        else:
            fehler += len(re.findall(r"\\(?:frac|text)\b", z))
    return fehler + im_block                    # offener Block am Ende = ungerade Anzahl „$$“


def zahlen(text: str):
    """Zahlen ab 2 Ziffern, Tausendertrenner vereinheitlicht („1 890“ = „1.890“ = „1890“).
    Rückgabe: ({vereinheitlicht: wie geschrieben}, alle einzelnen Ziffernfolgen ab 2 Ziffern)."""
    ganz = {}
    for roh in ZAHL.findall(text):
        if len(zahl := re.sub(r"\D", "", roh)) >= 2:
            ganz.setdefault(zahl, roh)
    return ganz, {t for t in re.findall(r"\d+", text) if len(t) >= 2}


def pruefen(lerntext: pathlib.Path, zusammenfassung: pathlib.Path):
    """Rückgabe: (Fehlerliste, Warnungsliste, Länge in %, Kennzahlen)."""
    lt = lerntext.read_text(encoding="utf-8")
    zf = zusammenfassung.read_text(encoding="utf-8")
    zf_zeilen = zf.splitlines()
    fehler, warnungen = [], []
    seiten = {int(n) for n in re.findall(r"<!-- Seite (\d+) -->", lt)}

    # a) YAML-Kopf
    kopf, start = aufteilen.front_matter(zf_zeilen)
    if kopf.get("teil") != "Zusammenfassung":
        fehler.append('YAML-Kopf mit teil: "Zusammenfassung" fehlt')
    inhalt = [(nr, z) for nr, z in enumerate(zf_zeilen, 1) if nr > start]   # ohne YAML-Kopf

    # b) Hauptkapitel, b2) Unterkapitel, b3) Unter-Unterkapitel; tiefere Ebenen nur Warnung
    ebenen = {0: [], 1: [], 2: [], 3: []}         # Anzahl Punkte (3 = drei und mehr) -> Nummern
    kapitel_titel = set()                         # alle Tiefen, als „1.2.3 Titel“
    for z in lt.splitlines():
        if m := aufteilen.KAPITEL.match(z):
            nr = m.group(1)
            kapitel_titel.add(titel(z[m.start(1):]))
            ebene = ebenen[min(nr.count("."), 3)]
            if nr not in ebene:
                ebene.append(nr)
    for punkte, rauten, name in ((0, "##", "Hauptkapitel"), (1, "###", "Unterkapitel"),
                                 (2, "####", "Unter-Unterkapitel"), (3, "#{4,6}", "tiefere Kapitel")):
        fehlend = [k for k in ebenen[punkte]
                   if not any(re.match(rf"{rauten}\s+{re.escape(k)}(\s|$)", z) for z in zf_zeilen)]
        if fehlend:
            meldung = f"{name} fehlen als „{rauten.replace('{4,6}', '####')} <Nr> …“: {', '.join(fehlend)}"
            (warnungen if punkte == 3 else fehler).append(meldung)
    kapitel_ohne_nr = {t.split(" ", 1)[-1].lower() for t in kapitel_titel}

    # c) nummerierte Definitionen
    definitionen = dict.fromkeys(re.findall(r"Definition\s+(\d+(?:\.\d+)*)", lt))
    fehlend = [d for d in definitionen if not re.search(rf"Definition\s+{re.escape(d)}(?!\.?\d)", zf)]
    if fehlend:
        fehler.append(f"Definitionen fehlen: {', '.join(fehlend)}")

    # d) Seitenangaben: jede „### “-Überschrift hat „(S. a)“ oder „(S. a–b)“; alle genannten Seiten existieren
    ohne = [f"{z[4:].strip()} (Zeile {nr})" for nr, z in inhalt if z.startswith("### ") and not SEITENBEREICH.search(z)]
    if ohne:
        fehler.append(f"„### “-Überschriften ohne „(S. a–b)“: {'; '.join(ohne)}")
    falsch = sorted({int(n) for a, b in SEITENBEREICH.findall(zf) for n in (a, b) if n and int(n) not in seiten})
    if falsch:
        fehler.append(f"Seitenangaben ohne passende Seite im Lerntext: {', '.join(map(str, falsch))}")

    # e) verbotene Überschriften – erlaubt nur, wenn Nummer und Titel genau einem Kapitel des Lerntexts entsprechen
    verboten = [z.strip() for z in zf_zeilen if aufteilen.UEBERSCHRIFT.match(z) and VERBOTEN.search(z)
                and titel(z) not in kapitel_titel]
    if verboten:
        fehler.append(f"verbotene Überschriften: {'; '.join(verboten)}")

    # f) Länge
    prozent = len(zf) * 100 / max(len(lt), 1)
    if not 20 <= prozent <= 45:
        warnungen.append(f"Länge {prozent:.1f} % (Ziel 25–35 %, Warnung außerhalb 20–45 %)")

    # g) Zahlen: jede Ziffernfolge ab 2 Ziffern muss im Lerntext stehen
    lt_zahlen, lt_teile = zahlen(BILD.sub(" ", SEITENMARKE.sub(" ", lt)))
    zahl_fehler = []
    for nr, z in inhalt:
        z = z.replace("\\,", " ").replace("{,}", ",")                    # LaTeX-Zahlen wie im Heft schreiben
        z = re.sub(r"Definition\s+\d+(?:\.\d+)*", " ", SEITENANGABE.sub(" ", BILD.sub(" ", z)))
        z = re.sub(r"^#{2,6}\s+\d+(?:\.\d+)*", " ", z)                  # Kapitelnummern aller Ebenen
        z = re.sub(r"\|\s*\d+(?:\s*[–-]\s*\d+)?\s*\|\s*$", "|", z)      # Seiten-Spalte der Begriffstabelle
        ganz, _ = zahlen(z)
        for zahl, roh in ganz.items():
            # „3 100“ kann auch „3“ und „100“ sein – dann genügen die einzelnen Ziffernfolgen
            teile = [t for t in re.findall(r"\d+", roh) if len(t) >= 2]
            if zahl not in lt_zahlen and not all(t in lt_teile for t in teile):
                zahl_fehler.append(f"{roh} (Zeile {nr})")
    if zahl_fehler:
        fehler.append(f"Zahlen nicht im Lerntext: {', '.join(zahl_fehler)}")

    # h) Fettbegriffe (nur Warnung)
    lt_flach = re.sub(r"\s+", " ", re.sub(r"\*\*|(?<!\w)_|_(?!\w)", "", lt)).lower()
    fett_fehlt = []
    for nr, z in inhalt:
        for fett in re.findall(r"\*\*(.+?)\*\*", z):
            fett = re.sub(r"\s+", " ", fett).strip().rstrip(":").strip()
            # Struktur-Beschriftungen: „Definition 1.2 – …“, „… (1.1)“, Format-Wörter, Kapiteltitel
            if (re.match(r"Definition\s+\d", fett) or re.search(r"\(\d+(?:\.\d+)*\)$", fett)
                    or fett.lower() in FORMAT_FETT or titel(fett) in kapitel_titel or fett.lower() in kapitel_ohne_nr):
                continue
            for begriff in fett.split(" / "):                          # Begriffspaar „A / B“
                if (begriff := begriff.strip()) and begriff.lower() not in lt_flach:
                    fett_fehlt.append(f"{begriff} (Zeile {nr})")
    if fett_fehlt:
        warnungen.append(f"Fettbegriffe nicht im Lerntext ({len(fett_fehlt)}): {'; '.join(fett_fehlt[:10])}"
                         + (" …" if len(fett_fehlt) > 10 else ""))

    # i) Plausibilität pro „### “-Abschnitt (nur Warnung): ≥ 30 % der Inhaltswörter stehen auf den Seiten a−1 … b+1
    seitentext = {int(n): t.lower() for n, t in
                  re.findall(r"<!-- Seite (\d+) -->\n(.*?)(?=<!-- Seite \d+ -->|\Z)", lt, re.S)}
    abschnitte, aktuell = [], None
    for nr, z in inhalt:
        if z.startswith("### ") and (m := SEITENBEREICH.search(z)):
            aktuell = [nr, int(m.group(1)), int(m.group(2) or m.group(1)), []]
            abschnitte.append(aktuell)
        elif z.startswith(("## ", "### ", "#### Das Wichtigste", "#### Selbstcheck")):
            aktuell = None
        elif aktuell:
            aktuell[3].append(z)
    unplausibel = []
    for nr, a, b, zeilen in abschnitte:
        text = re.sub(r"\\[a-zA-Z]+", " ", SEITENANGABE.sub(" ", BILD.sub(" ", "\n".join(zeilen)))).lower()
        woerter = set(re.findall(r"[a-zäöüß]{6,}", text))
        if len(woerter) < 3:
            continue
        umfeld = " ".join(seitentext.get(s, "") for s in range(a - 1, b + 2))
        if sum(w in umfeld for w in woerter) < 0.3 * len(woerter):
            unplausibel.append(nr)
    unplausibel_prozent = len(unplausibel) * 100 / max(len(abschnitte), 1)
    if unplausibel:
        warnungen.append(f"Abschnitte unplausibel: {len(unplausibel)} / {len(abschnitte)} "
                         f"({unplausibel_prozent:.1f} %), z. B. Zeilen {', '.join(map(str, unplausibel[:5]))}")

    # j) LaTeX
    if n := latex_fehler(zf):
        fehler.append(f"LaTeX-Fehler ($$ ungerade, {{ }} offen, \\frac/\\text außerhalb): {n}")

    # k) Bildlinks
    links = BILD.findall(zf)
    kaputt = [l for l in links if not (zusammenfassung.parent / l).is_file()]
    if kaputt:
        fehler.append(f"Bildlinks ohne Datei: {', '.join(kaputt)}")

    # l) Selbstcheck je Hauptkapitel (nur Warnung)
    ohne_check = []
    for teil in re.split(r"^(?=## )", zf, flags=re.M)[1:]:
        if m := re.match(r"##\s+(\d+)\s", teil):
            check = re.search(r"^#### Selbstcheck\s*$(.*?)(?=^#{1,4} |\Z)", teil, re.M | re.S)
            if not check or check.group(1).count("<details>") < 2:
                ohne_check.append(m.group(1))
    if ohne_check:
        warnungen.append(f"Kapitel ohne „#### Selbstcheck“ mit mindestens 2 <details>: {', '.join(ohne_check)}")

    werte = {"zahlen": len(zahl_fehler), "fett": len(fett_fehlt), "unplausibel": len(unplausibel),
             "abschnitte": len(abschnitte), "unplausibel_prozent": unplausibel_prozent,
             "formeln": sum(1 for z in zf_zeilen if z.strip() == "$$") // 2, "grafiken": len(links),
             "fragen": zf.count("<details>")}
    return fehler, warnungen, prozent, werte


def main():
    pfad = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else aufteilen.OUTPUT_ROOT
    lerntexte = sorted(pfad.rglob("* - Lerntext.md")) if pfad.is_dir() else []
    if not lerntexte:
        print(f"Keine Lerntexte unter „{pfad}“ gefunden.")
        return 0
    ok, offen = True, []
    for lt in lerntexte:
        heft = lt.name[:-len(" - Lerntext.md")]
        zf = lt.with_name(f"{heft} - Zusammenfassung.md")
        if not zf.is_file():
            offen.append(heft)
            continue
        fehler, warnungen, prozent, w = pruefen(lt, zf)
        ok &= not fehler
        print(f"{'✔' if not fehler else '✘'} {heft}: Länge {prozent:.1f} % · Zahlen {'✔' if not w['zahlen'] else '✘'}"
              f" · Fettbegriff-Warnungen {w['fett']} · Abschnitte unplausibel {w['unplausibel']} / {w['abschnitte']}"
              f" ({w['unplausibel_prozent']:.1f} %) · Formeln {w['formeln']} · Grafiken {w['grafiken']}"
              f" · Selbstcheck-Fragen {w['fragen']}")
        for f in fehler:
            print(f"    ✘ {f}")
        for w_ in warnungen:
            print(f"    ⚠ {w_}")
    if offen:
        print(f"\nNoch ohne Zusammenfassung ({len(offen)}): {', '.join(offen)}")
    print("\nERGEBNIS:", "alles in Ordnung" if ok else "PROBLEME GEFUNDEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
