# pdf2md

Wandelt PDFs in Markdown um, inklusive Grafiken, Tabellen, Markierungen und Kommentaren.

## Einrichtung (einmalig)

```bash
python -m pip install -r requirements.txt
```

## Benutzung

| Wie | Was passiert |
|---|---|
| `start.bat` doppelklicken | Frage: einzelne PDF(s) **oder** ganzen Ordner wählen |
| PDF(s) oder Ordner auf `start.bat` ziehen | direkt konvertieren |
| `python pdf2md.py "<PDF-Ordner>"` | Ordner per Konsole |
| `--overwrite` | alles neu erzeugen |
| `--nogui` | keine Dialoge |
| `-j 4` | höchstens 4 PDFs gleichzeitig (Standard: automatisch) |
| `python pdf2md.py --index "<PDF-Ordner>"` | nur `_index.md` neu schreiben, ohne Umwandlung |

## Wo landet was?

**Einzelne PDF:**
```
output\<PDF-Name>\<PDF-Name>.md
output\<PDF-Name>\images\seite002_bild01.png
```

**Ordner** (Unterordner werden gespiegelt):
```
output\<Name des PDF-Ordners>\_index.md          ← Inhaltsverzeichnis aller Hefte
output\<Name des PDF-Ordners>\01 Grundlagen\Heft 1\Heft 1.md
output\<Name des PDF-Ordners>\01 Grundlagen\Heft 1\images\...
```

## Aufteilung pro Heft

Nach jeder Umwandlung entstehen neben `<Heft>.md` (Volltext) automatisch:

| Datei | Inhalt |
|---|---|
| `<Heft> - Lerntext.md` | Kapiteltext inkl. Beispiele, Definitionen, Kapitel-Zusammenfassungen, Glossar |
| `<Heft> - Aufgaben.md` | Übungen im Text, Aufgaben zur Selbstüberprüfung, Übungsfälle, Einsendeaufgabe |
| `<Heft> - Lösungen.md` | Lösungs- und Bearbeitungshinweise aus dem Anhang |

Verworfen werden Titelseiten sowie Inhalts-, Literatur-, Abbildungs-, Tabellen-, Abkürzungs- und Sachwortverzeichnis. Reine Aufgaben- und Lösungshefte (Titel „Aufgabenheft“/„Lösungsheft“) landen komplett in Aufgaben bzw. Lösungen. **Gesetzestexte** (viele Zeilen beginnen mit „§ 12“) bleiben unverändert: Für sie gibt es nur den Volltext. In Aufgaben und Lösungen stehen Kapitelüberschriften und `<!-- Seite N -->` zur Orientierung. `_index.md` verlinkt pro Heft alle Teile.

Ohne Neu-Umwandlung erneut aufteilen (z. B. nachdem die Regeln angepasst wurden):
```bash
python aufteilen.py
```
Die Regeln stehen oben in `aufteilen.py` und sind auf typische deutschsprachige Lehrhefte abgestimmt (Übungen im Text, „Aufgaben zur Selbstüberprüfung“, Lösungen im Anhang, „Aufgabenheft“/„Lösungsheft“). Andere Hefte landen im Zweifel komplett im Lerntext.

Gesamtprüfung aller Ergebnisse gegen die Original-PDFs (z. B. nach Änderungen am Code):
```bash
python tools\endpruefung.py "<PDF-Ordner>"
```
Sie prüft unter anderem, dass alle Formelblöcke gültig sind (gerade Anzahl `$$`, Klammern ausgeglichen, kein LaTeX außerhalb der Blöcke).

## Zusammenfassung pro Heft

Die Zusammenfassung erzeugt Claude Code aus dem Lerntext, über das eigene Claude-Abo (kein API-Key):

```
/zusammenfassen              alle Hefte unter output, vorhandene werden übersprungen
/zusammenfassen ABC01        nur dieses Heft
/zusammenfassen alle --neu   alle neu erzeugen
```

Ergebnis ist `<Heft> - Zusammenfassung.md` neben dem Lerntext: ein **Lernskript**, mit dem man das Thema ohne das Heft verstehen kann. Pro Unterkapitel (z. B. `### 1.2 Angebot und Nachfrage (S. 12–14)`) gibt es eine Erklärung in ganzen Sätzen, Definitionen im Wortlaut, Formeln als LaTeX mit Erklärung der Größen und dem Rechenbeispiel aus dem Heft, die nötigen Grafiken mit Erläuterung, Tabellen für Vergleiche und Merksätze. Jedes Kapitel endet mit einem Rückblick und einem Selbstcheck (Fragen zum Aufklappen), am Ende steht eine Begriffstabelle. Inhalte kommen nur aus dem Heft; Aufgaben, Lösungen und Literatur gehören nicht hinein. Der Befehl steht in `.claude/commands/zusammenfassen.md`. Ältere Zusammenfassungen ohne `art: "Lernskript"` im Kopf werden beim nächsten Aufruf neu erzeugt.

