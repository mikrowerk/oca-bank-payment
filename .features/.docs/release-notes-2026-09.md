# Release Notes September 2026 — oca-bank-payment (Fork mikrowerk)

**Odoo-Version:** 17 · **Zeitraum:** Juli bis September 2026 · **Stand:** 2026-09-02
**Branch:** `feature/TOM-102-early-payment-for-sepa-credit-transfers`

Diese Release Notes beschreiben die Änderungen im Fork `mikrowerk/oca-bank-payment` seit Juli 2026.
Grundlage sind die Spezifikation und der Umsetzungsplan unter `.features/.specs` und
`.features/.plans`, abgeglichen mit dem Code. Die Beschreibung richtet sich an Anwender der
Buchhaltung; ein Abschnitt am Ende fasst zusammen, was Administratoren beachten müssen.

Deutsche Bezeichnungen entsprechen der deutschen Odoo-Oberfläche (englisches Original in Klammern).
Das neue Modul selbst liegt noch ohne deutsche Übersetzung vor; seine Feldbezeichnungen erscheinen
daher englisch und sind unten entsprechend angegeben.

---

## Das Wichtigste in Kürze

- **Neues Modul „Account Payment Order Early Payment Discount"**: Skonto wird jetzt auch bei
  Zahlungen über Zahlungsaufträge und SEPA-Überweisungsdateien automatisch berücksichtigt. Bisher
  galt Skonto nur beim manuellen „Zahlung registrieren".
- Der Zahlungsbetrag wird beim Einfügen einer skontofähigen Lieferantenrechnung automatisch um den
  Skonto gekürzt, sofern die Skontofrist zum geplanten Ausführungsdatum eingehalten wird.
- Beim Erzeugen der Zahlung wird der Skonto automatisch ausgebucht, inklusive Steuerkorrektur. Die
  Rechnung ist danach vollständig ausgeglichen.
- **Neue SEPA-Zahlungsmodi**: Das Format **pain.001.001.09** ist jetzt der empfohlene Standard für
  SEPA-Überweisungen und wird beim Update automatisch aktiviert. Dazu kommt die neue Zahlungsmethode
  **„International Credit Transfer"** für Überweisungen außerhalb des SEPA-Raums.
- Dazu wurden die aktuellen Fehlerbehebungen und Verbesserungen aus dem OCA-Repository
  `bank-payment` (Branch 17.0) in den Fork übernommen.

---

## 1. Skonto in Zahlungsaufträgen

### 1.1 Ausgangslage

Odoo bietet auf Zahlungsbedingungen die Option **„Frühzahlerrabatt"** (Early Discount, Skonto) mit
Prozentsatz und Frist. Bisher wurde dieser Skonto nur angewendet, wenn eine Rechnung über den Assistenten
**„Zahlung registrieren"** bezahlt wurde. Wer Lieferantenrechnungen über **Zahlungsaufträge**
(Payment Order) und SEPA-Überweisungsdateien bezahlt, musste den Skonto bisher manuell abziehen und
nachbuchen. Das neue Modul schließt diese Lücke.

### 1.2 Automatische Skontokürzung

Wird eine Lieferantenrechnung in einen Zahlungsauftrag aufgenommen, sei es über die Aktion
**„Zum Zahlungsauftrag hinzufügen"** (Add to Payment Order) auf der Rechnung oder über den
Assistenten **„Zahlungszeilen aus Journalposten erstellen"** (Create Payment Lines from Journal
Items) im Zahlungsauftrag, prüft das System die Skontofähigkeit:

- Die Zahlungsbedingung der Rechnung gewährt Skonto, die Rechnung ist noch vollständig offen und die
  Skontofrist ist zum **Referenzdatum** noch nicht abgelaufen.
- Das Referenzdatum ergibt sich aus der Einstellung **„Ausführung zum"** (Payment Execution Date
  Type) des Zahlungsauftrags: bei festem Datum das geplante Datum, bei Fälligkeitsdatum das
  Fälligkeitsdatum der jeweiligen Rechnung, bei **„Sofort"** der heutige Tag.

Ist die Rechnung skontofähig, wird die Zahlungszeile mit dem **um den Skonto gekürzten Betrag**
angelegt. Nicht skontofähige Rechnungen, Gutschriften, teilbezahlte Rechnungen und Rechnungen mit
mehreren Raten werden wie bisher mit dem vollen Restbetrag übernommen.

### 1.3 Anzeige und manuelle Steuerung

