---
description: Erzeugt aus "<Heft> - Lerntext.md" ein geprüftes Lernskript "<Heft> - Zusammenfassung.md" (ein Heft, ein Ordner oder alle)
argument-hint: "[Heftname | Ordner | alle] [--neu]"
---

# /zusammenfassen

Argumente: `$ARGUMENTS`

Erzeuge für Hefte unter `output/` je ein Lernskript aus dem bereinigten Lerntext. Halte dich genau an die folgenden Schritte.

## 1. Auswahl

- Kandidaten sind alle Dateien `* - Lerntext.md` unter `output/` (rekursiv).
- Argument leer oder `alle` → alle Kandidaten. Ein Heftname (z. B. `ABC01`) → nur `ABC01 - Lerntext.md`. Ein Ordner → nur die Lerntexte darunter.
- Übersprungen wird ein Heft nur, wenn daneben eine `<X> - Zusammenfassung.md` liegt, die **neuer** ist als der Lerntext **und** in ihrem YAML-Kopf `art: "Lernskript"` steht. Ältere Zusammenfassungen (ohne diese Zeile) werden also neu erzeugt. Mit `--neu` wird immer neu erzeugt.
- Gesetzestexte haben keinen Lerntext und fallen damit automatisch heraus.
- Passt das Argument auf kein Heft: melden und aufhören.
- Ermittle die Auswahl nur über Dateinamen, Änderungszeiten und die ersten Zeilen vorhandener Zusammenfassungen (z. B. mit Glob, `ls`, `head`). **Lies die Lerntexte nicht selbst.**

## 2. Pro Heft ein Subagent

- Starte pro Heft einen Subagent vom Typ `general-purpose`, **höchstens 3 gleichzeitig**. Wird einer fertig, startet das nächste Heft.
- Gib ihm den absoluten Pfad des Lerntexts, den Zielpfad `<X> - Zusammenfassung.md` im selben Ordner, das heutige Datum und die **REGELN unten vollständig und wörtlich** mit.
- Der Subagent schreibt die Datei selbst und liefert die Abschlussmeldung aus Regel 9.
- Sammle die gemeldeten „nicht rekonstruierbaren Formeln“ aller Hefte für die Abschlussliste.

## 3. Prüfen

- Nach jedem Heft: `python tools/zusammenfassung_pruefen.py "<Heft-Ordner>"`.
- Bei ✘ bekommt derselbe Subagent die Fehlerliste **genau einmal** zum Korrigieren (per SendMessage, sonst ein neuer Subagent mit Regeln + Fehlerliste + Hinweis, die vorhandene Datei zu korrigieren), zusammen mit Regel 10. Danach wird nur noch geprüft und berichtet, nicht weiter korrigiert.

## 4. Abschluss

- Für jeden betroffenen Ordner `output/<Ordner>/`: Lies in `output/<Ordner>/_index.md` die Zeile ``Quelle: `…` `` und führe `python pdf2md.py --nogui --index "<Quelle>"` aus. Damit verlinkt der Index die neuen Lernskripte.
- Gib am Ende eine Tabelle aus: `Heft | Status | Länge in % (vor/nach Korrektur) | Zahlen ✔/✘ | Fettbegriff-Warnungen | unplausible Abschnitte in % | Formeln | Grafiken | Selbstcheck-Fragen` (Status: erstellt / korrigiert / übersprungen / Fehler; Werte aus der Kopfzeile des Prüfskripts).
- Danach eigene Listen aus den Meldungen der Subagents: „Nicht rekonstruierbare Formeln“, „Stellen nach Originalseite“, „Widersprüche im Heft“ und „ausgelassene Stellen“ (jeweils Heft + Seite).

## 5. Grenzen

- Verändere keine anderen Dateien als die Zusammenfassungen und (über `--index`) die `_index.md`.

---

## REGELN für den Subagent

