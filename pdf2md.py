r"""
pdf2md – wandelt eine PDF in eine Markdown-Datei (+ Bilder) um.

Aufruf:
    python pdf2md.py                 -> Dateiauswahl-Dialog (mehrere PDFs möglich)
    python pdf2md.py a.pdf b.pdf     -> direkt konvertieren (auch per Drag & Drop auf start.bat)
    python pdf2md.py "<PDF-Ordner>"  -> ganzen Ordner inkl. Unterordner konvertieren
    python pdf2md.py --overwrite x.pdf  -> vorhandene Ausgabe ohne Rückfrage überschreiben
    python pdf2md.py --nogui x.pdf      -> ohne Dialoge (nur Konsole)
    python pdf2md.py -j 4 "<PDF-Ordner>"  -> höchstens 4 PDFs gleichzeitig (Standard: automatisch)
    python pdf2md.py --index "<PDF-Ordner>"  -> nur _index.md neu schreiben (ohne Umwandlung)

Ergebnis:  <Script-Ordner>/output/<PDF-Name>/<PDF-Name>.md  +  images/
Ordner:    <Script-Ordner>/output/<Ordner>/<Unterordner…>/<PDF-Name>/…  +  _index.md
"""

import argparse
import bisect
import collections
import hashlib
import os
import re
import shutil
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- Einstellungen
OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
BILD_DPI = 150                # Auflösung, mit der Grafiken gerendert werden
MIN_BILD_PT = 20              # kleinere Grafiken (Icons, Linien, Aufzählungszeichen) ignorieren
MIN_VEKTOR_PT = 40            # Mindestgröße für freistehende Vektorgrafiken
MERGE_ABSTAND_PT = 12         # Grafik-Teile mit kleinerem Abstand werden zu einem Bild zusammengefasst
MARKIERUNG_INLINE = "**"      # so werden markierte Stellen im Fließtext hervorgehoben
KOPF_FUSSZEILEN = False       # wiederkehrende Kopf-/Fußzeilen (Seitenzahlen etc.) übernehmen?
MAX_PROZESSE = 0              # gleichzeitig verarbeitete PDFs; 0 = automatisch (nach Kernen und RAM)
RAM_PRO_PROZESS_GB = 0.5      # geschätzter Arbeitsspeicher pro paralleler PDF (gemessen: ca. 0,3 GB)
KI_THREADS = 4                # Threads der Layout-KI bei einer einzelnen PDF (mehr bringt nichts)

TEXT_MARKUP = {"Highlight": "Markiert", "Underline": "Unterstrichen",
               "Squiggly": "Unterschlängelt", "StrikeOut": "Durchgestrichen"}
NOTIZ_TYPEN = {"Text": "Notiz", "FreeText": "Textfeld"}
IGNORIERTE_ANNOTS = {"Link", "Widget", "Popup"}
_THREADS_ENV = "PDF2MD_KI_THREADS"   # gibt Worker-Prozessen ihre Thread-Zahl mit


def _ki_threads_begrenzen(anzahl: int):
    """Die Layout-KI (onnxruntime) startet sonst einen Thread pro Kern; die bremsen sich gegenseitig
    aus (gemessen: 23 Kerne belegt, aber langsamer als mit 4). Muss vor dem Import von pymupdf4llm laufen."""
    try:
        import onnxruntime as ort
    except ImportError:
        return
    original = ort.InferenceSession

    def begrenzt(*args, **kwargs):
        args = list(args)
        optionen = (args[1] if len(args) > 1 else kwargs.get("sess_options")) or ort.SessionOptions()
        optionen.intra_op_num_threads = anzahl
        optionen.inter_op_num_threads = 1
        if len(args) > 1:
            args[1] = optionen
        else:
            kwargs["sess_options"] = optionen
        return original(*args, **kwargs)

    ort.InferenceSession = begrenzt


_ki_threads_begrenzen(int(os.environ.get(_THREADS_ENV, KI_THREADS)))

try:
    import aufteilen
    import pymupdf
    import pymupdf4llm
except ImportError:
    print("Fehlende Abhängigkeiten. Bitte einmalig ausführen:\n"
          "    python -m pip install -r requirements.txt")
    input("\nEnter zum Beenden ...")
    sys.exit(1)


