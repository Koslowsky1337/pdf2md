r"""
Prüft die von /zusammenfassen erzeugten Zusammenfassungen gegen ihren Lerntext.

Aufruf:
    python tools\zusammenfassung_pruefen.py                      -> alle Hefte unter output
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>"  -> nur dieser Ordner (rekursiv)
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>\…\<Heft>"  -> nur dieses Heft

Geprüft wird jede „<X> - Zusammenfassung.md“, die neben einer „<X> - Lerntext.md“ liegt:
YAML-Kopf, alle Hauptkapitel, alle nummerierten Definitionen, Seitenangaben „(S. N)“,
keine Übungen/Aufgaben/Lösungen/Literatur/Quellen, jede Zahl (ab 2 Ziffern) steht im Lerntext.
Nur Warnungen: Länge außerhalb 5–25 %, Fettbegriffe, die im Lerntext fehlen, und Seitenangaben,
bei denen weniger als 30 % der Inhaltswörter (ab 6 Buchstaben) auf der Seite oder einer Nachbarseite stehen.
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
BILD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
SEITENMARKE = re.compile(r"<!-- Seite \d+ -->")
SEITENANGABE = re.compile(r"\(S\.[^)]*\)")
ZAHL = re.compile(r"\b\d{1,3}(?:[ .  ]\d{3})+\b|\d+")      # mit Tausendertrennern oder ohne


def pruefen(lerntext: pathlib.Path, zusammenfassung: pathlib.Path):
    """Rückgabe: (Fehlerliste, Warnungsliste, Länge in %, Kennzahlen zu g/h/i)."""
    lt = lerntext.read_text(encoding="utf-8")
    zf = zusammenfassung.read_text(encoding="utf-8")
    zf_zeilen = zf.splitlines()
    fehler, warnungen = [], []

    # a) YAML-Kopf
    kopf, _ = aufteilen.front_matter(zf_zeilen)
    if kopf.get("teil") != "Zusammenfassung":
        fehler.append('YAML-Kopf mit teil: "Zusammenfassung" fehlt')

    # b) Hauptkapitel
    kapitel, kapitel_titel = [], set()       # Titel als „8 Titel“, ohne ** und mit normalisiertem Leerraum
    for z in lt.splitlines():
        if (m := aufteilen.KAPITEL.match(z)) and "." not in m.group(1):
            kapitel_titel.add(aufteilen.klartext(z[m.start(1):]))
            if m.group(1) not in kapitel:
                kapitel.append(m.group(1))
    fehlend = [k for k in kapitel if not any(re.match(rf"##\s+{k}(\s|$)", z) for z in zf_zeilen)]
    if fehlend:
        fehler.append(f"Hauptkapitel fehlen als „## <Nr> …“: {', '.join(fehlend)}")

    # c) nummerierte Definitionen
    definitionen = dict.fromkeys(re.findall(r"Definition\s+(\d+(?:\.\d+)*)", lt))
    fehlend = [d for d in definitionen if not re.search(rf"Definition\s+{re.escape(d)}(?!\.?\d)", zf)]
    if fehlend:
        fehler.append(f"Definitionen fehlen: {', '.join(fehlend)}")

    # d) Seitenangaben
    seiten = set(re.findall(r"<!-- Seite (\d+) -->", lt))
    abschnitte = re.split(r"^(?=## )", zf, flags=re.M)[1:]
    ohne = [a.splitlines()[0][3:].strip() for a in abschnitte if not re.search(r"\(S\.\s*\d", a)]
    if ohne:
        fehler.append(f"Abschnitte ohne „(S. N)“: {'; '.join(ohne)}")
    falsch = sorted({n for angabe in re.findall(r"\(S\.\s*([^)]*)\)", zf)
                     for n in re.findall(r"\d+", angabe) if n not in seiten}, key=int)
    if falsch:
        fehler.append(f"Seitenangaben ohne passende Seite im Lerntext: {', '.join(falsch)}")

    # e) verbotene Überschriften – erlaubt nur, wenn „## <Nr> <Titel>“ genau ein Hauptkapitel des Lerntexts ist
    verboten = [z.strip() for z in zf_zeilen if aufteilen.UEBERSCHRIFT.match(z) and VERBOTEN.search(z)
                and not (re.match(r"##\s", z) and aufteilen.klartext(z) in kapitel_titel)]
    if verboten:
        fehler.append(f"verbotene Überschriften: {'; '.join(verboten)}")

    # f) Länge
    prozent = len(zf) * 100 / max(len(lt), 1)
    if not 5 <= prozent <= 25:
        warnungen.append(f"Länge {prozent:.1f} % (erwartet 5–25 %)")

    _, start = aufteilen.front_matter(zf_zeilen)
    inhalt = [(nr, z) for nr, z in enumerate(zf_zeilen, 1) if nr > start]   # ohne YAML-Kopf
    lt_text = BILD.sub(" ", SEITENMARKE.sub(" ", lt))

    # g) Zahlen: jede Ziffernfolge ab 2 Ziffern muss im Lerntext stehen
    lt_zahlen, lt_teile = zahlen(lt_text)
    zahl_fehler = []
    for nr, z in inhalt:
        z = re.sub(r"Definition\s+\d+(?:\.\d+)*", " ", SEITENANGABE.sub(" ", BILD.sub(" ", z)))
        z = re.sub(r"^##\s+\d+", " ", z)
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
        for begriff in re.findall(r"\*\*(.+?)\*\*", z):
            begriff = re.sub(r"^Definition\s+\d+(?:\.\d+)*\s*[–-]\s*", "", begriff).strip().rstrip(":").strip()
            if begriff and re.sub(r"\s+", " ", begriff).lower() not in lt_flach:
                fett_fehlt.append(f"{begriff} (Zeile {nr})")
    if fett_fehlt:
        warnungen.append(f"Fettbegriffe nicht im Lerntext ({len(fett_fehlt)}): {'; '.join(fett_fehlt[:10])}"
                         + (" …" if len(fett_fehlt) > 10 else ""))

    # i) Seiten plausibel (nur Warnung): ≥ 30 % der Inhaltswörter stehen auf Seite N oder einer Nachbarseite
    seitentext = {int(n): t.lower() for n, t in
                  re.findall(r"<!-- Seite (\d+) -->\n(.*?)(?=<!-- Seite \d+ -->|\Z)", lt, re.S)}
    mit_seite, unplausibel = 0, []
    for nr, z in inhalt:
        angaben = [int(n) for a in re.findall(r"\(S\.\s*([^)]*)\)", z) for n in re.findall(r"\d+", a)]
        if not angaben:
            continue
        mit_seite += 1
        woerter = set(re.findall(r"[a-zäöüß]{6,}", SEITENANGABE.sub(" ", BILD.sub(" ", z)).lower()))
        if len(woerter) < 3:
            continue
        umfeld = " ".join(seitentext.get(s + d, "") for s in angaben for d in (-1, 0, 1))
        if sum(w in umfeld for w in woerter) < 0.3 * len(woerter):
            unplausibel.append(nr)
    unplausibel_prozent = len(unplausibel) * 100 / max(mit_seite, 1)
    if unplausibel:
        warnungen.append(f"Seiten unplausibel: {len(unplausibel)} / {mit_seite} Zeilen mit Seitenangabe "
                         f"({unplausibel_prozent:.1f} %), z. B. Zeilen {', '.join(map(str, unplausibel[:5]))}")

    werte = {"zahlen": len(zahl_fehler), "fett": len(fett_fehlt),
             "unplausibel": len(unplausibel), "mit_seite": mit_seite, "unplausibel_prozent": unplausibel_prozent}
    return fehler, warnungen, prozent, werte


def zahlen(text: str):
    """Zahlen ab 2 Ziffern, Tausendertrenner vereinheitlicht („1 890“ = „1.890“ = „1890“).
    Rückgabe: ({vereinheitlicht: wie geschrieben}, alle einzelnen Ziffernfolgen ab 2 Ziffern)."""
    ganz = {}
    for roh in ZAHL.findall(text):
        if len(zahl := re.sub(r"\D", "", roh)) >= 2:
            ganz.setdefault(zahl, roh)
    return ganz, {t for t in re.findall(r"\d+", text) if len(t) >= 2}


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
              f" · Fettbegriff-Warnungen {w['fett']} · Seiten unplausibel {w['unplausibel']} / {w['mit_seite']}"
              f" ({w['unplausibel_prozent']:.1f} %)")
        for f in fehler:
            print(f"    ✘ {f}")
        for w in warnungen:
            print(f"    ⚠ {w}")
    if offen:
        print(f"\nNoch ohne Zusammenfassung ({len(offen)}): {', '.join(offen)}")
    print("\nERGEBNIS:", "alles in Ordnung" if ok else "PROBLEME GEFUNDEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
