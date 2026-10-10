r"""
Gesamtprüfung aller umgewandelten Hefte gegen die Original-PDFs (Regressionstest nach Code-Änderungen).

Aufruf:
    python tools\endpruefung.py "<PDF-Ordner>"  -> prüft <PDF-Ordner> gegen output\<Name des PDF-Ordners>

Voraussetzung: Der Ordner wurde vorher mit pdf2md umgewandelt.
Endet mit „ERGEBNIS: alles in Ordnung“ oder „PROBLEME GEFUNDEN“ (Exit-Code 1).
"""
import collections
import pathlib
import re
import sys

for strom in (sys.stdout, sys.stderr):      # ✔/✘ dürfen bei umgeleiteter Ausgabe (cp1252) nicht abstürzen
    try:
        strom.reconfigure(errors="replace")
    except Exception:
        pass

PROJEKT = pathlib.Path(__file__).resolve().parent.parent
if len(sys.argv) < 2:
    sys.exit('Aufruf: python tools\\endpruefung.py "<PDF-Ordner>"')
QUELLE = pathlib.Path(sys.argv[1])
sys.argv = sys.argv[:1]                      # pdf2md soll keine Argumente sehen
sys.path.insert(0, str(PROJEKT))
import pdf2md                                # noqa: E402
import pymupdf                               # noqa: E402

BASIS = pdf2md.OUTPUT_ROOT / pdf2md.sicherer_name(QUELLE.resolve().name)
TABELLE = re.compile(r"(?:^\|.*\|\s*\n?)+", re.M)
ok = True


def melde(name, wert, gut):
    global ok
    ok &= gut
    print(f"  {'✔' if gut else '✘'} {name}: {wert}")


summe = collections.Counter()
summe["vollst_min"] = 100.0
pdfs = sorted(pdf2md.pdfs_im_ordner(QUELLE))
for pdf in pdfs:
    rel = pdf.relative_to(QUELLE).parent.parts
    ziel = pdf2md.ausgabe_ordner(pdf, BASIS.joinpath(*(pdf2md.sicherer_name(t, 40) for t in rel)))
    md_datei = ziel / f"{ziel.name}.md"
    if not md_datei.is_file():
        print(f"  ✘ fehlt: {md_datei}")
        ok = False
        continue
    md = md_datei.read_text(encoding="utf-8")
    doc = pymupdf.open(pdf)
    seiten = dict(re.findall(r"<!-- Seite (\d+) -->\n(.*?)(?=<!-- Seite \d+ -->|\Z)", md, re.S))

    summe["seiten_pdf"] += doc.page_count
    summe["seiten_md"] += len(seiten)
    summe["fffd"] += md.count("\ufffd")
    summe["ligatur"] += len(re.findall(r"\b([a-zäöüß]\w*|[A-ZÄÖÜ]\w+) \*\*([lftks])\*\* ([a-zäöüß]\w*)", md))
    summe["trennung_br"] += len(re.findall(r"\w-<br>[a-zäöüß]", md))
    for nr, text in seiten.items():
        w = pdf2md.seiten_woerter(doc[int(nr) - 1])
        summe["tab_schnitt"] += sum(pdf2md.tabelle_zerschnitten(z, w) for z in text.splitlines() if z.startswith("|"))
        summe["tab_stumpf"] += sum(len(pdf2md.tabelle_stuempfe(t, w)) for t in TABELLE.findall(text))
        summe["tabellen"] += len(TABELLE.findall(text))
        summe["gerettet"] += text.count("![Tabelle Seite")
    summe["formeln"] += md.count("![Formel Seite")
    links = re.findall(r"\]\((images/[^)]+)\)", md)
    summe["bildlinks"] += len(links)
    summe["bild_fehlt"] += sum(1 for l in links if not (ziel / l).is_file())
    for teil in ("Lerntext", "Aufgaben", "Lösungen"):
        f = ziel / f"{ziel.name} - {teil}.md"
        if f.is_file():
            summe["teile"] += 1
            summe["bild_fehlt"] += sum(1 for l in re.findall(r"\]\((images/[^)]+)\)", f.read_text(encoding="utf-8"))
                                       if not (ziel / l).is_file())
    v = re.search(r'vollstaendigkeit: "([\d,]+) %"', md)
    summe["vollst_min"] = min(summe["vollst_min"], float(v.group(1).replace(",", ".")) if v else 0.0)
    summe["probleme"] += len(re.findall(r"– bitte prüfen\.", md))

print(f"Gesamtprüfung über {len(pdfs)} PDF(s) aus {QUELLE}:")
melde("Seiten PDF = Seiten .md", f"{summe['seiten_pdf']} / {summe['seiten_md']}", summe["seiten_pdf"] == summe["seiten_md"])
melde("unlesbare Zeichen (�)", summe["fffd"], summe["fffd"] == 0)
melde("Ligatur-Lücken („Kontro **l** e“)", summe["ligatur"], summe["ligatur"] == 0)
melde("Silbentrennung in Tabellen („Verkehrs-<br>mittel“)", summe["trennung_br"], summe["trennung_br"] == 0)
melde("zerschnittene Wörter in Tabellen", summe["tab_schnitt"], summe["tab_schnitt"] == 0)
melde("Wortstümpfe in Tabellen", summe["tab_stumpf"], summe["tab_stumpf"] == 0)
print(f"  ℹ Tabellen: {summe['tabellen']} als Tabelle erhalten, {summe['gerettet']} als Bild + Fließtext übernommen")
print(f"  ℹ Formeln als Bild + Text: {summe['formeln']}")
melde("Bildlinks ohne Datei", f"{summe['bild_fehlt']} von {summe['bildlinks']}", summe["bild_fehlt"] == 0)
print(f"  ℹ Teil-Dateien (Lerntext/Aufgaben/Lösungen): {summe['teile']}")
melde("niedrigste Vollständigkeit", f"{summe['vollst_min']:.2f} %", summe["vollst_min"] >= 99)
melde("Seiten mit Lückenmeldung", summe["probleme"], summe["probleme"] == 0)
print("\nERGEBNIS:", "alles in Ordnung" if ok else "PROBLEME GEFUNDEN")
sys.exit(0 if ok else 1)