In der Liste **„Zahlungszeilen"** (Payment Lines) des Zahlungsauftrags gibt es neue Spalten:

| Spalte | Bedeutung |
|---|---|
| **Discount Date** | Skontofrist der Rechnung |
| **Pay with Discount** | Schalter: Zeile wird mit Skonto bezahlt |

Im Formular einer Zahlungszeile erscheint zusätzlich **Amount with Discount**, der Zahlbetrag
nach Skontoabzug.

- Zeilen, die mit Skonto bezahlt werden, sind **grün** hervorgehoben.
- Zeilen, deren Skontofrist zum Referenzdatum bereits überschritten ist, die aber noch auf „mit
  Skonto" stehen, sind **gelb** hervorgehoben.
- Der Schalter **Pay with Discount** kann pro Zeile ein- und ausgeschaltet werden, solange der
  Zahlungsauftrag bearbeitbar ist. Beim Ausschalten springt der Betrag auf den vollen Restbetrag,
  beim Einschalten auf den Skontobetrag.
- Wird der Betrag einer Skontozeile **manuell geändert**, schaltet sich „Pay with Discount"
  automatisch aus, damit Zahlbetrag und Ausbuchung zusammenpassen.

### 1.4 Prüfung beim Bestätigen

Beim **Bestätigen** (Confirm) des Zahlungsauftrags werden alle Skontozeilen erneut geprüft. Ist der
Skonto inzwischen nicht mehr möglich, etwa weil das geplante Datum verschoben wurde oder die
Rechnung zwischenzeitlich teilbezahlt ist, wird die Zeile **automatisch auf den vollen Restbetrag
zurückgesetzt**. Der Auftrag wird nicht blockiert. Im **Chatter** des Zahlungsauftrags erscheint
eine Notiz mit den betroffenen Zeilen und dem alten und neuen Betrag:

> Early payment discount no longer available for the following payment lines. Amount has been
> reset to the full residual amount: …

Wird ein Zahlungsauftrag storniert und wieder auf Entwurf gesetzt, läuft die Prüfung beim nächsten
Bestätigen erneut.

### 1.5 Ausbuchung des Skontos

Beim Erzeugen der Zahlungen (Generate Payment File / Datei erzeugen) wird für jede Skontozeile der
Skonto automatisch ausgebucht:

- Die Bankbuchung enthält den **gekürzten** Betrag.
- Zusätzliche Buchungszeilen buchen den Skonto auf das Skontoertragskonto und korrigieren die
  Vorsteuer, genau so, wie es der Assistent „Zahlung registrieren" tut. Maßgeblich ist die
  Unternehmenseinstellung **„Steuerermäßigung durch Skonto"** (Cash Discount Tax Reduction:
  „Immer (auf Rechnung)", „Niemals", „Auf frühzeitige Zahlung").
- Die Lieferantenrechnung ist nach dem Hochladen der Datei **vollständig ausgeglichen** und steht
  auf „Bezahlt" bzw. „In Zahlung".
- Werden Skonto- und Nicht-Skonto-Rechnungen desselben Lieferanten zu einer Zahlung
  zusammengefasst, wird die Ausbuchung nur für die skontofähigen Rechnungen erzeugt.

### 1.6 SEPA-Datei

Die SEPA-Überweisungsdatei (pain.001) bleibt unverändert. Sie enthält den bereits gekürzten
Zahlbetrag; der Verwendungszweck verweist wie bisher auf die Rechnung.

### 1.7 Fremdwährung und Abgrenzung

Fremdwährungsrechnungen werden unterstützt; der Skonto wird in Rechnungswährung ermittelt.

Nicht enthalten:

- Lastschriften (SEPA Direct Debit, Einzugsaufträge): kein Skonto, Verhalten unverändert.
- Mehrstufiger Skonto (z. B. 3 % in 10 Tagen, 2 % in 20 Tagen) und Toleranztage.
- Ein Schalter je Zahlungsmodus, um die automatische Skontokürzung abzuschalten.

---

## 2. Übernommene Aktualisierungen aus OCA bank-payment 17.0

Am 2026-07-17 wurde der Stand des OCA-Repositories in den Fork übernommen. Für Anwender relevante
Änderungen:

- **Zahlungsauftrag**: Der Verwendungszweck erscheint jetzt auch dann im Bericht, wenn eine
  Zahlungszeile keinen Journalposten hat. Bei ausgehenden Zahlungen wird die Zahlungsreferenz der
  Rechnung als Verwendungszweck verwendet, wenn vorhanden. Ein Zahlungsauftrag, der bereits im
  Entwurf steht, löst beim erneuten „Auf Entwurf setzen" keinen Fehler mehr aus.