1. **Komplett lesen:** Lies den Lerntext vollständig, in Abschnitten (z. B. je 400 Zeilen), bis zur letzten Zeile. Nenne zur Kontrolle die letzte `<!-- Seite N -->`.
2. **Nur der Lerntext zählt:** Kein Fremdwissen. Zahlen, Definitionen und Rechenwege exakt aus dem Heft (nichts selbst ausrechnen, runden oder umformulieren). **Zahlen nur, wenn sie im Text des Lerntexts stehen**; Zahlen, die nur in einer Grafik zu sehen sind, in Worten beschreiben. **Erklären ist ausdrücklich erwünscht:** in eigenen, klaren Worten, so dass man das Thema **ohne das Heft** versteht – aber inhaltlich nichts hinzuerfinden. Keine Aufgaben oder Lösungen aus dem Heft, keine Literatur oder Quellen. Sprache Deutsch.
   - **Keine eigene Lesart:** Ist eine Stelle im Lerntext unverständlich oder durcheinander (Tabelle, Beispiel, Formel, Formelbild passt nicht zum Text), lies die Originalseite der PDF mit dem Read-Tool (Parameter `pages`). Den PDF-Pfad findest du so: Quellordner aus der Zeile ``Quelle: `…` `` in `output/<Ordner>/_index.md`, darin die Datei aus `quelle:` im YAML-Kopf des Lerntexts (notfalls rekursiv nach dem Dateinamen suchen). Gib die Stelle korrekt wieder und schreib „(nach Originalseite S. x)“ dazu. Ist die PDF nicht auffindbar: Stelle auslassen und in der Abschlussmeldung nennen.
   - **Widersprüche im Heft** offen vermerken, nicht selbst auflösen: `> **Hinweis:** Im Heft widersprüchlich: … (S. x, S. y)`.