Jedes Lernskript wird automatisch geprüft: alle Kapitel und Unterkapitel mit gültigen Seitenangaben, alle Definitionen, jede Zahl steht im Heft, LaTeX und Bildlinks in Ordnung, keine Aufgaben/Lösungen, Länge 25–35 % des Lerntexts. Die Prüfung lässt sich auch einzeln starten und listet am Ende die Hefte ohne Zusammenfassung:
```bash
python tools\zusammenfassung_pruefen.py
```

## Verhalten

- **Markierungen** (Textmarker, Unterstreichung) werden im Text **fett** gesetzt, Durchgestrichenes als ~~durchgestrichen~~. Am Ende jeder .md steht zusätzlich eine Liste „Markierungen & Kommentare“ je Seite, inklusive Notizen.
- **Grafiken:** Eingebettete Bilder **und** gezeichnete Diagramme werden als PNG gespeichert. Zerstückelte Diagramm-Teile werden zu einem Bild zusammengefasst. Mini-Icons und Linien werden ignoriert, doppelte Bilder nur einmal gespeichert.
- **Seitenmarker:** `<!-- Seite N -->` ist in der Vorschau unsichtbar, aber Claude kann damit Seitenzahlen zuordnen.
- **Qualitätsprüfung:** Nach jeder Umwandlung wird geprüft, ob jedes Wort und jede Zahl aus der Textebene der PDF auch in der `.md` steht. Kopf- und Fußzeilen werden dabei nicht mitgezählt. Das Ergebnis steht in der Konsole, im Kopf der `.md` (`vollstaendigkeit: "99,81 %"`) und in `_index.md`. Seiten mit Lücken werden oben in der `.md` gemeldet („Seite 47: … – bitte prüfen“).
- **Formeln:** Formeln werden als Bild übernommen und zusätzlich als LaTeX-Block mit echten Brüchen, z. B. `$$ \text{Quote} = \frac{\text{Wert A} \cdot 100}{\text{Wert B}} $$` (in der .md stehen die `$$` jeweils allein in einer Zeile). In VS Code zeigt die Vorschau (**Strg+Shift+V**, oder Strg+K V für die Vorschau daneben) die Formeln als echte Formeln. Verschachtelte Brüche werden erkannt; Rechenschemata mit Summenstrich („– Kosten / = Ergebnis“) bleiben Zeilen. Maßgeblich bleibt das Bild. Ohne diesen Schritt würde die Layout-KI Formeln komplett weglassen.
- **Tabellen:** Manchmal legt die Layout-KI Spaltengrenzen mitten durch Wörter („Fen|ster“). Einzelne betroffene Wörter werden an Ort und Stelle zusammengesetzt. Ist eine ganze Textspalte zerschnitten, wird die Tabelle als Bild plus Fließtext übernommen, und die `.md` vermerkt das. Silbentrennungen in Zellen werden zusammengezogen.
- **Unlesbare Zeichen** („�“, wenn die Schrift in der PDF kein Text-Mapping hat) werden ersetzt: Tausendertrenner und feste Leerzeichen durch Leerzeichen, Office-Ligaturen (ti, ft, fb) durch Buchstaben, Platzhalterlinien durch `______`.
- **Scan-Seiten** ohne Textebene werden als ganzes Bild eingebettet und oben in der .md als Hinweis vermerkt (kein OCR).
- **Bereits vorhanden:** Bei einzelnen PDFs wird gefragt (überschreiben / neuer Ordner / überspringen). Im Ordner-Modus werden unveränderte PDFs übersprungen und geänderte neu erzeugt.
- **Parallel:** Mehrere PDFs werden gleichzeitig umgewandelt, große zuerst. Alle Rückfragen (Passwort, Überschreiben) kommen vorher gesammelt, danach läuft alles ohne Unterbrechung. Die Anzahl richtet sich automatisch nach CPU-Kernen und freiem Arbeitsspeicher (`MAX_PROZESSE` oben im Script oder `-j`). Die Layout-KI wird dabei auf wenige Threads begrenzt (`KI_THREADS`), denn ungebremst belegt sie alle Kerne und ist trotzdem langsamer. Gemessen mit 12 PDFs à 20 Seiten: 81 s vorher, 7,5 s jetzt, bei identischem Ergebnis.
- **Abbrechen** mit Strg+C: Fertige PDFs bleiben erhalten, der nächste Ordner-Lauf macht beim Rest weiter.
- **Fehler** (defekte PDF, falsches Passwort) stoppen nicht den ganzen Lauf. Sie werden am Ende und in `_index.md` aufgelistet.

Einstellungen (Bildauflösung, Mindestgröße, Kopf-/Fußzeilen, Markierungsstil) stehen oben in `pdf2md.py`.

**Hinweis für Claude:** Wenn Claude die Grafiken sehen soll, lade die Bilder aus `images\` zusammen mit der .md hoch oder gib Claude den ganzen Ordner.