- **Zahlungsauftrag**: Benutzer mit Nur-Lese-Buchhaltungsrechten können Zahlungsaufträge lesen.
- **SEPA-Überweisung**: Fehlerbehebung in der Dateierzeugung. Neue Formate und Zahlungsmethoden
  siehe Abschnitt 3.
- **Zahlungspartner**: Neue Option, das Bankkonto des Partners auch ohne Zahlungsmodus beizubehalten.
- **SEPA-Mandate**: Die Bankkontoauswahl am Mandat filtert wieder korrekt; die Kontakt-Zuordnung am
  Mandat ist jetzt unternehmensabhängig; der Lastschrift-Bericht wird auch in anderen Sprachen als
  Englisch kompakt gedruckt.
- **Zahlungsauftrag-Rückläufer** (account_payment_order_return) ist auf Odoo 17 migriert.

Ob diese Module in der Produktivdatenbank installiert sind, ist je Modul zu prüfen; der Fork enthält
das gesamte OCA-Repository.

---

## 3. Neu unterstützte SEPA-Zahlungsmodi

Mit der Übernahme des OCA-Stands stehen für **Zahlungsmodi** (Payment Modes) und
**Zahlungsmethoden** (Payment Methods) unter Buchhaltung → Konfiguration neue Formate und eine neue
Zahlungsmethode zur Verfügung.

### 3.1 SEPA-Überweisung im Format pain.001.001.09

- Die Zahlungsmethode **„SEPA Credit Transfer to suppliers"** unterstützt zusätzlich das Format
  **pain.001.001.09**. Es ist jetzt als **empfohlen für Überweisungen** gekennzeichnet und entspricht
  den aktuellen Vorgaben des European Payments Council zur strukturierten Adresse. Ältere Formate
  (pain.001.001.03, .04, .05, pain.001.003.03) bleiben wählbar.
- **Automatische Umstellung beim Update**: Bestehende SEPA-Überweisungs-Zahlungsmethoden, die noch
  auf pain.001.001.03 stehen, werden beim Modul-Update auf pain.001.001.09 umgestellt, damit keine
  Dateien erzeugt werden, die Banken zurückweisen. Die Version kann danach wieder geändert werden,
  falls die Hausbank ein anderes Format verlangt.
- **Neues Feld „PAIN.001.001.09 Address Mode"** auf der Zahlungsmethode steuert, wie die
  Empfängeradresse in die Datei geschrieben wird:

| Adressmodus | Inhalt der Datei |
|---|---|
| **Minimal (City + Country only)** | nur Ort und Land (Standard, immer schemakonform) |
| **Hybrid (City/Country + AdrLine)** | Ort und Land, zusätzlich Straße und Postleitzahl des Empfängers, sofern hinterlegt |

  Der Adressmodus wirkt nur bei pain.001.001.09; ältere Formate sind nicht betroffen. Für den
  Hybridmodus müssen Straße, Ort und Land am Lieferanten gepflegt sein.

### 3.2 Neue Zahlungsmethode „International Credit Transfer"

- Das neue Modul `account_banking_international_credit_transfer` legt bei der Installation die
  Zahlungsmethode **„International Credit Transfer"** (Format pain.001.001.03) an. Sie ist für
  Überweisungen an Empfänger außerhalb des SEPA-Raums gedacht, etwa in Fremdwährung oder an Banken
  ohne IBAN-Pflicht.
- Einrichtung: unter Buchhaltung → Konfiguration → Zahlungsmodi einen eigenen Zahlungsmodus mit
  dieser Zahlungsmethode und dem Bankjournal anlegen. Zahlungsaufträge mit diesem Zahlungsmodus
  erzeugen eine pain.001-Datei nach den Implementierungsrichtlinien für internationale Überweisungen.
- Die Skontokürzung aus Abschnitt 1 greift auch für diese Zahlungsmethode, da sie auf der Ebene der
  Zahlungszeilen arbeitet.

### 3.3 SEPA-Lastschrift

Für Lastschriften bleiben die bisherigen Formate erhalten: pain.008.001.02 (empfohlen),
pain.008.001.03, pain.008.001.04 und pain.008.003.02 (Lastschrift in Deutschland). Der
Lastschrift-Bericht wird jetzt auch in anderen Sprachen als Englisch kompakt gedruckt.