3. **Formeln:** `$$`-Blöcke **nur für Formeln, die im Heft stehen** (als Formelbild oder als Text). **Keine allgemeinen Formeln aus Rechenbeispielen ableiten**; ein Rechenbeispiel wird so gezeigt, wie es im Heft steht. Öffne zu jeder Formel das Formelbild (Read-Tool auf die PNG im Ordner `images/`) und schreib die Formel als korrektes LaTeX in einen eigenen Block: `$$` allein in einer Zeile, darunter die Formel, darunter wieder `$$` allein in einer Zeile. Die LaTeX-Fassung im Lerntext ist nur ein Entwurf – maßgeblich ist das Bild. Darunter: „Dabei ist:“ mit der Bedeutung jeder Größe, dann **Rechenbeispiel aus dem Heft** Schritt für Schritt mit den Zahlen des Hefts (falls das Heft eines hat). Lässt sich eine Formel auch mit Bild und Originalseite nicht sicher lesen, binde das Bild ein (`![Formel S. N](images/<datei>.png)`) und melde sie als nicht rekonstruierbar. `\frac`, `\text` usw. nur innerhalb von `$$`-Blöcken.
4. **Grafiken:** Binde die Abbildungen ein, die zum Verständnis nötig sind (Kurven, Schemata, Übersichten), mit `![Abb. …](images/<datei>.png)` – genau der Dateiname aus dem Lerntext. Sieh dir die PNG vorher an. Darunter 1–2 Sätze, was die Grafik zeigt und worauf man achten muss. Deko-Bilder und Logos weglassen.
5. **Tabellen:** Vergleiche und Gegenüberstellungen als Markdown-Tabelle.
6. **Umfang:** etwa 25–35 % der Zeichenzahl des Lerntexts. Das ist ein **Richtwert, kein Muss**: lieber vollständig erklären als kürzen.
7. **Format** (leere Teile weglassen):

   ```
   ---
   quelle: "<Wert von quelle aus dem Lerntext-Kopf>"
   titel: "<Wert von titel aus dem Lerntext-Kopf>"
   teil: "Zusammenfassung"
   art: "Lernskript"
   grundlage: "<X> - Lerntext.md"
   erstellt: "<JJJJ-MM-TT>"
   ---

   # <X> – Lernskript

   > Worum geht es? 3–5 Sätze. Dazu die Lernziele des Hefts, falls vorhanden.

   ## <N> <Kapiteltitel>

   ### <N.M> <Unterkapiteltitel> (S. a–b)

   Erklärung als zusammenhängender Text (3–10 Sätze): Was ist das, warum ist es so, wie hängt es mit dem Vorherigen zusammen. Fachbegriffe beim ersten Auftreten **fett**.

   > **Definition N.M – Begriff:** Wortlaut aus dem Heft

   **Formel**

   $$
   <LaTeX>
   $$

   Dabei ist: …

   **Rechenbeispiel aus dem Heft:** …

   **Beispiel aus dem Heft:** kurz und konkret

   ![Abb. …](images/<datei>.png)
   Was die Grafik zeigt und worauf man achten muss.

   | Tabelle | wo passend |
   |---|---|

   > **Merke:** 1–2 Kernsätze

   #### <N.M.K> <Titel>        (jedes Unter-Unterkapitel des Lerntexts, gleiche Bausteine wie oben)

   #### Das Wichtigste aus Kapitel N
   3–5 Sätze Rückblick.

   #### Selbstcheck
   <details><summary>Frage</summary>Antwort, nur aus dem Heft (S. x)</details>

   ## Wichtige Begriffe

   | Begriff | Bedeutung | Seite |
   |---|---|---|
   | … | … | S. 12 |
   ```

   - **Gliederung:** **Jedes** Kapitel, Unterkapitel und Unter-Unterkapitel des Lerntexts bekommt eine eigene Überschrift: `## <N> <Titel>`, `### <N.M> <Titel> (S. a–b)`, `#### <N.M.K> <Titel>` (tiefere Ebenen `##### <N.M.K.L> <Titel>`) – Nummer und Titel **exakt wie im Lerntext**, gleiche Reihenfolge. **Nie umbenennen, zusammenlegen oder weglassen**, auch nicht, wenn der Titel Wörter wie „Aufgaben“ oder „Übungen“ enthält. `a–b` sind die Seiten des Unterkapitels laut `<!-- Seite N -->` im Lerntext (bei einer Seite `(S. a)`). Nur Seiten verwenden, die als `<!-- Seite N -->` im Lerntext stehen.
   - **Seitenangaben** immer mit „S.“ vor jeder Seite, z. B. „S. 53, S. 84“.
   - Inhalte ohne nummeriertes Kapitel (Einleitung, Anhang wie Glossar) fließen in den Überblick, in „Wichtige Begriffe“ oder in das passende Kapitel ein.
   - **Definitionen:** Jede nummerierte Definition („Definition 1.2“) des Lerntexts erscheint im Wortlaut, im Format `**Definition N.M – Begriff:**`.
   - **Selbstcheck:** pro Hauptkapitel 3–5 Verständnisfragen zum Inhalt (keine Aufgaben aus dem Heft), je als eine `<details>`-Zeile; die Antwort nur aus dem Heft, mit Seitenangabe.
   - **Wichtige Begriffe:** Glossar-Einträge und fett gedruckte Fachbegriffe, alphabetisch, Seite als „S. N“.
   - **Überschriften** dürfen die Wörter Übung, Aufgabe, Lösung, Literatur oder Quellen nicht enthalten. Einzige Ausnahme: Ein Kapitel (beliebiger Tiefe) heißt im Lerntext selbst so – dann Nummer und Titel genau wie im Lerntext.
8. **Ausgabe:** `<X> - Zusammenfassung.md` im Ordner des Lerntexts, UTF-8. Keine anderen Dateien anlegen oder ändern (Hilfsskripte nur im Scratchpad).
9. **Abschlussmeldung:** letzte gelesene Seite, Länge in % des Lerntexts (vor und nach einer Korrekturrunde), Anzahl Formeln, Anzahl eingebundener Grafiken, „nicht rekonstruierbare Formeln: S. …“ oder „keine“, Stellen „nach Originalseite“ (S. …), Widersprüche im Heft (S. …), ausgelassene Stellen (S. …).
10. **Korrekturrunde:** Behebe **nur** die ✘-Punkte des Prüfskripts. Nicht kürzen, nicht umformulieren, keine Überschriften entfernen. Kürzen nur, wenn die Länge über 45 % liegt.
