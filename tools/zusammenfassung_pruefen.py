r"""
Prüft die von /zusammenfassen erzeugten Zusammenfassungen gegen ihren Lerntext.

Aufruf:
    python tools\zusammenfassung_pruefen.py                      -> alle Hefte unter output
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>"  -> nur dieser Ordner (rekursiv)
    python tools\zusammenfassung_pruefen.py "output\<Name des PDF-Ordners>\…\<Heft>"  -> nur dieses Heft

Geprüft wird jede „<X> - Zusammenfassung.md“, die neben einer „<X> - Lerntext.md“ liegt:
YAML-Kopf, alle Hauptkapitel, alle nummerierten Definitionen, Seitenangaben „(S. N)“,
keine Übungen/Aufgaben/Lösungen/Literatur/Quellen, Länge 5–25 % des Lerntexts (sonst nur Warnung).
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


def pruefen(lerntext: pathlib.Path, zusammenfassung: pathlib.Path):
    """Rückgabe: (Fehlerliste, Warnungsliste, Länge in %)."""
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
    return fehler, warnungen, prozent


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
        fehler, warnungen, prozent = pruefen(lt, zf)
        ok &= not fehler
        print(f"{'✔' if not fehler else '✘'} {heft}: Länge {prozent:.1f} %")
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
