---
description: Erzeugt aus "<Heft> - Lerntext.md" eine geprüfte "<Heft> - Zusammenfassung.md" (ein Heft, ein Ordner oder alle)
argument-hint: "[Heftname | Ordner | alle] [--neu]"
---

# /zusammenfassen

Argumente: `$ARGUMENTS`

Erzeuge für Hefte unter `output/` je eine Zusammenfassung aus dem bereinigten Lerntext. Halte dich genau an die folgenden Schritte.

## 1. Auswahl

- Kandidaten sind alle Dateien `* - Lerntext.md` unter `output/` (rekursiv).
- Argument leer oder `alle` → alle Kandidaten. Ein Heftname (z. B. `ABC01`) → nur `ABC01 - Lerntext.md`. Ein Ordner → nur die Lerntexte darunter.
- Übersprungen wird ein Heft, wenn daneben schon eine `<X> - Zusammenfassung.md` liegt, die **neuer** ist als der Lerntext. Mit `--neu` wird sie trotzdem neu erzeugt.
- Gesetzestexte haben keinen Lerntext und fallen damit automatisch heraus.
- Passt das Argument auf kein Heft: melden und aufhören.
- Ermittle die Auswahl nur über Dateinamen und Änderungszeiten (z. B. mit Glob oder `ls`). **Lies die Lerntexte nicht selbst.**

## 2. Pro Heft ein Subagent

- Starte pro Heft einen Subagent vom Typ `general-purpose`, **höchstens 3 gleichzeitig**.
- Gib ihm den absoluten Pfad des Lerntexts, den Zielpfad `<X> - Zusammenfassung.md` im selben Ordner, das heutige Datum und die **REGELN unten vollständig und wörtlich** mit.
- Der Subagent schreibt die Datei selbst. Er meldet die letzte `<!-- Seite N -->` des Lerntexts zurück und „unzuverlässige Formeln: S. …“ oder „unzuverlässige Formeln: keine“.
- Sammle diese Formel-Meldungen aller Hefte für die Abschlussliste.

## 3. Prüfen

- Nach jedem Heft: `python tools/zusammenfassung_pruefen.py "<Heft-Ordner>"`.
- Bei ✘ bekommt derselbe Subagent die Fehlerliste **genau einmal** zum Korrigieren (per SendMessage, sonst ein neuer Subagent mit Regeln + Fehlerliste + Hinweis, die vorhandene Datei zu korrigieren). Danach wird nur noch geprüft und berichtet, nicht weiter korrigiert.

## 4. Abschluss

- Für jeden betroffenen Ordner `output/<Ordner>/`: Lies in `output/<Ordner>/_index.md` die Zeile ``Quelle: `…` `` und führe `python pdf2md.py --nogui --index "<Quelle>"` aus. Damit verlinkt der Index die neuen Zusammenfassungen.
- Gib am Ende eine Tabelle aus: `Heft | Status | Länge in % | Zahlen ✔/✘ | Fettbegriff-Warnungen | unplausible Seiten in %` (Status: erstellt / korrigiert / übersprungen / Fehler; Werte aus der Kopfzeile des Prüfskripts).
- Danach eine eigene Liste „Unzuverlässige Formeln“: Heft + Seiten, aus den Meldungen der Subagents.

## 5. Grenzen

- Verändere keine anderen Dateien als die Zusammenfassungen und (über `--index`) die `_index.md`.

---

## REGELN für den Subagent

1. **Komplett lesen:** Lies den Lerntext vollständig, in Abschnitten (z. B. je 400 Zeilen), bis zur letzten Zeile. Nenne zur Kontrolle die letzte `<!-- Seite N -->`.
2. **Nur der Lerntext zählt:** Kein Fremdwissen, keine eigenen Beispiele. Definitionen exakt übernehmen. Zahlen nur übernehmen, wenn sie genau so im Lerntext stehen (nichts ausrechnen, runden oder umformulieren). Keine Aufgaben, keine Übungen, keine Lösungen, keine Literatur oder Quellen. Sprache Deutsch.
3. **Seitenangaben:** Hinter jede Aussage gehört `(S. N)`. Fasst eine Aussage mehrere Stellen zusammen, auch `(S. N, S. M)`. Jede Seite muss die sein, auf der dieser Inhalt im Lerntext steht, also die nächstgelegene **vorausgehende** `<!-- Seite N -->` vor der jeweiligen Stelle. Nur Seitenzahlen verwenden, die als `<!-- Seite N -->` im Lerntext stehen.
4. **Formeln:** Die Textfassung (die „> “-Zeilen unter einem Formelbild) nur übernehmen, wenn sie lesbar und mathematisch plausibel ist, dann exakt. Andernfalls das zugehörige Formelbild aus dem Lerntext verlinken, mit genau dem Pfad aus dem Lerntext, z. B. `![Formel S. N](images/<datei>.png) (Textfassung im Heft unzuverlässig) (S. N)`. Melde am Ende „unzuverlässige Formeln: S. …“ oder „unzuverlässige Formeln: keine“.
5. **Umfang:** etwa 10–15 % der Zeichenzahl des Lerntexts, Stil Lernzettel (knappe Stichpunkte, keine Fließtext-Absätze).
6. **Format** (leere Unterabschnitte weglassen, keine weiteren Überschriften außer den hier genannten):

   ```
   ---
   quelle: "<Wert von quelle aus dem Lerntext-Kopf>"
   titel: "<Wert von titel aus dem Lerntext-Kopf>"
   teil: "Zusammenfassung"
   grundlage: "<X> - Lerntext.md"
   erstellt: "<JJJJ-MM-TT>"
   ---

   # <X> – Zusammenfassung

   > Überblick über das ganze Heft in 3–5 Sätzen.

   ## <Nr> <Kapiteltitel>
   ### Kernaussagen
   - Stichpunkt (S. N)
   ### Definitionen
   - **Definition N – Begriff:** vollständiger Inhalt der Definition (S. N)
   ### Formeln
   > Textfassung exakt wie in den „> “-Zeilen des Lerntexts (S. N)
   ![Formel S. N](images/<datei>.png) (Textfassung im Heft unzuverlässig) (S. N)
   ### Merke
   - Merksatz oder Hinweis (S. N)

   ## Wichtige Begriffe
   - **Begriff:** kurze Erklärung (S. N)
   ```

   - Jedes Hauptkapitel des Lerntexts (z. B. `**1 …**`, `**2 …**`) bekommt einen eigenen `## <Nr> <Kapiteltitel>`-Abschnitt, mit derselben Nummer und in derselben Reihenfolge wie im Lerntext. Unterkapitel werden in die Stichpunkte ihres Hauptkapitels eingearbeitet.
   - Inhalte ohne nummeriertes Kapitel (Einleitung, Anhang wie Glossar) fließen in den Überblick, in „Wichtige Begriffe“ oder in das passende Kapitel ein.
   - **Definitionen:** Jede nummerierte Definition („Definition 1.2“) des Lerntexts erscheint vollständig, im Format `**Definition N – Begriff:**`.
   - **Wichtige Begriffe:** Glossar-Einträge und fett gedruckte Fachbegriffe, alphabetisch sortiert, je eine kurze Erklärung aus dem Lerntext.
   - Überschriften dürfen die Wörter Übung, Aufgabe, Lösung, Literatur oder Quellen nicht enthalten.
7. **Ausgabe:** `<X> - Zusammenfassung.md` im Ordner des Lerntexts, UTF-8. Keine anderen Dateien anlegen oder ändern.