---

## 4. Für Administratoren

### 4.1 Modul

| Modul | Version | Neu | Abhängigkeit |
|---|---|---|---|
| account_payment_order_early_payment_discount | 17.0.1.0.0 | ✓ | account_payment_order |
| account_banking_pain_base | 17.0.1.1.0 | | Adressmodus für pain.001.001.09 (OCA) |
| account_banking_sepa_credit_transfer | 17.0.1.1.1 | | Format pain.001.001.09, Migration der Zahlungsmethoden (OCA) |
| account_banking_international_credit_transfer | 17.0.1.0.0 | ✓ | Zahlungsmethode „International Credit Transfer" (OCA) |

Das Modul hängt bewusst nur von `account_payment_order` ab, nicht vom SEPA-Modul. Jede
Dateiausgabe, die auf Zahlungszeilen aufsetzt, profitiert damit automatisch. Es ist nicht
`auto_install` und muss explizit installiert werden:

```
.venv/bin/python ../odoo-17/odoo-bin -c odoo.conf -i account_payment_order_early_payment_discount --stop-after-init
```

Nach dem Update der SEPA-Module unter Buchhaltung → Konfiguration → Zahlungsmethoden prüfen:
PAIN-Version der SEPA-Überweisung (nach der Migration pain.001.001.09) und der neue Adressmodus
(Standard „Minimal"). Die Migration setzt `openupgradelib` voraus.

### 4.2 Voraussetzungen und Konfiguration

Das Modul selbst hat keine Einstellungen. Es nutzt die vorhandene Odoo-Konfiguration:

- **Zahlungsbedingung** mit aktiviertem **„Frühzahlerrabatt"** (Early Discount), Prozentsatz und Fristtagen,
  z. B. „2 % innerhalb 10 Tagen, netto 30".
- **Unternehmenseinstellung „Steuerermäßigung durch Skonto"** (Buchhaltung → Einstellungen), die
  festlegt, ob der Skonto die Steuer einschließt. Die Ausbuchung folgt dieser Einstellung.
- Skontoertrags- und Skontoaufwandskonto in den Buchhaltungseinstellungen (Odoo-Standard).

Die Skontokürzung ist in dieser Version **unbedingt aktiv** für alle skontofähigen Rechnungen. Ein
Opt-out je Zahlungsmodus ist als Ausbaustufe vorgesehen; Anwender können einzelne Zeilen über den
Schalter abwählen.

### 4.3 Stand der Umsetzung

- Der Code liegt auf dem Branch `feature/TOM-102-early-payment-for-sepa-credit-transfers` und ist
  noch **nicht** in `releases/17-candidate` zusammengeführt.
- Das Modul bringt 15 automatisierte Tests mit (Skontofähigkeit, Fristprüfung, Rücksetzung beim
  Bestätigen, manuelle Steuerung, Ausbuchung im Vergleich mit „Zahlung registrieren", alle drei
  Berechnungsmodi, gemischte Zahlungen, Gutschriften, Ratenzahlung, Fremdwährung, SEPA-Datei).
  Ergebnis des Prüflaufs vom 2026-09-02: siehe Abschnitt 4.4.
- Eine deutsche Übersetzung (`i18n/de.po`) liegt noch nicht vor.
- Das Modul ist als Beitrag an OCA/bank-payment vorgesehen (RFC-Issue und Pull Request stehen aus).
  Deshalb folgt es den OCA-Konventionen (Readme-Fragmente, pre-commit) und kapselt alle Zugriffe auf
  Odoo-Kernfunktionen in einer Adapterdatei, damit eine Portierung auf Odoo 18/19 nur diese Datei
  betrifft.
- Deinstallation ist gefahrlos: Die Felder sind additiv, ohne gesetzte Skontozeilen ändert das Modul
  kein Verhalten des Zahlungsauftrags.

### 4.4 Prüflauf

Testlauf am 2026-09-02 auf einer frischen Datenbank ohne Demo-Daten mit den Modulen
`account_payment_order_early_payment_discount` und `account_banking_sepa_credit_transfer`:

| Ergebnis | Wert |
|---|---|
| Tests | 15 |
| Fehlgeschlagen | 0 |
| Fehler | 0 |

Der SEPA-Test (T13) wurde ausgeführt, nicht übersprungen: Der Betrag in der pain.001-Datei entspricht
dem skontierten Zahlbetrag.