# ---------------------------------------------------------------- Hilfsfunktionen
def sicherer_name(name: str, max_len: int = 80) -> str:
    """Macht aus einem beliebigen Dateinamen einen gültigen Windows-Ordner-/Dateinamen."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:max_len].strip(" .")
    if not name or name.upper().split(".")[0] in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}:
        name = f"pdf_{name or 'dokument'}"
    return name


def trennungen_aufloesen(text: str) -> str:
    """Silbentrennungen in Tabellenzellen (Zeilenumbruch = <br>) zusammenziehen, damit Wörter
    durchsuchbar sind: „Verkehrs-<br>mittel“ -> „Verkehrsmittel“. Ergänzungsstriche
    („Lager-<br>und Transportkosten“) und Bindestrichwörter („E-<br>Mail“) behalten ihren Strich."""
    text = re.sub(r"(\w)-<br>(?=(und|oder|bzw|sowie|bis|als)\b)", r"\1- ", text)
    text = re.sub(r"(\w)-<br>(?=[a-zäöüß])", r"\1", text)
    text = re.sub(r"(\w)-<br>(?=[A-ZÄÖÜ\d])", r"\1-", text)
    return re.sub(r"<br>([•\-–])<br>", r"<br>\1 ", text)          # Aufzählungspunkt an seinen Text


def _doppel_ligatur(m) -> str:
    vor, buchstabe, nach = m.groups()
    # „Me **s** sung“: der Buchstabe ist einfach -> nur zusammenziehen; sonst fehlt einer („Kontro **l** e“)
    return vor + (buchstabe if nach.startswith(buchstabe) else buchstabe * 2) + nach


def zeichen_reparieren(text: str) -> tuple[str, int]:
    """Repariert Zeichen, die bei der Textextraktion verloren gehen (beobachtet in deutschsprachigen Lehrheften):
    1. Doppelbuchstaben-Ligaturen (ll, tt, ff, kk, ss) kommen als einzelner fetter Buchstabe mit
       Leerzeichen heraus: „Kontro **l** e“ -> „Kontrolle“, „h **t** ps“ -> „https“.
    2. „�“ – Zeichen ohne Text-Zuordnung in der Schrift: Tausendertrenner und feste Leerzeichen
       (≈ 95 %), Platzhalter-Linien und Office-Ligaturen (ti, ft, fb)."""
    # Wortteil davor: klein beginnend oder mind. 2 Zeichen – schützt „**A** ausgabe“ (Buchstaben-Register)
    text, anzahl = re.subn(r"\b([a-zäöüß]\w*|[A-ZÄÖÜ]\w+) \*\*([lftks])\*\* ([a-zäöüß]\w*)", _doppel_ligatur, text)
    anzahl += text.count("�")
    if "�" not in text:
        return text, anzahl
    text = re.sub(r"\*\*�+\*\*", " ", text)                    # fett gesetzte Trenner
    text = re.sub(r"�{3,}", "______", text)                     # Lücken-/Platzhalterlinien
    text = re.sub(r"scha�", "schaft", text)                     # Wirtscha� -> Wirtschaft
    text = re.sub(r"u�au", "ufbau", text)                       # Au�au -> Aufbau
    text = re.sub(r"(?<=[a-zäöüß])�(?=(on|ge|g\b|k\b|sch|v|ef|ere|al\b))", "ti", text)  # Kri�k, Sta�on
    return text.replace("�", " "), anzahl                       # 100�000 -> 100 000, Abs.�1 -> Abs. 1


def merge_rects(rects, abstand):
    """Fasst überlappende/nahe Rechtecke transitiv zusammen."""
    gruppen = [pymupdf.Rect(r) for r in rects]
    geaendert = True
    while geaendert:
        geaendert = False
        for i in range(len(gruppen)):
            gross = gruppen[i] + (-abstand, -abstand, abstand, abstand)
            for j in range(i + 1, len(gruppen)):
                if gross.intersects(gruppen[j]):
                    gruppen[i] |= gruppen.pop(j)
                    geaendert = True
                    break
            if geaendert:
                break
    return sorted(gruppen, key=lambda r: (r.y0, r.x0))


def zu_klein(rect, minimum=MIN_BILD_PT):
    return rect.width < minimum or rect.height < minimum


class BildSpeicher:
    """Rendert Bereiche einer Seite als PNG, vermeidet Duplikate."""

    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.bekannt = {}          # (breite, hoehe, sha1 der Pixeldaten) -> link
        self.anzahl = 0

    def speichern(self, page, rect, ganze_seite=False, minimum=MIN_BILD_PT) -> str | None:
        clip = None if ganze_seite else pymupdf.Rect(rect) & page.rect
        if clip is not None and (clip.is_empty or zu_klein(clip, minimum)):
            return None
        pix = page.get_pixmap(dpi=BILD_DPI, clip=clip, annots=False)
        if pix.width < 2 or pix.height < 2:
            return None
        # Nur pixelgleiche Bilder zusammenlegen: ähnliche (z. B. einzeilige Formeln) sind oft verschieden
        schluessel = (pix.width, pix.height, hashlib.sha1(pix.samples).hexdigest())
        if schluessel in self.bekannt:
            return self.bekannt[schluessel]
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.anzahl += 1
        name = f"seite{page.number + 1:03d}_bild{self.anzahl:02d}.png"
        pix.save(self.ordner / name)
        link = f"images/{name}"
        self.bekannt[schluessel] = link
        return link


# ---------------------------------------------------------------- Annotationen
def text_unter_quads(page, annot, woerter):
    verts = annot.vertices or []
    quads = [pymupdf.Quad(verts[i:i + 4]).rect for i in range(0, len(verts) - 3, 4)] or [annot.rect]
    gefunden = []
    for q in quads:
        q = q + (-1, -1, 1, 1)
        zeile = [w for w in woerter
                 if q.contains(pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))]
        for w in sorted(zeile, key=lambda w: (round(w[3]), w[0])):
            if not gefunden or gefunden[-1] is not w:
                gefunden.append(w)
    # Wörter, die in mehreren Quads liegen, nur einmal
    eindeutig = list(dict.fromkeys(gefunden))
    return " ".join(w[4] for w in eindeutig).strip()


def annotationen_lesen(page):
    """Liefert Liste von dicts: art, text, kommentar, inline(markdown-zeichen oder None)."""
    ergebnisse = []
    try:
        annots = list(page.annots())
    except Exception:
        return ergebnisse
    if not annots:
        return ergebnisse
    woerter = page.get_text("words")
    for a in annots:
        try:
            typ = a.type[1]
            if typ in IGNORIERTE_ANNOTS:
                continue
            kommentar = (a.info.get("content") or "").strip()
            if typ in TEXT_MARKUP:
                text = text_unter_quads(page, a, woerter)
                inline = "~~" if typ == "StrikeOut" else MARKIERUNG_INLINE
                ergebnisse.append(dict(art=TEXT_MARKUP[typ], text=text, kommentar=kommentar, inline=inline))
            elif typ in NOTIZ_TYPEN:
                if kommentar:
                    ergebnisse.append(dict(art=NOTIZ_TYPEN[typ], text="", kommentar=kommentar, inline=None))
            else:  # Ink, Square, Circle, Stamp, ...
                ergebnisse.append(dict(art=f"Zeichnung ({typ})", text="", kommentar=kommentar, inline=None))
        except Exception as e:
            ergebnisse.append(dict(art="Unlesbare Annotation", text="", kommentar=str(e), inline=None))
    return ergebnisse


def inline_markieren(md: str, text: str, zeichen: str) -> tuple[str, bool]:
    """Setzt Markdown-Hervorhebung um die erste passende Stelle (Leerraum-tolerant)."""
    woerter = text.split()
    if not woerter:
        return md, False
    muster = re.compile(r"\s+".join(re.escape(w) for w in woerter))
    for m in muster.finditer(md):
        davor, danach = md[max(0, m.start() - 2):m.start()], md[m.end():m.end() + 2]
        if davor == zeichen and danach == zeichen:      # schon hervorgehoben
            return md, True
        return md[:m.start()] + zeichen + m.group(0) + zeichen + md[m.end():], True
    return md, False


# ---------------------------------------------------------------- Seiten-Aufbau
def seiten_woerter(page) -> set:
    return {re.sub(r"\W+", "", w[4]).lower() for w in page.get_text("words")}


def _schnitt(x: str, y: str, woerter: set):
    """Endet Teilzeile x und beginnt Teilzeile y mitten im selben Wort? Gegenprobe mit der PDF-Seite:
    „Fen“+„ster“ muss dort als Wort stehen, „Fen“ allein nicht – sonst sind es zufällig klein
    beginnende Stichpunkte nebeneinander. Rückgabe: (Match x, Match y) oder None."""
    mx = re.search(r"(\w+)(\**)$", x.strip())
    my = re.match(r"(\**)([a-zäöüß]\w*)(\**)", y.strip())
    if mx and my and mx.group(1).lower() not in woerter and (mx.group(1) + my.group(2)).lower() in woerter:
        return mx, my
    return None


def tabelle_zerschnitten(zeile: str, woerter: set) -> int:
    """Größte Zahl zerschnittener Teilzeilen zwischen zwei Nachbarzellen dieser Tabellenzeile."""
    zellen = zeile.strip().strip("|").split("|")
    return max((sum(1 for x, y in zip(a.split("<br>"), b.split("<br>")) if _schnitt(x, y, woerter))
                for a, b in zip(zellen, zellen[1:])), default=0)


def _zeile_flicken(zeile: str, woerter: set) -> str:
    zellen = [c.split("<br>") for c in zeile.strip().strip("|").split("|")]
    for a, b in zip(zellen, zellen[1:]):
        for k in range(min(len(a), len(b))):
            if treffer := _schnitt(a[k], b[k], woerter):
                mx, my = treffer
                x, y = a[k].strip(), b[k].strip()
                a[k] = x[:mx.start(2)] + my.group(2) + mx.group(2)
                rest = y[my.end():] if my.group(3) else y[my.end(2):]
                b[k] = "" if not rest.strip("* ") else (my.group(1) if not my.group(3) else "") + rest.lstrip()
        # geleerte Teilzeilen entfernen, damit nachfolgende Wortteile auf gleiche Höhe rücken
        b[:] = [t for t in b if t.strip()] or [""]
    return "|" + "|".join("<br>".join(c) for c in zellen) + "|"


def tabelle_flicken(tabelle: str, woerter: set) -> str:
    """Zerschnittene Wörter in der Tabelle wieder zusammensetzen: „|Fen|ster|“ -> „|Fenster||“.
    Wiederholt, bis sich nichts mehr ändert – die Fehler der Layout-KI sind oft verkettet
    („|Jahresüber|sicht<br>Lager|bestand II|“: erst „sicht“ zurück, dann rückt „Lager“ auf)."""
    ergebnis = []
    for zeile in tabelle.splitlines():
        if zeile.startswith("|") and not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+\s*", zeile):
            for _ in range(5):
                neu = _zeile_flicken(zeile, woerter)
                if neu == zeile:
                    break
                zeile = neu
        ergebnis.append(zeile)
    return "\n".join(ergebnis) + ("\n" if tabelle.endswith("\n") else "")


def tabelle_stuempfe(tabelle: str, woerter: set) -> list[str]:
    """Wortstümpfe am Ende von Tabellen-Teilzeilen: auf der PDF-Seite kein Wort, aber Anfang eines
    längeren Worts („Verwaltun“, „Beschaffun“). Findet Zerschneidungen unabhängig davon, ob die
    Wortteile in den Zellen auf gleicher Höhe stehen."""
    sortiert = sorted(woerter)
    stuempfe = []
    for zeile in tabelle.splitlines():
        if not zeile.startswith("|"):
            continue
        for teil in re.split(r"\||<br>", zeile):
            m = re.search(r"(?<![\w-])([A-Za-zÄÖÜäöüß]{2,})\**\s*$", teil)
            if not m or (w := m.group(1).lower()) in woerter:
                continue
            i = bisect.bisect_left(sortiert, w)
            if i < len(sortiert) and sortiert[i].startswith(w) and len(sortiert[i]) >= len(w) + 2:
                stuempfe.append(m.group(1))
    return stuempfe


def _woerter(text: str) -> dict:
    text = re.sub(r"(\w)-(?:<br>|\n)\s*(\w)", r"\1\2", text)          # Silbentrennung
    zaehler = {}
    for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{2,}", text):
        zaehler[w.lower()] = zaehler.get(w.lower(), 0) + 1
    return zaehler


def tabelle_retten(page, rect, bilder, hinweise, woerter) -> str:
    """Ersatz für eine von der Layout-KI zerschnittene Tabelle. Erst klassische Tabellenerkennung
    (nur wenn sie dieselben Wörter wie die PDF liefert), sonst Bild der Tabelle + Text in Lesereihenfolge."""
    nr = page.number + 1
    clip = (rect + (-3, -3, 3, 3)) & page.rect
    soll = _woerter(page.get_text("text", clip=clip))
    n_soll = sum(soll.values()) or 1
    try:
        for t in page.find_tables(clip=clip, strategy="lines").tables:
            md = t.to_markdown()
            ist = _woerter(md)
            fehlt = sum(max(0, n - ist.get(w, 0)) for w, n in soll.items())
            extra = sum(max(0, n - soll.get(w, 0)) for w, n in ist.items())
            if (fehlt <= 0.02 * n_soll and extra <= 0.02 * n_soll
                    and not any(tabelle_zerschnitten(z, woerter) for z in md.splitlines())
                    and not tabelle_stuempfe(md, woerter)):
                hinweise.append(f"Seite {nr}: Tabelle mit klassischer Erkennung neu gelesen.")
                return md.strip() + "\n\n"
    except Exception:
        pass
    link = bilder.speichern(page, clip)
    bloecke = [b[4].strip() for b in page.get_text("blocks", clip=clip, sort=True) if b[6] == 0 and b[4].strip()]
    text = "\n\n".join(re.sub(r"\s+", " ", re.sub(r"(\w)-\n(\w)", r"\1\2", b)) for b in bloecke)
    hinweise.append(f"Seite {nr}: Tabelle nicht sauber lesbar – als Bild + Fließtext übernommen.")
    return (f"![Tabelle Seite {nr}]({link})\n\n" if link else "") + text + "\n\n"


# ---------------------------------------------------------------- Formeln
def _bruchstriche(page) -> list:
    """Waagerechte, dünne Linien/Rechtecke einer Seite – mögliche Bruchstriche."""
    striche = []
    try:
        zeichnungen = page.get_drawings()
    except Exception:
        return striche
    for d in zeichnungen:
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 0.8 and abs(it[2].x - it[1].x) > 6:
                striche.append(pymupdf.Rect(min(it[1].x, it[2].x), it[1].y, max(it[1].x, it[2].x), it[1].y))
            elif it[0] == "re" and it[1].height < 1.5 and it[1].width > 6:
                y = (it[1].y0 + it[1].y1) / 2
                striche.append(pymupdf.Rect(it[1].x0, y, it[1].x1, y))
    return striche


def _zeilen(tokens) -> list[list]:
    """Tokens (x0, x1, y_mitte, text, …) zu Zeilen gruppieren, jede Zeile von links nach rechts."""
    zeilen = []
    for t in sorted(tokens, key=lambda t: t[2]):
        if zeilen and abs(sum(x[2] for x in zeilen[-1]) / len(zeilen[-1]) - t[2]) < 7:
            zeilen[-1].append(t)
        else:
            zeilen.append([t])
    for z in zeilen:
        z.sort(key=lambda t: t[0])
    return zeilen


def _zeilen_text(tokens) -> list[str]:
    """Tokens (x0, x1, y_mitte, text) zu Zeilen gruppieren; sich berührende Stücke ohne Leerzeichen
    verbinden (manche PDFs setzen einzelne Buchstaben als eigene Textstücke: „Sta|t|is|t|ik“)."""
    ergebnis = []
    for z in _zeilen(tokens):
        text = z[0][3]
        for vor, t in zip(z, z[1:]):
            text += ("" if t[0] - vor[1] < 1.0 else " ") + t[3]
        ergebnis.append(text)
    return ergebnis


_LATEX_ZEICHEN = {"⋅": r"\cdot", "·": r"\cdot", "×": r"\cdot", "*": r"\cdot", "−": "-", "–": "-",
                  "≤": r"\le", "≥": r"\ge", "%": r"\%", "€": r"\text{€}", "{": r"\{", "}": r"\}",
                  "Δ": r"\Delta", "Σ": r"\Sigma", "∑": r"\sum", "√": r"\surd", "→": r"\rightarrow"}
# große Klammern der Symbol-Schrift bestehen aus Teilstücken (oben/Mitte/unten, Private-Use-Bereich):
# das Mittelstück steht auf der Formelzeile und wird zur Klammer, die übrigen Teilstücke entfallen
_LATEX_ZEICHEN.update({chr(c): "" for c in range(0xF0E6, 0xF0FF)})
_LATEX_ZEICHEN.update({"": "(", "": ")", "": "[", "": "]", "": r"\{", "": r"\}"})
_TEXT_ESCAPE = {"#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&", "_": r"\_", "{": r"\{", "}": r"\}",
                "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}
_LATEX_TEIL = re.compile(r"(?P<zahl>\d{1,3}(?: \d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
                         r"|(?P<wort>[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß.'\-]*)|(?P<leer>\s+)|(?P<zeichen>.)")


def _latex_text(t: str) -> str:
    return r"\text{" + "".join(_TEXT_ESCAPE.get(c, c) for c in t) + "}"


def latex(text: str) -> str:
    """Formelzeile als LaTeX: Wortfolgen -> \\text{…}, einzelne Buchstaben, Zahlen und Operatoren als Mathe."""
    teile, woerter = [], []

    def woerter_abschliessen():
        if woerter:
            teile.append(_latex_text(" ".join(woerter)))
            woerter.clear()

    for m in _LATEX_TEIL.finditer(text):
        art, t = m.lastgroup, m.group()
        if art == "leer":
            continue
        if art == "wort" and (len(t) > 1 or not t.isascii()):
            woerter.append(t)
            continue
        woerter_abschliessen()
        if art == "zahl":
            teile.append(t.replace(",", "{,}").replace(" ", r"\,"))    # Dezimalkomma, Tausendertrenner
        elif art == "wort" or t in "=+-/()[]<>,;:.!|'" or (t.isascii() and t not in _TEXT_ESCAPE):
            teile.append(t)
        elif t in _LATEX_ZEICHEN:
            if _LATEX_ZEICHEN[t]:
                teile.append(_LATEX_ZEICHEN[t])
        else:
            teile.append(_latex_text(t))
    woerter_abschliessen()
    return " ".join(teile)


def _zeile_latex(zeile) -> str:
    """Eine Zeile aus Wörtern (latex=None) und fertigen Brüchen (latex gesetzt) als LaTeX."""
    teile, roh, vor = [], "", None
    for t in zeile:
        if t[4] is None:
            roh += ("" if not roh or t[0] - vor[1] < 1.0 else " ") + t[3]
        else:
            if roh:
                teile.append(latex(roh))
                roh = ""
            teile.append(t[4])
        vor = t
    if roh:
        teile.append(latex(roh))
    return " ".join(teile)


def formel_text(page, clip, striche) -> tuple[str, int]:
    """Formel als LaTeX, eine Zeile pro Formelzeile, Brüche als \\frac{Zähler}{Nenner}.
    Rückgabe: (LaTeX-Zeilen, Anzahl Striche mit Text darüber und darunter – Brüche oder Summenstriche;
    > 0 heißt: Textbox ist eine Formel bzw. Rechnung)."""
    # Stücke: [x0, oben, x1, unten, text, latex] – Wörter (latex None) und fertige Brüche
    stuecke = [[w[0], w[1], w[2], w[3], w[4], None] for w in page.get_text("words", clip=clip)]
    im_clip = sorted((s for s in striche if clip.contains(pymupdf.Point(s.x0 + 1, s.y0))
                      and clip.contains(pymupdf.Point(s.x1 - 1, s.y0))), key=lambda s: s.width)
    benutzt, treffer = set(), 0
    for s in im_clip:
        # schmale Striche zuerst: ein innerer Bruch ist dann schon fertig und landet
        # als Ganzes im Zähler/Nenner des äußeren Bruchs (verschachtelte Brüche)
        frei = [i for i in range(len(stuecke)) if i not in benutzt
                and stuecke[i][0] >= s.x0 - 3 and stuecke[i][2] <= s.x1 + 3]
        zaehler = [i for i in frei if s.y0 - 14 <= stuecke[i][3] <= s.y0 + 2]
        nenner = [i for i in frei if s.y0 - 2 <= stuecke[i][1] <= s.y0 + 14]
        if not zaehler or not nenner:
            continue                                    # Unterstreichung o. Ä., kein Bruch
        treffer += 1
        nenner = [i for i in nenner if i not in zaehler]
        if not nenner:
            continue
        breite = lambda ids: max(stuecke[i][2] for i in ids) - min(stuecke[i][0] for i in ids)
        if max(breite(zaehler), breite(nenner)) < 0.6 * s.width:
            continue                                    # viel breiter als Zähler/Nenner: Rahmen- oder Tabellenlinie
        mitte = lambda ids: (max(stuecke[i][2] for i in ids) + min(stuecke[i][0] for i in ids)) / 2
        if any(abs(mitte(ids) - (s.x0 + s.x1) / 2) > 0.25 * s.width for ids in (zaehler, nenner)):
            continue                                    # nicht mittig: Summenstrich eines Rechenschemas
        # mehrzeilige Zähler/Nenner: direkt anschließende Zeilen innerhalb der Strichbreite gehören dazu,
        # aber nie über einen anderen Bruchstrich hinweg (sonst zerfallen verschachtelte Brüche)
        for ids, nach_oben in ((zaehler, True), (nenner, False)):
            while True:
                rand = min(stuecke[i][1] for i in ids) if nach_oben else max(stuecke[i][3] for i in ids)
                dazu = []
                for i in frei:
                    if i in zaehler or i in nenner:
                        continue
                    oben, unten = (stuecke[i][3], rand) if nach_oben else (rand, stuecke[i][1])
                    if 0 <= unten - oben <= 6 and not any(
                            t is not s and oben - 1 <= t.y0 <= unten + 1
                            and t.x0 < stuecke[i][2] and t.x1 > stuecke[i][0] for t in im_clip):
                        dazu.append(i)
                if not dazu:
                    break
                ids += dazu
        if " ".join(stuecke[i][4] for i in sorted(nenner, key=lambda i: (stuecke[i][1], stuecke[i][0]))).startswith("="):
            continue                                    # „– Kosten / = Ergebnis“: Summenstrich eines Rechenschemas

        def teil(ids):
            tokens = [(stuecke[i][0], stuecke[i][2], (stuecke[i][1] + stuecke[i][3]) / 2,
                       stuecke[i][4], stuecke[i][5]) for i in ids]
            zeilen = _zeilen(tokens)
            return " ".join(_zeilen_text(tokens)), " ".join(_zeile_latex(z) for z in zeilen)

        (zt, zl), (nt, nl) = teil(zaehler), teil(nenner)
        ids = zaehler + nenner
        stuecke.append([s.x0, min(stuecke[i][1] for i in ids), s.x1, max(stuecke[i][3] for i in ids),
                        f"({zt}) / ({nt})", rf"\frac{{{zl}}}{{{nl}}}"])
        benutzt.update(ids)
    rest = [st for i, st in enumerate(stuecke) if i not in benutzt]
    tokens = []
    for st in rest:
        y = (st[1] + st[3]) / 2
        if st[5] is not None:       # Bruch in die Textzeile setzen, die auf seiner Höhe links/rechts daneben steht
            daneben = [(w[1] + w[3]) / 2 for w in rest if w[5] is None and st[1] <= (w[1] + w[3]) / 2 <= st[3]
                       and (w[2] <= st[0] + 1 or w[0] >= st[2] - 1)]
            y = min(daneben, key=lambda d: abs(d - y), default=y)
        tokens.append((st[0], st[2], y, st[4], st[5]))
    return "\n".join(_zeile_latex(z) for z in _zeilen(tokens)), treffer


def formel_md(page, rect, bilder, striche) -> str:
    """Formel als Bild (sieht aus wie im Heft) + LaTeX-Fassung (VS-Code-Vorschau, Suche, Claude)."""
    clip = (rect + (-2, -2, 2, 2)) & page.rect
    link = bilder.speichern(page, clip, minimum=6)
    text, _ = formel_text(page, clip, striche)
    teile = [f"![Formel Seite {page.number + 1}]({link})"] if link else []
    teile += [f"$$\n{z}\n$$" for z in text.splitlines() if z.strip()]
    return "\n\n".join(teile) + "\n\n" if teile else ""


def dollar_escapen(md: str) -> str:
    """Ein einzelnes „$“ würde die Vorschau als Mathe deuten – außerhalb der $$-Formelblöcke escapen."""
    zeilen, im_block = md.split("\n"), False
    for i, z in enumerate(zeilen):
        if z == "$$":
            im_block = not im_block
        elif not im_block:
            zeilen[i] = re.sub(r"(?<!\\)\$", r"\\$", z)
    return "\n".join(zeilen)


def vektor_cluster(page):
    try:
        cluster = page.cluster_drawings()
    except Exception:
        return []
    seite = abs(page.rect)
    return [r for r in cluster if abs(r) < 0.8 * seite]   # Seitenrahmen/Hintergründe ignorieren


def seite_aufbauen(page, chunk, bilder: BildSpeicher, hinweise: list) -> str:
    nr = page.number + 1
    roh = page.get_text().strip()

    # Seite ohne Textebene: Scan oder reine Grafik -> ganze Seite als Bild
    if not roh:
        hat_inhalt = bool(page.get_images()) or bool(page.get_drawings())
        if not hat_inhalt:
            return "_(leere Seite)_\n"
        link = bilder.speichern(page, None, ganze_seite=True)
        hinweise.append(f"Seite {nr}: keine Textebene (Scan?) – als Bild eingebettet, Text nicht durchsuchbar.")
        return f"> **Hinweis:** Diese Seite enthält keinen auslesbaren Text (vermutlich ein Scan).\n\n![Seite {nr}]({link})\n"

    text = chunk.get("text", "") if chunk else ""
    boxen = chunk.get("page_boxes") if chunk else None
    if not boxen:                                   # Fallback ohne Layout-Infos
        return text or roh

    tabellen = [pymupdf.Rect(b["bbox"]) for b in boxen if b["class"] == "table"]
    alle_boxen = [pymupdf.Rect(b["bbox"]) + (-2, -2, 2, 2) for b in boxen]
    cluster = [c for c in vektor_cluster(page) if not any(c.intersects(t) for t in tabellen)]
    benutzt = set()

    def grafik_md(rects, txt=""):
        rects = merge_rects(rects, MERGE_ABSTAND_PT)
        # Vektor-Teile (Achsen, Beschriftungslinien ...) zur Grafik dazunehmen
        for i, c in enumerate(cluster):
            if any((r + (-MERGE_ABSTAND_PT, -MERGE_ABSTAND_PT, MERGE_ABSTAND_PT, MERGE_ABSTAND_PT)).intersects(c) for r in rects):
                rects.append(c)
                benutzt.add(i)
        teile = []
        for r in merge_rects(rects, MERGE_ABSTAND_PT):
            link = bilder.speichern(page, r)
            if link:
                teile.append(f"![Grafik Seite {nr}]({link})")
        # Text, der in der Grafik steckt: unsichtbar für die Vorschau, lesbar für Claude
        txt = re.sub(r"(<!--|-{3,})?\s*(Start|End) of picture text\s*(-->|-{3,})?|<br>", " ", txt, flags=re.I)
        txt = re.sub(r"[*_#|`]+", " ", txt)
        txt = re.sub(r"\s+", " ", txt).replace("--", "–").strip()
        if txt:
            teile.append(f"<!-- Bildtext: {txt} -->")
        return "\n\n".join(teile) + "\n\n" if teile else ""

    teile, bild_lauf, lauf_text = [], [], []
    woerter = None                      # Wörter der PDF-Seite, nur bei Tabellen benötigt
    striche = None                      # mögliche Bruchstriche, nur bei Formeln benötigt

    def lauf_abschliessen():
        if bild_lauf:
            teile.append(("grafik", grafik_md(bild_lauf, "\n".join(lauf_text))))
            bild_lauf.clear()
            lauf_text.clear()

    for b in boxen:
        stueck = text[b["pos"][0]:b["pos"][1]]
        if b["class"] == "picture":
            rect = pymupdf.Rect(b["bbox"])
            if not zu_klein(rect):
                bild_lauf.append(rect)
            lauf_text.append(stueck)
            continue
        lauf_abschliessen()
        if b["class"] in ("page-header", "page-footer") and not KOPF_FUSSZEILEN:
            continue
        if b["class"] == "table":
            woerter = woerter or seiten_woerter(page)
            # erst Silbentrennungen und unlesbare Zeichen reparieren – sonst stehen zerschnittene
            # Wortteile nicht auf gleicher Höhe („Verkehrs-<br>mittel“) bzw. sind nicht erkennbar („Pr|��eis“)
            stueck = zeichen_reparieren(trennungen_aufloesen(stueck))[0]
            schnitte = max((tabelle_zerschnitten(z, woerter) for z in stueck.splitlines()), default=0)
            if schnitte and schnitte < 3:   # einzelne Wörter (meist Kopfzeile) -> an Ort und Stelle flicken
                stueck = tabelle_flicken(stueck, woerter)
            # ganze Textspalte zerschnitten oder nach dem Flicken noch Wortstümpfe -> Bild + Fließtext
            if schnitte >= 3 or tabelle_stuempfe(stueck, woerter):
                stueck = tabelle_retten(page, pymupdf.Rect(b["bbox"]), bilder, hinweise, woerter)
        elif b["class"] == "formula" or (b["class"] in ("text", "list-item") and "=" in stueck):
            # Formeln: die Layout-KI liefert für „formula“ gar keinen Text, in Textboxen wird ein Bruch
            # zu „A ⋅100 = 1 890 ⋅100 = 69,31 % B 2 727“ zerwürfelt -> Bild + Text mit echten Brüchen
            striche = _bruchstriche(page) if striche is None else striche
            rect = pymupdf.Rect(b["bbox"])
            if b["class"] == "formula" or formel_text(page, rect + (-2, -2, 2, 2), striche)[1]:
                stueck = formel_md(page, rect, bilder, striche)
        teile.append((b["class"], stueck, pymupdf.Rect(b["bbox"])))
    lauf_abschliessen()

    # freistehende Vektorgrafiken, die das Layout nicht als Bild erkannt hat
    for i, c in enumerate(cluster):
        if i in benutzt or zu_klein(c, MIN_VEKTOR_PT) or any(c.intersects(bx) for bx in alle_boxen):
            continue
        md = grafik_md([c])
        pos = next((k for k, t in enumerate(teile) if len(t) == 3 and t[2].y0 >= c.y0), len(teile))
        teile.insert(pos, ("grafik", md))

    return dollar_escapen("".join(t[1] for t in teile))


# ---------------------------------------------------------------- Qualitätsprüfung
_PRUEFWORT = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}|\d{2,}")


def _seiten_bloecke(page) -> list[str]:
    """Textblöcke der PDF-Seite, Zeilen nach derselben Regel gebildet wie im Konverter
    (sich berührende Textstücke ohne Leerzeichen: „Umsatzren|tabilität“ -> ein Wort)."""
    bloecke = collections.defaultdict(list)
    for w in page.get_text("words"):
        bloecke[w[5]].append((w[0], w[2], (w[1] + w[3]) / 2, w[4]))
    return ["\n".join(_zeilen_text(tokens)) for _, tokens in sorted(bloecke.items())]


def _zaehlen(text: str) -> collections.Counter:
    return collections.Counter(w.lower() for w in _PRUEFWORT.findall(text))


def vollstaendigkeit(doc, seiten_md: list) -> tuple[float, list]:
    """Unabhängige Gegenprobe: Jedes Wort/jede Zahl der PDF-Textebene muss in der .md stehen.
    Bewusst weggelassene Kopf-/Fußzeilen (kurze Blöcke, die auf >= 4 Seiten wiederkehren) zählen nicht.
    Rückgabe: (Prozent gefunden, [(Seite, Anzahl fehlend, Beispielwörter), …])"""
    bloecke = [_seiten_bloecke(p) for p in doc]
    norm = lambda t: re.sub(r"[\d\s]+", " ", t).strip().lower()
    wiederkehrend = set()
    if not KOPF_FUSSZEILEN:
        haeufig = collections.Counter(n for bl in bloecke for n in {norm(b) for b in bl if len(b) < 120})
        wiederkehrend = {n for n, k in haeufig.items() if k >= 4}
    pdf = []
    for bl in bloecke:
        text = "\n".join(b for b in bl if norm(b) not in wiederkehrend)
        text = re.sub(r"(\w)[-­]\s*\n\s*(\w)", r"\1\2", text)          # Silbentrennung
        pdf.append(_zaehlen(zeichen_reparieren(text)[0]))
    md = [_zaehlen(re.sub(r"\]\([^)]*\)|<br>", " ", m)) for m in seiten_md]

    def fehlend(soll, ist):
        fehlt = soll - ist
        for w in list(fehlt):   # von der Reparatur ergänzter Doppelbuchstabe („kontrole“ -> „kontrolle“)
            if any(w[:k] + w[k] + w[k:] in ist for k in range(len(w))):
                del fehlt[w]
        return fehlt

    probleme = []
    for i, soll in enumerate(pdf):
        # Nachbarseiten mitzählen: über den Seitenumbruch gerutschter Text ist kein Verlust
        fenster = md[max(0, i - 1)] + md[i] + (md[i + 1] if i + 1 < len(md) else collections.Counter())
        fehlt = fehlend(soll, fenster)
        n, m = sum(fehlt.values()), sum(soll.values())
        if n >= 8 and n >= 0.1 * m:
            probleme.append((i + 1, n, [w for w, _ in fehlt.most_common(5)]))
    soll_gesamt, ist_gesamt = sum(pdf, collections.Counter()), sum(md, collections.Counter())
    n_soll = sum(soll_gesamt.values())
    prozent = 100.0 if not n_soll else 100 * (1 - sum(fehlend(soll_gesamt, ist_gesamt).values()) / n_soll)
    return prozent, probleme


# ---------------------------------------------------------------- Konvertierung
def pdf_oeffnen(pfad: Path, passwort_fragen):
    try:
        doc = pymupdf.open(pfad)
    except Exception as e:
        raise RuntimeError(f"Datei beschädigt oder keine gültige PDF ({type(e).__name__}).") from e
    pw = None
    if doc.needs_pass:
        for versuch in range(3):
            pw = passwort_fragen(pfad.name, versuch)
            if pw is None:
                raise RuntimeError("Abgebrochen: kein Passwort eingegeben.")
            if doc.authenticate(pw):
                break
        else:
            raise RuntimeError("Falsches Passwort (3 Versuche).")
    if not doc.is_pdf:
        raise RuntimeError("Die Datei ist keine PDF.")
    if doc.page_count == 0:
        raise RuntimeError("Die PDF enthält keine Seiten.")
    return doc, pw


def chunks_erzeugen(doc, hinweise, fortschritt=False):
    opts = dict(page_chunks=True, use_ocr=False, show_progress=fortschritt,
                header=KOPF_FUSSZEILEN, footer=KOPF_FUSSZEILEN)
    try:
        return pymupdf4llm.to_markdown(doc, **opts)
    except Exception as e:
        hinweise.append(f"Gesamtkonvertierung fehlgeschlagen ({e}) – Seite für Seite weiter.")
    chunks = []
    for i in range(doc.page_count):
        try:
            chunks.append(pymupdf4llm.to_markdown(doc, pages=[i], **{**opts, "show_progress": False})[0])
        except Exception as e:
            hinweise.append(f"Seite {i + 1}: Layout-Analyse fehlgeschlagen ({e}) – nur Rohtext.")
            chunks.append(None)
    return chunks


def ausgabe_ordner(pdf: Path, eltern: Path) -> Path:
    """Ordner für eine PDF; kürzt den Namen, damit Windows' 260-Zeichen-Grenze nicht reißt."""
    basis = sicherer_name(pdf.stem)
    platz = 225 - len(str(eltern)) - len("/images/seite000_bild000.png")  # Reserve für Bilddateien
    platz = max(12, platz // 2)                                           # Name steckt 2x im .md-Pfad
    return eltern / (basis[:platz].strip(" .") or "pdf")


def zielordner_bestimmen(pdf: Path, eltern: Path, ueberschreiben_fragen, reserviert=frozenset()) -> Path | None:
    ziel = ausgabe_ordner(pdf, eltern)
    if ziel in reserviert:          # zwei PDFs ergeben denselben Ordnernamen (z. B. „a?.pdf“ / „a_.pdf“)
        antwort = False
    elif ziel.exists():
        antwort = ueberschreiben_fragen(ziel)
        if antwort is None:
            return None
    else:
        antwort = True
    if antwort:
        (ziel / f"{ziel.name}.md").unlink(missing_ok=True)
        shutil.rmtree(ziel / "images", ignore_errors=True)
    else:
        n = 2
        while (kandidat := ziel.with_name(f"{ziel.name}_{n}")).exists() or kandidat in reserviert:
            n += 1
        ziel = kandidat
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def ist_aktuell(pdf: Path, eltern: Path) -> bool:
    """True, wenn die .md schon existiert und neuer als die PDF ist (Ordner-Modus: überspringen)."""
    ziel = ausgabe_ordner(pdf, eltern)
    md = ziel / f"{ziel.name}.md"
    return md.is_file() and md.stat().st_mtime >= pdf.stat().st_mtime


def pdfs_im_ordner(ordner: Path) -> list[Path]:
    """Alle PDFs rekursiv (Groß-/Kleinschreibung egal), ohne den eigenen output-Ordner."""
    gefunden = []
    for p in ordner.rglob("*"):
        try:
            if p.suffix.lower() == ".pdf" and p.is_file() and OUTPUT_ROOT not in p.resolve().parents:
                gefunden.append(p)
        except OSError:
            continue  # z. B. kaputte Verknüpfung / keine Rechte
    return sorted(gefunden, key=lambda p: [s.lower() for s in p.relative_to(ordner).parts])


def index_schreiben(ordner_ausgabe: Path, quelle: Path, fehler: list):
    """Inhaltsverzeichnis aller .md-Dateien im gespiegelten Ordner (praktisch für Claude)."""
    zeilen = [f"# {quelle.name}", "", f"Quelle: `{quelle}`  ",
              f"Stand: {datetime.now():%Y-%m-%d %H:%M}", ""]
    aktueller = None
    for md in sorted(aufteilen.volltexte(ordner_ausgabe), key=lambda p: [s.lower() for s in p.parts]):
        rel = md.relative_to(ordner_ausgabe)
        gruppe = "/".join(rel.parts[:-2]) or "(Hauptordner)"
        if gruppe != aktueller:
            zeilen += ["", f"## {gruppe}", ""]
            aktueller = gruppe
        # Heft mit allen vorhandenen Teilen: Volltext · Lerntext · Aufgaben · Lösungen · Zusammenfassung
        links = [f"[{md.stem}](<{rel.as_posix()}>)"]
        for teil in ("Lerntext", "Aufgaben", "Lösungen", "Zusammenfassung"):
            if (md.parent / f"{md.stem} - {teil}.md").is_file():
                links.append(f"[{teil}](<{(rel.parent / f'{md.stem} - {teil}.md').as_posix()}>)")
        kopf = md.read_text(encoding="utf-8")[:600]
        if m := re.search(r'^vollstaendigkeit: "([^"]+)"', kopf, re.M):
            pruefen = len(re.findall(r"– bitte prüfen\.", md.read_text(encoding="utf-8")[:20000]))
            links.append(f"Vollständigkeit {m.group(1)}" + (f" ⚠ {pruefen} Seite(n) prüfen" if pruefen else ""))
        zeilen.append("- " + " · ".join(links))
    if fehler:
        zeilen += ["", "## Nicht konvertiert", ""] + [f"- {f}" for f in fehler]
    (ordner_ausgabe / "_index.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def vorbereiten(pdf: Path, eltern: Path, passwort_fragen, ueberschreiben_fragen, reserviert: set) -> dict | None:
    """Hauptprozess: PDF prüfen und alle Rückfragen stellen, bevor parallel umgewandelt wird."""
    if not pdf.is_file():
        raise RuntimeError("Datei nicht gefunden.")
    doc, passwort = pdf_oeffnen(pdf, passwort_fragen)
    seiten = doc.page_count
    doc.close()
    ziel = zielordner_bestimmen(pdf, eltern, ueberschreiben_fragen, reserviert)
    if ziel is None:
        return None
    reserviert.add(ziel)
    return {"pdf": pdf, "passwort": passwort, "ziel": ziel, "seiten": seiten}


def prozess_anzahl(auftraege: int, wunsch: int = 0) -> int:
    """Parallele Prozesse: begrenzt durch Kerne (2 bleiben frei) und freien Arbeitsspeicher."""
    if wunsch > 0:
        return min(wunsch, auftraege)
    kerne = os.cpu_count() or 1
    try:
        import psutil
        frei_gb = psutil.virtual_memory().available / 1024 ** 3
    except Exception:
        frei_gb = 4.0
    return max(1, min(auftraege, kerne - 2, int(frei_gb // RAM_PRO_PROZESS_GB)))


def _job(job: dict) -> dict:
    """Läuft im Worker-Prozess (muss auf Modulebene stehen, damit Windows ihn starten kann)."""
    print(f"  … läuft: {job['anzeige']} ({job['seiten']} S.)", flush=True)
    return umwandeln(job["pdf"], job["passwort"], job["ziel"])


def alle_umwandeln(jobs: list, prozesse: int):
    """Liefert (job, ergebnis oder Exception) in der Reihenfolge, in der sie fertig werden."""
    if prozesse <= 1:
        for job in jobs:
            try:
                yield job, umwandeln(job["pdf"], job["passwort"], job["ziel"], fortschritt=True)
            except Exception as e:
                yield job, e
        return

    # Kerne aufteilen: viele parallele PDFs -> je 1 Thread, wenige -> bis zu KI_THREADS
    kerne = os.cpu_count() or 1
    os.environ[_THREADS_ENV] = str(max(1, min(KI_THREADS, (kerne - 2) // prozesse)))
    nochmal = []
    pool = ProcessPoolExecutor(max_workers=prozesse)
    try:
        # große PDFs zuerst, damit am Ende nicht eine dicke PDF allein läuft
        futures = {pool.submit(_job, j): j for j in sorted(jobs, key=lambda j: -j["seiten"])}
        for f in as_completed(futures):
            try:
                yield futures[f], f.result()
            except BrokenProcessPool:
                nochmal.append(futures[f])
            except Exception as e:
                yield futures[f], e
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # Stürzt ein Prozess hart ab (defekte PDF), reißt er alle laufenden Aufträge mit:
    # diese einzeln und isoliert wiederholen, damit nur die schuldige PDF scheitert.
    for job in nochmal:
        with ProcessPoolExecutor(max_workers=1) as einzel:
            try:
                yield job, einzel.submit(_job, job).result()
            except BrokenProcessPool:
                yield job, RuntimeError("Verarbeitung abgestürzt – PDF vermutlich fehlerhaft.")
            except Exception as e:
                yield job, e


def umwandeln(pdf: Path, passwort: str | None, ziel: Path, fortschritt: bool = False) -> dict:
    start = time.perf_counter()
    hinweise = []
    doc, _ = pdf_oeffnen(pdf, lambda name, versuch: passwort if versuch == 0 else None)

    bilder = BildSpeicher(ziel / "images")
    chunks = chunks_erzeugen(doc, hinweise, fortschritt)
    if len(chunks) != doc.page_count:               # sollte nie passieren – dann sicher zuordnen
        chunks = (list(chunks) + [None] * doc.page_count)[:doc.page_count]

    seiten_md, alle_annots, repariert = [], [], 0
    for i, page in enumerate(doc):
        try:
            md = seite_aufbauen(page, chunks[i], bilder, hinweise)
        except Exception as e:
            hinweise.append(f"Seite {i + 1}: Fehler beim Aufbau ({e}) – nur Rohtext.")
            md = page.get_text()
        md, n = zeichen_reparieren(trennungen_aufloesen(md))
        repariert += n
        annots = annotationen_lesen(page)
        for a in annots:
            if a["inline"] and a["text"]:
                md, a["im_text"] = inline_markieren(md, a["text"], a["inline"])
        if annots:
            alle_annots.append((i + 1, annots))
        seiten_md.append(f"<!-- Seite {i + 1} -->\n\n{md.strip()}\n")

    # Gegenprobe: steht jedes Wort der PDF auch in der .md?
    try:
        prozent, probleme = vollstaendigkeit(doc, seiten_md)
    except Exception as e:
        prozent, probleme = None, []
        hinweise.append(f"Vollständigkeitsprüfung fehlgeschlagen ({e}).")
    for nr, n, beispiele in probleme:
        hinweise.append(f"Seite {nr}: {n} Wörter der PDF fehlen in der .md (z. B. {', '.join(beispiele)}) – bitte prüfen.")

    titel = (doc.metadata or {}).get("title", "").strip() or pdf.stem
    kopf = ["---", f'quelle: "{pdf.name}"', f'titel: "{titel.replace(chr(34), chr(39))}"',
            f"seiten: {doc.page_count}", f"konvertiert: {datetime.now():%Y-%m-%d %H:%M}"]
    if prozent is not None:
        kopf.append(f'vollstaendigkeit: "{prozent:.2f} %"'.replace(".", ","))
    kopf += ["---", ""]
    if hinweise:
        kopf += ["> **Konvertierungshinweise:**"] + [f"> - {h}" for h in hinweise] + [""]

    fuss = []
    if alle_annots:
        fuss = ["", "---", "", "## Markierungen & Kommentare", ""]
        for nr, annots in alle_annots:
            fuss.append(f"### Seite {nr}")
            for a in annots:
                zeile = f"- **{a['art']}:**"
                if a["text"]:
                    zeile += f" „{a['text']}“"
                if a["kommentar"]:
                    zeile += f" — Kommentar: {a['kommentar']}" if a["text"] else f" {a['kommentar']}"
                fuss.append(zeile)
            fuss.append("")

    md_datei = ziel / f"{ziel.name}.md"
    inhalt = "\n".join(kopf) + "\n" + "\n".join(seiten_md) + "\n".join(fuss)
    inhalt = re.sub(r"\n{4,}", "\n\n\n", inhalt)
    md_datei.write_text(inhalt, encoding="utf-8")
    anzahl_annots = sum(len(a) for _, a in alle_annots)
    doc.close()

    # Aufteilen in Aufgaben / Lösungen / Lerntext (Fehler dabei kosten nicht den Volltext)
    try:
        teile = aufteilen.statistik(aufteilen.aufteilen(md_datei))
    except Exception as e:
        teile = f"Aufteilen fehlgeschlagen: {e}"
    return {"md": md_datei, "ordner": ziel, "seiten": len(seiten_md), "bilder": bilder.anzahl,
            "teile": teile, "repariert": repariert, "vollstaendigkeit": prozent, "problemseiten": len(probleme),
            "markierungen": anzahl_annots, "hinweise": hinweise, "dauer": time.perf_counter() - start}


# ---------------------------------------------------------------- Oberfläche
def main():
    for strom in (sys.stdout, sys.stderr):      # Umlaute/Sonderzeichen dürfen nie zum Absturz führen
        try:
            strom.reconfigure(errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="PDF -> Markdown")
    parser.add_argument("pdfs", nargs="*", help="PDF-Datei(en) oder \"<PDF-Ordner>\"; ohne Angabe öffnet sich ein Dialog")
    parser.add_argument("--overwrite", action="store_true", help="vorhandene Ausgabe überschreiben")
    parser.add_argument("--nogui", action="store_true", help="keine Dialoge, nur Konsole")
    parser.add_argument("-j", "--prozesse", type=int, default=MAX_PROZESSE,
                        help="gleichzeitig verarbeitete PDFs (0 = automatisch)")
    parser.add_argument("--index", action="store_true", help="nur _index.md von \"<PDF-Ordner>\" neu schreiben")
    args = parser.parse_args()

    if args.index:
        if not args.pdfs:
            parser.error('--index braucht den Quellordner, z. B.: python pdf2md.py --index "<PDF-Ordner>"')
        for p in map(Path, args.pdfs):
            basis = OUTPUT_ROOT / sicherer_name(p.resolve().name or "Laufwerk")
            if not basis.is_dir():
                print(f"Kein Ausgabeordner „{basis}“ – „{p}“ wurde noch nicht umgewandelt.")
                continue
            index_schreiben(basis, p, [])
            print(f"Index neu geschrieben: {basis / '_index.md'}")
        return

    tk = root = None
    try:
        if args.nogui:
            raise RuntimeError
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
    except Exception:
        tk = None   # kein GUI verfügbar -> Konsole

    pfade = [Path(p) for p in args.pdfs]
    if not pfade:
        if not tk:
            parser.error("Keine PDF/Ordner angegeben und kein Dialog verfügbar.")
        modus = messagebox.askyesnocancel(
            "PDF → Markdown", "Was möchtest du konvertieren?\n\n"
            "Ja = einzelne PDF(s) auswählen\nNein = ganzen Ordner (inkl. Unterordner)", parent=root)
        if modus is None:
            return
        if modus:
            auswahl = filedialog.askopenfilenames(parent=root, title="PDF(s) auswählen",
                                                  filetypes=[("PDF-Dateien", "*.pdf"), ("Alle Dateien", "*.*")])
            pfade = [Path(p) for p in auswahl]
        else:
            ordner = filedialog.askdirectory(parent=root, title="Ordner mit PDFs auswählen", mustexist=True)
            pfade = [Path(ordner)] if ordner else []
        if not pfade:
            print("Nichts ausgewählt.")
            return

    # Aufträge: (pdf, Eltern-Ordner der Ausgabe, Quellordner oder None)
    auftraege, ordner_jobs = [], []
    for p in pfade:
        if p.is_dir():
            basis = OUTPUT_ROOT / sicherer_name(p.resolve().name or "Laufwerk")
            ordner_jobs.append((p, basis))
            gefunden = pdfs_im_ordner(p)
            print(f"Ordner „{p}“: {len(gefunden)} PDF(s) gefunden.")
            for pdf in gefunden:
                rel = pdf.relative_to(p).parent.parts
                auftraege.append((pdf, basis.joinpath(*(sicherer_name(t, 40) for t in rel)), p))
        else:
            auftraege.append((p, OUTPUT_ROOT, None))
    if not auftraege:
        print("Keine PDFs gefunden.")
        if tk:
            messagebox.showinfo("PDF → Markdown", "Keine PDFs gefunden.", parent=root)
        return

    def passwort_fragen(name, versuch):
        frage = f"„{name}“ ist passwortgeschützt." + ("\nFalsches Passwort, nochmal:" if versuch else "")
        if tk:
            return simpledialog.askstring("Passwort", frage, show="*", parent=root)
        import getpass
        return getpass.getpass(frage + " Passwort: ") or None

    def ueberschreiben_fragen(ordner):
        if args.overwrite:
            return True
        if tk:
            return messagebox.askyesnocancel(
                "Ausgabe existiert", f"„{ordner.name}“ existiert bereits.\n\n"
                "Ja = überschreiben\nNein = neuen Ordner anlegen\nAbbrechen = diese PDF überspringen",
                parent=root)
        return False  # Konsole: nie stillschweigend überschreiben -> neuer Ordner

    # Phase 1: prüfen + alle Rückfragen (Passwort, Überschreiben) vorab – danach läuft alles ohne Unterbrechung
    jobs, fehler, uebersprungen, reserviert = [], [], 0, set()
    for pdf, eltern, quelle in auftraege:
        anzeige = str(pdf.relative_to(quelle)) if quelle else pdf.name
        try:
            # Ordner-Modus: unveränderte PDFs überspringen, geänderte ohne Rückfrage neu erzeugen
            if quelle and not args.overwrite and pdf.is_file() and ist_aktuell(pdf, eltern):
                print(f"Bereits aktuell – übersprungen: {anzeige}")
                uebersprungen += 1
                continue
            job = vorbereiten(pdf, eltern, passwort_fragen,
                              (lambda o: True) if quelle else ueberschreiben_fragen, reserviert)
            if job is None:
                print(f"Übersprungen: {anzeige}")
                continue
            job.update(anzeige=anzeige, quelle=quelle)
            jobs.append(job)
        except Exception as e:
            print(f"FEHLER: {anzeige}: {e}")
            fehler.append((quelle, f"{anzeige}: {e}"))

    # Phase 2: umwandeln, mehrere PDFs gleichzeitig
    ergebnisse = []
    if jobs:
        prozesse = prozess_anzahl(len(jobs), args.prozesse)
        print(f"\n{len(jobs)} PDF(s) mit {sum(j['seiten'] for j in jobs)} Seiten, "
              f"{prozesse} gleichzeitig …\n")
        start = time.perf_counter()
        try:
            for n, (job, r) in enumerate(alle_umwandeln(jobs, prozesse), 1):
                kopf = f"[{n}/{len(jobs)}] {job['anzeige']}"
                if isinstance(r, Exception):
                    print(f"{kopf}: FEHLER: {r}")
                    if not isinstance(r, RuntimeError):
                        traceback.print_exception(r)
                    fehler.append((job["quelle"], f"{job['anzeige']}: {r}"))
                    continue
                print(f"{kopf}: OK – {r['seiten']} S., {r['bilder']} Bilder, "
                      f"{r['markierungen']} Markierungen ({r['dauer']:.0f} s)")
                if r["vollstaendigkeit"] is not None:
                    status = "✔" if not r["problemseiten"] else f"⚠ {r['problemseiten']} Seite(n) prüfen"
                    print(f"    Vollständigkeit: {r['vollstaendigkeit']:.2f} % der PDF-Wörter enthalten {status}")
                print(f"    Aufteilung: {r['teile']}")
                if r["repariert"]:
                    print(f"    {r['repariert']} unlesbare Zeichen ersetzt (Tausendertrenner, Leerzeichen, Ligaturen)")
                for h in r["hinweise"]:
                    print(f"    Hinweis: {h}")
                ergebnisse.append(r)
        except KeyboardInterrupt:
            print("\nAbgebrochen. Fertige PDFs bleiben erhalten, der nächste Ordner-Lauf macht beim Rest weiter.")
        print(f"\nGesamtdauer: {time.perf_counter() - start:.0f} s")

    for quelle, basis in ordner_jobs:
        if basis.exists():
            index_schreiben(basis, quelle, [t for q, t in fehler if q == quelle])
            print(f"\nInhaltsverzeichnis: {basis / '_index.md'}")

    zusammenfassung = f"{len(ergebnisse)} konvertiert, {uebersprungen} übersprungen, {len(fehler)} Fehler"
    print(f"\n{zusammenfassung}")
    if tk:
        zeilen = [f"✔ {r['md'].name} ({r['seiten']} S., {r['bilder']} Bilder, "
                  f"{r['markierungen']} Markierungen)" for r in ergebnisse]
        if len(zeilen) > 12:
            zeilen = zeilen[:12] + [f"… und {len(zeilen) - 12} weitere"]
        text = zusammenfassung + "\n\n" + "\n".join(zeilen)
        if fehler:
            text += "\n\nFehler:\n" + "\n".join(t for _, t in fehler[:10]) + ("\n…" if len(fehler) > 10 else "")
        if ergebnisse or uebersprungen:
            if messagebox.askyesno("Fertig", text + "\n\nAusgabeordner öffnen?", parent=root):
                if ordner_jobs:
                    os.startfile(ordner_jobs[0][1])
                else:
                    os.startfile(ergebnisse[-1]["ordner"] if len(ergebnisse) == 1 else OUTPUT_ROOT)
        else:
            messagebox.showerror("Fehler", text, parent=root)
        root.destroy()


if __name__ == "__main__":
    main()
