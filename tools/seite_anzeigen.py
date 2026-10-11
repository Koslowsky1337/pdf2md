r"""
Rendert einzelne Seiten einer PDF als PNG, damit man die Originalseite ansehen kann (liest nur, verändert die PDF nie).

Aufruf:
    python tools\seite_anzeigen.py "<PDF>" <Seite> [<Seite> …]

Seiten sind 1-basiert und physisch (wie „<!-- Seite N -->“ in der .md). Ausgabe in 150 dpi nach
output\_seiten\<PDF-Name>_S<N>.png (im Projektordner); die Pfade werden ausgegeben. Bei Fehlern Exit-Code 1.
"""
import pathlib
import sys

for strom in (sys.stdout, sys.stderr):      # Umlaute dürfen bei umgeleiteter Ausgabe (cp1252) nicht abstürzen
    try:
        strom.reconfigure(errors="replace")
    except Exception:
        pass

import pymupdf                               # noqa: E402

DPI = 150
ZIEL = pathlib.Path(__file__).resolve().parent.parent / "output" / "_seiten"


def main():
    if len(sys.argv) < 3:
        sys.exit('Aufruf: python tools\\seite_anzeigen.py "<PDF>" <Seite> [<Seite> …]')
    pdf = pathlib.Path(sys.argv[1])
    if not pdf.is_file():
        sys.exit(f"Fehler: Datei nicht gefunden: {pdf}")
    try:
        seiten = [int(s) for s in sys.argv[2:]]
    except ValueError:
        sys.exit(f"Fehler: Seiten müssen ganze Zahlen sein: {' '.join(sys.argv[2:])}")
    try:
        doc = pymupdf.open(pdf)
    except PermissionError:
        sys.exit(f"Fehler: Zugriff verweigert: {pdf}")
    except Exception as e:
        sys.exit(f"Fehler: keine lesbare PDF: {pdf} ({e})")
    with doc:
        if not doc.is_pdf:
            sys.exit(f"Fehler: keine PDF: {pdf}")
        if doc.needs_pass:
            sys.exit(f"Fehler: PDF ist passwortgeschützt: {pdf}")
        falsch = [s for s in seiten if not 1 <= s <= doc.page_count]
        if falsch:
            sys.exit(f"Fehler: Seite außerhalb des Bereichs 1–{doc.page_count}: {', '.join(map(str, falsch))}")
        ZIEL.mkdir(parents=True, exist_ok=True)
        for s in seiten:
            png = ZIEL / f"{pdf.stem}_S{s}.png"
            doc[s - 1].get_pixmap(dpi=DPI).save(png)
            print(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
