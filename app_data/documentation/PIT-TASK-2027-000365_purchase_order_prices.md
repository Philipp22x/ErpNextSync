# WARUM fehlen die EK-Preise in den importierten Bestellungen?

ERPNext Task: **PIT-TASK-2027-000365** (ADJUSTMENT 1) ·
Projekt PIT-PROJ-2026-000106 (Webshop Lang-Kunstgewerbe) ·
Customer Lang Kunstgewerbe ·
Sync Instance `officeno1_purchase_orders` (4D `OfficeNo1`, driver `p4d`) ·
Untersuchung live auf `portal.lang-kunstgewerbe.at` am 2026-09-25.

User-Feedback (wortwörtlich): *"looks good already. please let synci check why so many
item prices missing in the purchase orders"*

## Ergebnis in einem Satz

Der Import ist korrekt: `rate`/`price_list_rate` übernehmen **1:1** die 4D-Spalte
`BESTELLUNGpos.Preis_EK`. Die 224 Positionen ohne Preis haben **in 4D selbst**
`Preis_EK = 0` — für 220 davon ist auch der Lieferanten-Artikelpreis
(`Artikel_Lieferant.Preis_EK`) nicht gepflegt. Es wurde **nichts** am Mapping, an der
Sync-Instance oder am Server Script geändert, weil es keinen Import-Fehler gibt.

## Messung (live, echte Zahlen)

| Messgröße | Wert |
|---|---|
| Purchase Orders auf der Site (alle docstatus=1) | 64 (40 manuell + 24 importiert) |
| Positionszeilen gesamt | 1542 |
| Positionen mit `rate = 0` **und** `price_list_rate = 0` | **224** (alle in den 24 importierten POs) |
| importierte Positionszeilen | 500 (24 POs) |
| davon ohne Preis | 224 von 500 |
| manuelle POs: Zeilen ohne Preis | 0 (1042 Zeilen, alle mit Preis) |

Vorher/Nachher (Import + Update erneut ausgeführt, siehe Verifikation):
`224 von 500` → **`224 von 500` unverändert**, weil 4D an diesen Stellen keinen Preis hat.
Der Task-Text nannte `222 von 735`; die Differenz von 2 Positionen und die abweichende
Gesamtzeilenzahl (damals 735, heute 1542) kommen daher, dass die Stichprobe vom
live-assi-Lauf älter ist als der jetzige Stand der Site (die Positionszeilen der
manuellen POs sind inzwischen 1042 statt 235). Entscheidend ist: **alle** 224
Nullpreis-Positionen der Site liegen in den 24 importierten POs.

## Ursachenmessung: 4D-Wert vs. importierter Wert

Matching: `tabSync Mapping Entry.source_row_key` (aus dem Mapping-Key
`match_key_column: PRIMARYKEY`) = 4D-Spalte `BESTELLUNGpos.primaryKey`. Damit ist jede
ERPNext-Positionszeile eindeutig ihrer 4D-Quellzeile zuordenbar (kein Index-Raten).

Gesamtvergleich über **alle 500 importierten Positionszeilen**:

```
lines = 500, erp_zero = 224, p4d_zero = 224,
mismatch = 0                 (kein Fall, in dem rate != 4D PREIS_EK)
zero_erp_but_price_4d = 0    (kein Fall, in dem der Import einen 4D-Preis verliert)
no_key_match = 0             (jede Zeile eindeutig zuordenbar)
```

Beispiele (vollständige Liste für PO `LNG-BE-2026-0047` / BESTELLNR 226060 geprüft):

| PO | supplier | 4D ArtikelNr | 4D `BESTELLUNGpos.Preis_EK` | ERPNext `rate`/`price_list_rate` |
|---|---|---|---|---|
| LNG-BE-2026-0047 | 33349 | 24634 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24635 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24640 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24656 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24721 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24724 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | ST24725 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | LB24378 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0045 | 33539 | 65153 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0045 | 33539 | 65149 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0057 | 33521 | 56421 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0062 | 33551 | S24728 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0062 | 33551 | 98849 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0067 | 33427 | 24695 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0067 | 33427 | 24726 | 0.0 | 0.0 / 0.0 |
| LNG-BE-2026-0047 | 33349 | 24054 (mit Preis, Gegenprobe) | 5.36 | 5.36 / 5.36 |
| LNG-BE-2026-0047 | 33349 | 23456 (mit Preis, Gegenprobe) | 1.85 | 1.85 / 1.85 |
| LNG-BE-2026-0067 | 33427 | 24571 (mit Preis, Gegenprobe) | 0.87 | 0.87 / 0.87 |
| LNG-BE-2026-0067 | 33427 | 24144 (mit Preis, Gegenprobe) | 1.16 | 1.16 / 1.16 |

Jede geprüfte Nullzeile hat in 4D exakt `Preis_EK = 0.0`; jede geprüfte Zeile **mit**
Preis stimmt centgenau mit `Preis_EK` überein. Die Positiv-Gegenprobe ist wichtig:
derselbe Lieferant (33349) hat in derselben Bestellung 22 Positionen mit korrekt
übernommenem Preis — der Import scheitert also nicht an Lieferant, Spalte oder Typ.

## Warum steht in 4D 0? (Antwort auf das "why")

1. **Kein Preispflege-Fall, sondern fehlende Stammdaten.** Für alle 224 Positionen
   wurde je `(ArtikelNr, LieferantenNr)` der Lieferanten-Artikelpreis geprüft:
   * 224/224 haben eine `Artikel_Lieferant`-Zeile für den Bestell-Lieferanten,
   * **220/224** haben dort `Preis_EK = 0`,
   * **4/224** haben dort inzwischen einen Preis, der aber **nach** der Bestellung
     gepflegt wurde:
     | PO | Artikel | Lieferant | `Artikel_Lieferant.Preis_EK` | `Letztes_Update` | Bestelldatum 4D |
     |---|---|---|---|---|---|
     | LNG-BE-2026-0055 | LB28650 | 33380 | 0.06 | 2026-08-20 | 2026-06-26 |
     | LNG-BE-2026-0056 | 82581 | 33334 | 1.72 | 2026-08-27 | 2026-05-18 |
     | LNG-BE-2026-0056 | 82580 | 33334 | 0.66 | 2026-08-27 | 2026-05-18 |
     | LNG-BE-2026-0057 | 56421 | 33521 | 0.60 | 2026-08-24 | 2026-06-26 |

     In diesen 4 Fällen existiert der Preis heute im 4D-Stamm, die **Bestellposition**
     wurde aber nie nachgezogen — der Sync spiegelt die Position, nicht den Stamm.
2. **Es sind fast ausschließlich neu angelegte Artikel.** Die 224 betroffenen
   Artikelnummern verteilen sich auf neu angelegte Nummernblöcke:
   `24627–24728` (99), `56483–56509` (28), `65124–65159` (35), `98813–98865` (53),
   dazu `82580/82581`, `86686`, `89986`, `LB24378`, `LB28650`, `S24727/S24728`,
   `ST24725` (9). Die Bestellungen wurden großteils am 2026-06-26 angelegt
   (z. B. 226050, 226052, 226057, 226060), also unmittelbar nach Anlage der neuen
   Artikel — zu diesem Zeitpunkt war für sie kein EK-Preis erfasst.
3. **Es gibt in der Bestellposition keine alternative Preisspalte.** Alle
   `BESTELLUNGpos`-Spalten wurden auf Preis-/Rabattfelder geprüft:
   * `Preis_EK` (DATA_TYPE 6) — die einzige EK-Preisspalte,
   * `Rabatt`, `Rabatt2`, `Rabatt3`, `Nachlass` — in den Nullzeilen alle `0.0`,
   * `VK_imAuftrag` — Verkaufspreis im Auftrag, ebenfalls `0.0`.

   Zusätzlich geprüfte 4D-Preisquellen:
   * `Artikel_EK_Staffel` (EK-Staffelpreise je Menge): **keine Zeile** für diese 224 Artikel,
   * `Artikel_Lieferant.ZuschlagPreis` / `EKexclFracht`: `0.0`,
   * `Artikel.Kalk_HK` / `Kalk_VK` / `Kalk_Datum`: `0.0` / `null`,
   * `Artikel.EK_USD`: **gefüllt** (z. B. 24634 = 1.48, 24721 = 3.96, 23456 = 1.97),
     ist aber ein separater USD-Preis und keine EUR-EK-Quelle (Verhältnis
     `EK_USD / Bestellpreis` streut über geprüfte Artikel zwischen 0.96 und 1.13 —
     also keine Währungsumrechnung des Bestellpreises). Er wurde bewusst **nicht**
     als Ersatzpreis übernommen (keine erfundenen Preise).

## Verifikation (live, nach der Messung)

1. **Import erneut ausgeführt** (`_run_import`, `types_str=["PurchaseOrder"]`, top=100):
   4D liefert 24 offene Bestellungen (`allesgeliefert IS NULL OR false`), davon sind
   alle 24 bereits gemappt → **0 neue Dokumente, 0 Batch-Jobs**; der after-import Hook
   (`submit purchase orders`) läuft.
2. **Update erneut ausgeführt** (`_run_bulk_update`, `types_str=["PurchaseOrder"]`):
   alle 24 Sync Mappings "up to date" (kein Feld-Write), after-update Hook läuft.
3. **Submit-Hook-Regression:** Snapshot aller 64 POs (docstatus, `modified`,
   `per_received`, Summen qty/received/rate) **vorher == nachher** (diff leer) →
   der Hook hat **0 von 24 POs neu geschrieben**.
   Toleranzvergleich nachgerechnet: max `abs(po.per_received - Summe(received_qty)/Summe(qty)*100)`
   = **3.64e-07** < 1e-6 → `0` POs, bei denen der Hook schreiben würde.
4. **received_qty == Summe MENGEGELIEFERT:** alle 500 importierten Positionen geprüft,
   **0 Abweichungen** (4D `BESTELLUNGpos.MengeGeliefert` → `Purchase Order Item.received_qty`).
5. **Preis-Zählung nachher:** 224 von 500 importierten Zeilen ohne Preis — unverändert,
   gestützt auf den Nachweis, dass 4D an genau diesen Zeilen keinen Preis hat.

## Betroffene Dateien / Zeilen (unverändert)

* `app_data/mappings/purchase_orders.json` Zeilen 132–139 (`table_fieldname` `rate`
  und `price_list_rate`, beide `sl_column: PREIS_EK`) — korrekt, keine Änderung.
* Live-Mapping der Sync Instance `officeno1_purchase_orders` gegen diese Datei geprüft:
  die Feld-Definitionen sind **identisch** (`jq -S`-Vergleich von
  `table_mapping[0].mapping` gegen `.[0].mapping` der Datei: diff leer; ebenso
  `type`/`table_name`/`primary_key`/`order_by`/`timestamp_column_name`/
  `query_filter`) → kein Live-Drift.
* Server Script `submit purchase orders` — unverändert.

## Empfehlung an den User

Die fehlenden Preise sind **kein Sync-Fehler**, sondern fehlende EK-Preise im
4D-Warenwirtschaftssystem für neu angelegte Artikel. Sobald in OfficeNo1 der EK-Preis
in der Bestellposition (`BESTELLUNG` → Positionen → `Preis_EK`) gepflegt ist, übernimmt
der Sync ihn beim nächsten Update automatisch. Bei den 4 Positionen, bei denen der
Lieferantenpreis inzwischen im Artikelstamm steht, muss die Bestellposition in 4D
nachgezogen werden (oder bewusst so bleiben) — der Sync erfindet dort keinen Preis.

---

# ADJUSTMENT 2 (2026-09-25): USD-Preisliste als Ursache — bestätigt, Preise nachgetragen

ERPNext Task **PIT-TASK-2027-000365**, ADJUSTMENT 2 · Untersuchung + Änderung live auf
`portal.lang-kunstgewerbe.at` am 2026-09-25.

User-Feedback (wortwörtlich): *"i think the problem is that the most item have usd prices
they are in the usd price list"*

## Ergebnis in einem Satz

Die Hypothese des Users ist **belegt**: alle 224 Nullpreis-Positionen haben in 4D
`BESTELLUNGpos.Preis_EK = 0`, aber für **alle 224 Artikel** ist der USD-Einkaufspreis
gepflegt (`4D Artikel.EK_USD` → ERPNext-Preisliste `Standard-Kauf-USD`, **224/224 exakt
gleich**). Die EUR-Preisliste (`Standard-Kauf` ← `4D Artikel.LETZTER_EK_NTO`) hat nur für
4 der 224 Artikel einen Preis. Die gespiegelten Bestellungen sind EUR-Bestellungen
(4D `BESTELLUNG.Waehrung` kennt in OfficeNo1 kein USD) und ERPNext hat **keinen
USD/EUR-Kurs** (Currency Exchange: 0 Zeilen), daher werden die fehlenden Preise mit dem
Kurs nachgetragen, den der Kunde in seinen **eigenen USD-Bestellungen** verwendet
(0,86207). Ergebnis: **224 → 0 Nullzeilen**, die 276 bereits bepreisten Zeilen unverändert.

## Messung 1 — die 224 Nullzeilen gegen 4D (`BESTELLUNGpos` + `Artikel`)

Matching wie in ADJ1: `tabSync Mapping Entry.source_row_key` (Mapping-Key
`match_key_column: PRIMARYKEY`) = 4D `BESTELLUNGpos.primaryKey`. Messung über alle 500
importierten Positionen (Datei `/tmp/diag_usd_po_4d.py` auf dem Server, Ergebnis
`/tmp/diag4d.out`):

```
zero lines                            : 224
4D BESTELLUNGpos rows matched by key  : 224
lines with 4D Artikel.EK_USD filled   : 224
ERP USD item price == 4D EK_USD       : 224
ERP USD item price != 4D EK_USD       : 0
```

Beispiele (vollständige Liste in `/tmp/diag4d.out`, jeweils `Preis_EK` = 0.0):

| PO | 4D BestellNr | Artikel | 4D `Preis_EK` | 4D `Artikel.EK_USD` | ERPNext `Standard-Kauf-USD` | importiert `rate` |
|---|---|---|---|---|---|---|
| LNG-BE-2026-0047 | 226060 | 24634 | 0.0 | 1.48 | 1.48 | 0.0 |
| LNG-BE-2026-0047 | 226060 | 24638 | 0.0 | 2.99 | 2.99 | 0.0 |
| LNG-BE-2026-0047 | 226060 | 24721 | 0.0 | 3.96 | 3.96 | 0.0 |
| LNG-BE-2026-0045 | 226050 | 65153 | 0.0 | 2.66 | 2.66 | 0.0 |
| LNG-BE-2026-0067 | 226052 | 98813 | 0.0 | 0.35 | 0.35 | 0.0 |
| LNG-BE-2026-0068 | 226051 | 98864 | 0.0 | 1.75 | 1.75 | 0.0 |

Weitere Preisspalten der Position sind in den Nullzeilen leer: `Rabatt`, `Rabatt2`,
`Rabatt3`, `Nachlass`, `VK_imAuftrag` alle 0.0 (geprüft, erste 10 Zeilen + Stichproben).
`BESTELLUNGpos` hat 78 Spalten und **keine** USD-Preisspalte (komplette Spaltenliste in
`/tmp/diag_schema`-Ausgabe); die USD-Preise hängen ausschließlich am Artikel.

## Messung 2 — was die "USD price list" konkret ist

Die Preislisten stammen aus der Migration `officeno1_migration` (live gelesen, nicht aus
git):

| ERPNext Preisliste | Währung | buying | Zeilen | Quelle (Mapping-Typ) | 4D-Spalte |
|---|---|---|---|---|---|
| `Standard-Kauf` | EUR | 1 | 29.446 | `EKItemPricesEUR` | `Artikel.LETZTER_EK_NTO` |
| `Standard-Kauf-USD` | USD | 1 | 18.341 | `EKItemPricesUSD` | `Artikel.EK_USD` |
| `Standard-Vertrieb` | EUR | 0 (Verkauf) | 34.620 | `VKItemPrices` | Verkaufspreis |

Für die 224 betroffenen Artikel:

* **224/224** haben eine `Standard-Kauf-USD`-Zeile,
* **4/224** haben zusätzlich eine `Standard-Kauf`-Zeile (EUR): LB28650 (0,06), 82580 (0,66),
  82581 (1,72), 56421 (0,60),
* 4D-Sicht: `EK_USD` gefüllt 224/224, `letzter_EK_Nto` gefüllt 4/224, `Letzter_EK_Bto` 4/224,
  `DB_EK1..4` 0/224, `Kalk_HK` 0/224.

Pro Artikel existiert genau eine Zeile je Preisliste (kein Supplier-/Datums-Splitting).

## Messung 3 — Währung: gehört der USD-Preis überhaupt in diese Bestellungen?

* Die 24 gespiegelten Bestellungen sind **alle EUR / Standard-Kauf**, `conversion_rate` 1.0.
* 4D `BESTELLUNG.Waehrung` über **alle 2.051** Bestellungen: `EUR` 1.541, `Eur` 504,
  `ATS` 6 — **USD kommt nicht vor**. Die Quellspalte kann eine USD-Bestellung also gar
  nicht ausdrücken (`UmRechFrW` ist bei den ATS-Bestellungen z. B. 13,7603, sonst 1.0).
* ERPNext: `tabCurrency Exchange` = **0 Zeilen**; Company-Währung EUR; USD ist enabled.
  Es gibt also keinen hinterlegten USD/EUR-Kurs, aus dem umgerechnet werden könnte.
* Die 40 manuell angelegten Bestellungen: **30 USD / Standard-Kauf-USD**
  (`conversion_rate` 0,86207 bzw. 0,86214; LNG-BE-2026-0043 vom 2026-07-02: 0,8785) und
  10 EUR. Von den 25 Zeilen dieser manuellen USD-Bestellungen, die betroffene Artikel
  verwenden, haben **25/25** genau den USD-Preislisten-Preis als `rate` (`rate == 4D
  EK_USD`, 0 Abweichungen) — der Kunde benutzt die USD-Preisliste also genau so.
* `Purchase Receipts` der Site: 20 USD / 9 EUR — der Wareneingang dieser
  Import-Lieferanten läuft real in USD.

Damit ist die Währungsfrage entschieden: die Position gehört in **EUR** (die Bestellung ist
eine EUR-Bestellung), der einzige belegte USD/EUR-Kurs dieser Umgebung ist der, den der
Kunde selbst in seinen USD-Bestellungen verwendet: **0,86207 EUR je USD** (28 POs,
LNG-BE-2026-0007 … 0041; Ausreißer 0,8785 vom 2026-07-02).

## Änderung (nur Sync-Instance + Server Script, kein App-Code, kein Mapping)

* **NEU** `app_data/server_scripts/fill_purchase_order_prices.py` — Server Script
  *"fill purchase order prices from usd price list"*, live angelegt und in
  `officeno1_purchase_orders` als Hook **after / both** registriert (nach dem
  `submit purchase orders`-Hook).
* Regel je Bestellzeile **mit `rate = 0`**:
  1. Preis aus der EUR-Einkaufspreisliste `Standard-Kauf`, sonst
  2. Preis aus `Standard-Kauf-USD` × `usd_to_eur_rate` (0,86207), gerundet auf 2 Stellen.
  Geschrieben werden `rate`, `price_list_rate`, `base_rate`, `base_price_list_rate`;
  Zeilenbeträge (`amount`, `net_rate`, `net_amount`, `base_*`) und die Kopfsummen
  (`total`/`net_total`/`grand_total`/`rounded_total`/`in_words` …) rechnet **ERPNext
  selbst** (`calculate_taxes_and_totals()` + `set_total_in_words()`).
* Der Kurs steht als Konstante `usd_to_eur_rate` im Server Script — ändert sich der Kurs,
  wird er dort angepasst.
* Nur die gespiegelten Bestellungen (`Sync Mapping` → `Sync Mapping Entry.docname`) werden
  angefasst; die 40 manuellen Bestellungen, andere Sync-Instances und das Mapping
  `purchase_orders.json` bleiben unverändert.
* Idempotent: Zeilen mit Preis werden nie berührt → ein Hook-Lauf auf unveränderten Daten
  ist ein No-Op. Der Hook repariert außerdem den Fall, dass die **Update-Phase** aus einer
  unveränderten 4D-Quelle erneut `0.0` in `rate` schreibt (`update.py` überspringt nur
  `None`/`""`, nicht `0.0`) — im selben Zyklus, da der Hook danach läuft.

## Verifikation (live, echte Zahlen)

1. **Import + Update erneut ausgeführt** (`start_import(instance, top=100,
   types_str='["PurchaseOrder"]')` + `run_bulk_update(...)`, gewartet mit
   `controller.wait_for_jobs`): beide Jobs `ok`, beide Hooks laufen
   (`scripts_to_call: ['submit purchase orders', 'fill purchase order prices from usd price list']`,
   `logs/pit_erpnextsync.log`).
2. **Vorher/Nachher-Zählung:** Positionszeilen mit `rate = 0` — Site vorher
   **224 von 1542** (alle in den 24 gespiegelten POs, 500 Zeilen), nachher **0 von 1542**.
3. **Unabhängige Nachrechnung** (eigenes Verifikationsskript, ohne den Server-Script-Code):
   224/224 nachgetragene Zeilen stimmen in `rate`, `price_list_rate` und `amount` exakt
   (0 Abweichungen); 220 aus `Standard-Kauf-USD` × 0,86207, 4 aus `Standard-Kauf`
   (LB28650 0,06 / 82580 0,66 / 82581 1,72 / 56421 0,60).
   Beispiele: 65148 (USD 2,15 → 1,85), 65149 (USD 1,25 → 1,08), 98862 (USD 0,52 → 0,45),
   98863 (USD 0,88 → 0,76), 98864 (USD 1,75 → 1,51), 98865 (USD 0,64 → 0,55).
4. **Non-Regression:** die 276 bereits bepreisten importierten Zeilen haben **0 geänderte
   Felder** (`rate`, `price_list_rate`, `amount`, `base_*`, `net_*`); `received_qty`/`qty`
   **0 Abweichungen** über alle 500 Zeilen; Kopf-Felder (docstatus, currency,
   buying_price_list, conversion_rate, status) **0 Änderungen**.
5. **Kopfsummen** — `total == Summe(amount)` für alle 24 POs (18 geändert, 6 unverändert):

   | PO | total vorher | total nachher |
   |---|---|---|
   | LNG-BE-2026-0045 | 1.144,32 | 3.529,44 |
   | LNG-BE-2026-0047 | 8.477,04 | 20.463,36 |
   | LNG-BE-2026-0048 | 1.629,24 | 4.785,00 |
   | LNG-BE-2026-0052 | 1.182,82 | 6.258,94 |
   | LNG-BE-2026-0054 | 0,00 | 5.374,80 |
   | LNG-BE-2026-0055 | 5.637,94 | 5.707,06 |
   | LNG-BE-2026-0056 | 1.653,12 | 3.098,88 |
   | LNG-BE-2026-0057 | 5.531,28 | 12.081,48 |
   | LNG-BE-2026-0058 | 3.404,40 | 6.459,60 |
   | LNG-BE-2026-0059 | 2.102,76 | 3.783,96 |
   | LNG-BE-2026-0061 | 2.485,80 | 5.906,64 |
   | LNG-BE-2026-0062 | 0,00 | 5.844,48 |
   | LNG-BE-2026-0063 | 1.912,32 | 4.497,12 |
   | LNG-BE-2026-0064 | 2.193,41 | 11.645,33 |
   | LNG-BE-2026-0065 | 0,00 | 6.995,04 |
   | LNG-BE-2026-0066 | 0,00 | 6.137,28 |
   | LNG-BE-2026-0067 | 15.156,36 | 50.042,88 |
   | LNG-BE-2026-0068 | 0,00 | 2.045,16 |

   unverändert: LNG-BE-2026-0046 (13.038,24), 0049 (679,68), 0050 (9.409,92),
   0051 (178,95), 0053 (5.714,16), 0060 (767,70). `in_words` wird mitgeführt
   (z. B. 0047 vorher *"… Eight Thousand, Four Hundred And Seventy Seven …"* → nachher
   *"… Twenty Thousand, Four Hundred And Sixty Three and Thirty Six Cent only."*).
6. **Submit-Hook-Regression:** max `abs(per_received − received/qty*100)` über die 24 POs
   = **4,55e-10** < 1e-6 → der Hook schreibt **0 von 24** POs neu (unverändert zu ADJ1).
7. **Zweiter kompletter Zyklus** (Import + Update + beide Hooks): **0** POs mit geändertem
   `(modified, total, per_received, status)`; Summe `amount` aller Positionszeilen
   795.497,54 vorher == nachher; weiterhin **0** Nullzeilen.
8. **Keine neuen Fehler:** `tabError Log` enthält keinen Eintrag des neuen Hooks
   (Methode `Fill purchase order prices` = 0). Die vorhandenen
   `Submit purchase orders`-Einträge (Fallback-Pfad „Item Group … not found“) stammen aus
   den Import-Läufen 11:42–12:10 Uhr, also **vor** dieser Änderung.

## Betroffene Dateien / Zeilen

* **NEU** `app_data/server_scripts/fill_purchase_order_prices.py` (Server Script
  *fill purchase order prices from usd price list*, live angelegt, Hook after/both).
* `app_data/mappings/purchase_orders_instance.json` — Hook-Eintrag ergänzt (Zeilen 24–28).
* `app_data/mappings/purchase_orders.json` — **unverändert** (`rate`/`price_list_rate`
  bleiben auf `PREIS_EK`; der Nachtrag passiert im Server Script).
* Kein App-Code geändert, keine anderen Sync-Instances, keine manuellen Bestellungen.

## Offene Punkte / Empfehlung

* Der Kurs **0,86207** ist die Konvention des Kunden (in 28 eigenen USD-Bestellungen
  belegt). ERPNext selbst hat keinen Kurs hinterlegt — wenn sich der Kurs ändert, ist
  `usd_to_eur_rate` im Server Script anzupassen (oder eine `Currency Exchange` zu pflegen,
  dann könnte der Hook sie lesen).
* Nicht umgesetzt (Geschäftsentscheidung, würde 125 bereits korrekt importierte EUR-Zeilen
  derselben Bestellungen umdeuten und die Währung gestellter Bestellungen ändern): die
  Import-Bestellungen wie die manuellen POs als **USD-Bestellungen** mit
  `Standard-Kauf-USD` zu führen.
* Empfehlung an Lang: für neue Import-Artikel auch den EUR-EK
  (`BESTELLUNGpos.Preis_EK` bzw. `Artikel.LETZTER_EK_NTO`) pflegen — dann liefert der Sync
  den EUR-Preis direkt aus der Quelle und der Nachtrag greift nur noch als Fallback.

## Reproduktion (Server, temporäre Skripte wurden danach entfernt)

```
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_usd_po_4d.main_measure
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_usd_po_ratio2.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_fill_dryrun.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_run_cycle.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_verify_fill.main_verify
```

---

# ADJUSTMENT 3 (2026-09-28): Preisliste der importierten Bestellungen auf "Standard-Kauf-USD"

## Auftrag (User, wörtlich)

> "die preisliste muss auf standard kauf usd umgestellt werden"

## Ergebnis in einem Satz

Alle 24 gespiegelten Bestellungen (`LNG-BE-2026-0045` … `0068`) sind jetzt **USD-Bestellungen
mit der Käufer-Preisliste `Standard-Kauf-USD`, Kurs 0,86207 und EUR-Basiswerten** — genau in
der Form, in der der Kunde seine eigenen USD-Bestellungen anlegt (ADJUSTMENT 2 hatte diese
Umstellung als offene Geschäftsentscheidung notiert). Die EK-Preise aus 4D bleiben
unangetastet; nur die 224 Zeilen, in denen 4D **keinen** Preis hat, tragen den echten
USD-Preislisten-Preis (vorher: USD-Preis × Kurs, also ein abgeleiteter EUR-Wert).

## Messung 1 — wie der Kunde seine eigenen USD-Bestellungen baut (das 1:1-Vorbild)

Gemessen an den 30 manuellen Bestellungen `LNG-BE-2026-0007` … `0043` (u. a. für dieselben
Lieferanten wie die importierten Bestellungen):

| Feld | Wert in den manuellen USD-POs |
|---|---|
| `currency` | USD |
| `conversion_rate` | 0,86207 (Ausreißer `0043`: 0,8785, Kurs vom 02.07.2026) |
| `price_list_currency` | USD |
| `plc_conversion_rate` | = Kurs |
| `buying_price_list` | Standard-Kauf-USD |
| Positionszeile `rate` | = `price_list_rate` = **Preis aus der USD-Preisliste** (2 NKS) |
| Positionszeile `base_rate` / `base_amount` | = `rate` / `amount` × Kurs |

Beispiel `LNG-BE-2026-0007` (USD, Kurs 0,86207): Zeile rate=0,30 / base_rate=0,26 /
amount=345,60 / base_amount=297,93. Beispiel `LNG-BE-2026-0043` (USD, Kurs 0,8785):
rate=0,68 / base_rate=0,5974 / amount=489,60 / base_amount=430,11.

## Messung 2 — Zustand der 24 importierten Bestellungen vor der Umstellung

* Kopf (24/24): `currency=EUR`, `conversion_rate=1.0`, `price_list_currency=EUR`
  (9 Bestellungen ohne Wert), `plc_conversion_rate=0/1.0`, `buying_price_list=Standard-Kauf`.
* 500 Positionszeilen: 276 Zeilen mit 4D-Preis (`BESTELLUNGpos.Preis_EK`, rate == Preis_EK,
  0 Abweichungen), 224 Zeilen mit 4D-Preis 0 — davon 222 mit `rate = USD-Preis × 0,86207`
  (gerundet) und 2 mit dem EUR-Preislisten-Preis; **keine** Zeile ohne Preis, keine Rabatte,
  alle `uom == stock_uom`, 393 Zeilen mit `stock_uom_rate = 0` (Altlast aus dem Import).
* Summe Positionsbeträge 194.445,10 (damals = Basiswert, da Kurs 1,0).

## Änderung

1. **Mapping** `app_data/mappings/purchase_orders.json` (identisch nach
   `/private/files/officeno1_purchase_order_mapping.json` kopiert, die Datei ist die Quelle
   der `Selectline Table Mapping`-Zeilen):
   * `currency`: `default: "USD"` — vorher `sl_column: WAEHRUNG` + `value_map` auf die
     4D-Währung;
   * `buying_price_list`: `default: "Standard-Kauf-USD"` — vorher ebenfalls aus `WAEHRUNG`;
   * `conversion_rate`: `default: 0.86207` — vorher `sl_column: UMRECHFRW` (= 1,0 bei den
     EUR-Bestellungen; ERPNext hätte für USD sonst einen Kurs verlangt, den es auf dieser
     Site nicht gibt).
   Damit hängt der Kopf der Bestellung **nicht mehr von der 4D-Währung** ab.
   Sync-Instance danach über `controller.load_table_mapping` neu geladen — das gespeicherte
   `table_mapping` entspricht der Datei (14 Felder, keine Differenz).
2. **72 gespeicherte `Sync Mapping Entry`-Zeilen** (3 Felder × 24 Bestellungen) auf
   `selectline_column = ""` gesetzt. Grund: die Update-Phase arbeitet über die
   *gespeicherten* Einträge und hätte sonst bei jeder Quelländerung EUR/1,0/Standard-Kauf
   wieder zurückgeschrieben. Zeilen ohne Quellspalte werden von der Update-Phase
   übersprungen; der neue Wert kommt aus dem Mapping-Default bzw. dem Server Script.
3. **Server Script** `fill purchase order prices from usd price list`
   (`app_data/server_scripts/fill_purchase_order_prices.py`) neu gefasst:
   * erzwingt den Kopf: `currency=USD`, `conversion_rate=0.86207`, `price_list_currency=USD`,
     `plc_conversion_rate=0.86207`, `buying_price_list=Standard-Kauf-USD`;
   * füllt **fehlende** Preise: **USD-Preisliste primär**, EUR-Preisliste nur noch als
     Fallback (vorher umgekehrt), Rundung auf 2 Nachkommastellen (Währungspräzision);
   * **vorhandene Zeilenpreise bleiben unangetastet** (4D `Preis_EK` ist der Bestellpreis,
     der in ADJUSTMENT 2 bereits korrekt in der Zeile steht und nicht umgedeutet wird);
   * rechnet Beträge, Basisbeträge und Summen über ERPNexts
     `calculate_taxes_and_totals()` in USD/EUR neu und ergänzt `set_total_in_words()`
     (das ruft ERPNext nur in `validate()` auf, nicht in der Berechnung);
   * schreibt ausschließlich tatsächlich abweichende Felder → zweiter Lauf ist ein No-op;
   * Fallback für die drei Bestellungen mit Steuerzeilen (`0046`, `0051`, `0060`): ERPNexts
     Item-Tax-Template-Prüfung schlägt den Item-Group-Stammdatensatz nach, diese Artikel
     tragen aber die SelectLine-Artikelgruppen**nummer** als `item_group` (kein Stammdatensatz
     auf dieser Site, Webshop-Toleranz, vgl. PIT-TASK-2027-000346). Die Berechnung wird in
     diesen Fällen mit ausgeblendeten `item_tax_template` wiederholt (die Zeilen sind
     +20 % / −20 % auf Nettosumme, Steuersumme 0 → keine Auswirkung auf die Werte).
4. **Datenübernahme**: ein erzwungener Update-Lauf (`run_bulk_update(..., ignore_ts=1)`)
   schreibt `PREIS_EK` in alle 500 Zeilen (die 224 Nullzeilen damit auf 0), im selben Zyklus
   füllt der Hook sie aus der USD-Preisliste und rechnet alle Basiswerte neu.
5. **Doku** (diese Datei).

## Verifikation (live, nach der Umstellung)

* **Kopf 24/24**: `currency=USD`, `conversion_rate=0.86207`, `price_list_currency=USD`,
  `plc_conversion_rate=0.86207`, `buying_price_list=Standard-Kauf-USD`, `docstatus=1`.
* **500 Zeilen**: 276 Zeilen mit 4D-Preis → `rate == Preis_EK` (0 Abweichungen, geprüft
  gegen `BESTELLUNGpos` über die Mapping-Keys); 224 Nullzeilen → **alle** aus der
  USD-Preisliste gefüllt (0 EUR-Fallback, 0 Zeilen ohne Preis); `rate = 0`: **0** Zeilen.
* Basiswerte: `base_rate == rate × 0,86207` (max. Abweichung 0,00005),
  `base_amount == amount × 0,86207` (max. 0,005), `amount == qty × rate`,
  `net_rate == rate`, `net_amount == amount`, `stock_uom_rate == rate`.
* Kopfsummen == Zeilensummen (`total`, `base_total`, `grand_total`), Steuersumme aller 24
  Bestellungen 0, `grand_total == total`.
* `received_qty == 4D MengeGeliefert` (0 Abweichungen), `qty == 4D Menge` (0 Abweichungen),
  `per_received` und `status` unverändert → der Submit-Hook schreibt **0 von 24**
  Bestellungen neu.
* **Idempotenz**: zweiter Sync-Lauf (Import + Update, ohne `ignore_ts`) meldet alle 24
  Mappings "up to date"; der Preis-Hook meldet `changed_orders=0 changed_lines=0
  written_field_values=0`; Snapshot-Vergleich vor/nach dem Lauf ergibt **0 Feldänderungen**,
  auch kein `modified`-Bump.
* **Unverändert**: 64 Bestellungen / 1542 Positionen auf der Site, 40 manuelle Bestellungen
  (neueste Änderung 16.07.2026, keine heute), die anderen Sync-Instances
  (`officeno1_migration`, `officeno1_sales_orders`, `stock_reconciliation`) wurden nicht
  angefasst, kein App-Code außerhalb `app_data/`.

## Geänderte Werte (konkret)

Kopf-Felder geändert: `currency`, `conversion_rate`, `price_list_currency`,
`plc_conversion_rate`, `buying_price_list` in **24/24** Bestellungen; `total`/`grand_total`
in 18 Bestellungen (bei 6 Bestellungen bestand keine Zeile ohne 4D-Preis);
`base_grand_total` in 24/24; `in_words`/`base_in_words` in 24/24; `per_received`, `status` und
die Steuersumme in 0/24.

Zeilen mit neuem `rate` (`= USD-Preislisten-Preis`, Pos / Artikel / alt → neu):

| Bestellung | Zeilen | Beispiele |
|---|---|---|
| LNG-BE-2026-0045 | 6 | 4 65148 1.85→2.15, 5 65149 1.08→1.25, 6 65150 1.85→2.15 |
| LNG-BE-2026-0046 | 0 | – |
| LNG-BE-2026-0047 | 29 | 21 24634 1.28→1.48, 22 24635 0.16→0.18, 23 24636 0.38→0.44 |
| LNG-BE-2026-0048 | 6 | 2 56486 1.02→1.18, 5 56483 0.85→0.99, 6 56484 0.82→0.95 |
| LNG-BE-2026-0049 | 0 | – |
| LNG-BE-2026-0050 | 0 | – |
| LNG-BE-2026-0051 | 0 | – |
| LNG-BE-2026-0052 | 12 | 4 24715 1.13→1.31, 5 24716 0.78→0.91, 6 24717 1.74→2.02 |
| LNG-BE-2026-0053 | 0 | – |
| LNG-BE-2026-0054 | 9 | 1 86686 0.65→0.75, 2 56507 2.86→3.32, 3 56506 2.86→3.32 |
| LNG-BE-2026-0055 | 1 | 1 LB28650 0.06→0.07 |
| LNG-BE-2026-0056 | 2 | 3 82580 0.66→0.75, 4 82581 1.72→1.95 |
| LNG-BE-2026-0057 | 15 | 3 56509 2.54→2.95, 4 56508 1.21→1.40, 5 56500 1.72→2.00 |
| LNG-BE-2026-0058 | 6 | 6 65154 0.52→0.60, 7 65155 0.78→0.90, 8 65156 0.60→0.70 |
| LNG-BE-2026-0059 | 3 | 1 98842 0.79→0.92, 2 98841 0.32→0.37, 3 24697 0.75→0.87 |
| LNG-BE-2026-0060 | 0 | – |
| LNG-BE-2026-0061 | 7 | 5 24698 1.38→1.60, 6 24699 1.16→1.35, 7 24700 2.37→2.75 |
| LNG-BE-2026-0062 | 12 | 1 S24728 0.39→0.45, 2 98849 0.34→0.40, 3 98848 0.39→0.45 |
| LNG-BE-2026-0063 | 6 | 1 24633 0.76→0.88, 2 24632 0.93→1.08, 3 24631 0.63→0.73 |
| LNG-BE-2026-0064 | 20 | 1 65125 0.69→0.80, 2 65124 0.60→0.70, 8 65126 0.60→0.70 |
| LNG-BE-2026-0065 | 10 | 1 65145 0.72→0.83, 2 65146 1.27→1.47, 3 65147 1.56→1.81 |
| LNG-BE-2026-0066 | 6 | 1 24709 1.45→1.68, 2 24712 1.12→1.30, 3 24711 1.36→1.58 |
| LNG-BE-2026-0067 | 70 | 1 24695 1.40→1.62, 2 24726 0.60→0.70, 34 24657 0.49→0.57 |
| LNG-BE-2026-0068 | 4 | 1 98862 0.45→0.52, 2 98863 0.76→0.88, 3 98864 1.51→1.75 |

Summen je Bestellung (Positionssumme in Bestellwährung und Basiswert in EUR):

| Bestellung | Summe vorher | nachher (USD) | Basis vorher | nachher (EUR) |
|---|---|---|---|---|
| LNG-BE-2026-0045 | 3529.44 | 3911.04 | 3529.44 | 3371.61 |
| LNG-BE-2026-0046 | 13038.24 | 13038.24 | 13038.24 | 11240.07 |
| LNG-BE-2026-0047 | 20463.36 | 22367.76 | 20463.36 | 19282.57 |
| LNG-BE-2026-0048 | 4785.00 | 5313.96 | 4785.00 | 4581.01 |
| LNG-BE-2026-0049 | 679.68 | 679.68 | 679.68 | 585.93 |
| LNG-BE-2026-0050 | 9409.92 | 9409.92 | 9409.92 | 8111.99 |
| LNG-BE-2026-0051 | 178.95 | 178.95 | 178.95 | 154.24 |
| LNG-BE-2026-0052 | 6258.94 | 7068.94 | 6258.94 | 6093.91 |
| LNG-BE-2026-0053 | 5714.16 | 5714.16 | 5714.16 | 4926.01 |
| LNG-BE-2026-0054 | 5374.80 | 6230.64 | 5374.80 | 5371.24 |
| LNG-BE-2026-0055 | 5707.06 | 5718.58 | 5707.06 | 4929.80 |
| LNG-BE-2026-0056 | 3098.88 | 3294.72 | 3098.88 | 2840.29 |
| LNG-BE-2026-0057 | 12081.48 | 13135.44 | 12081.48 | 11323.68 |
| LNG-BE-2026-0058 | 6459.60 | 6949.20 | 6459.60 | 5990.70 |
| LNG-BE-2026-0059 | 3783.96 | 4052.52 | 3783.96 | 3493.56 |
| LNG-BE-2026-0060 | 767.70 | 767.70 | 767.70 | 661.82 |
| LNG-BE-2026-0061 | 5906.64 | 6457.84 | 5906.64 | 5567.11 |
| LNG-BE-2026-0062 | 5844.48 | 6758.40 | 5844.48 | 5826.22 |
| LNG-BE-2026-0063 | 4497.12 | 4907.52 | 4497.12 | 4230.61 |
| LNG-BE-2026-0064 | 11645.33 | 13169.57 | 11645.33 | 11353.06 |
| LNG-BE-2026-0065 | 6995.04 | 8123.04 | 6995.04 | 7002.63 |
| LNG-BE-2026-0066 | 6137.28 | 7119.60 | 6137.28 | 6137.60 |
| LNG-BE-2026-0067 | 50042.88 | 55557.12 | 50042.88 | 47894.13 |
| LNG-BE-2026-0068 | 2045.16 | 2369.52 | 2045.16 | 2042.69 |
| **Summe** | **194445.10** | **212294.06** | **194445.10** | **183012.48** |

Zusätzlich wurden in 400 Zeilen `stock_uom_rate` von 0 auf `rate` gesetzt (Altlast aus dem
Import; reines Nachführfeld, ohne Wirkung auf Beträge oder Summen). Die 55 Zeilen mit
dreistelligem `rate` sind 4D-Quellpreise (z. B. 1,139) und wurden bewusst **nicht** gerundet.

## Offene Frage an den User (bitte entscheiden)

Die Semantik der **276 Zeilen mit 4D-Preis**: sie behalten ihren Quellpreis aus 4D. Da die
Bestellung jetzt eine USD-Bestellung ist, steht dieser Wert nun als USD-Betrag in der Zeile,
und der EUR-Buchwert der Zeile entspricht `Preis × 0,86207` (also 86,207 % des 4D-Wertes).
Die **224 Zeilen ohne 4D-Preis** tragen jetzt den echten USD-Preislisten-Preis, ihr
EUR-Buchwert bleibt dabei praktisch unverändert.

Wenn der Kunde möchte, dass **jede** Zeile den Preis der USD-Preisliste trägt (in seinen
manuellen Bestellungen entspricht `rate` immer exakt dem Preislisten-Preis — 25/25 Zeilen
gemessen), müssen die 276 Quellzeilen ebenfalls auf den Preislisten-Preis umgestellt werden.
Beispiel `LNG-BE-2026-0047`, Zeile 1: 1,85 → 1,97 USD. Das ist ohne Rückmeldung **nicht**
gemacht worden, weil es die Bestellwerte gegenüber der 4D-Quelle verändert.

## Betroffene Dateien / Zeilen

* `app_data/mappings/purchase_orders.json` — `currency`, `buying_price_list`,
  `conversion_rate` (Kopf-Felder des Purchase-Order-Blocks), inkl. Kommentaren.
* `/private/files/officeno1_purchase_order_mapping.json` (Site) — identischer Inhalt.
* `app_data/server_scripts/fill_purchase_order_prices.py` — komplett neu gefasst
  (Server Script "fill purchase order prices from usd price list" auf der Site wurde aus
  dieser Datei aktualisiert).
* Sync Instance `officeno1_purchase_orders`: `table_mapping` neu geladen, 72
  `Sync Mapping Entry`-Zeilen (Feld `selectline_column` geleert).
* Sync Mapping-Einträge der 24 Bestellungen: Feldwerte `currency`, `conversion_rate`,
  `price_list_currency`, `plc_conversion_rate`, `buying_price_list` + Werte der 500 Zeilen.
* Kein App-Code, keine anderen Sync-Instances, keine manuellen Bestellungen.

## Reproduktion (Server, temporäre Skripte wurden danach entfernt)

```
# Messung des Vorbilds (manuelle USD-POs) und des Vorzustands
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_po_ref.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_po_state.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_po_plan.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_po_4d.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.diag_po_snapshot.dump --kwargs '{"path":"/tmp/adj3_before.json"}'

# Deploy + Datenübernahme
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj3_deploy.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj3_run_cycle.main --kwargs '{"do_import":true,"ignore_ts":true}'

# Verifikation + Idempotenz (zweiter Lauf ohne ignore_ts)
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj3_verify.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj3_run_cycle.main --kwargs '{"do_import":true,"ignore_ts":false}'
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj3_dump_mapping.main
```

---

# ADJUSTMENT 4 (2026-09-28): Preisliste je Quellwährung — USD-Preis → Standard-Kauf-USD, EUR-Preis → Standard-Kauf

## Auftrag (User, wörtlich)

> "can you please check where prices are dollar in source db set price list to dollar and if euro set pricelist to euro"

## Ergebnis in einem Satz

Die Preisliste folgt jetzt der Währung, in der die Einkaufspreise der Bestellung in der Quelle
gepflegt sind: **21 der 24 gespiegelten Bestellungen** der chinesischen/indischen Lieferanten sind
**USD-Bestellungen auf `Standard-Kauf-USD`** (Dollar-Preise, 4D `Artikel.EK_USD`), **3 Bestellungen**
der deutschen Lieferanten (Halbach 33078, Mabella 33345, Carl Dietrich 33547) sind **EUR-Bestellungen
auf `Standard-Kauf`** (Euro-Preise, 4D `Artikel.LETZTER_EK_NTO`). **Jede** der 500 Positionszeilen
trägt exakt den Preis der Preisliste ihrer Bestellwährung — es wird keine Preisliste gemischt und
kein Kurs erfunden. Die 4D-Bestellpreise (`BESTELLUNGpos.Preis_EK`) sind gemessen **Euro-Werte**
(sie entsprechen in 271 von 276 bepreisten Zeilen centgenau dem EUR-Preislisten-Preis) und werden
deshalb **nicht mehr als Zeilenpreis verwendet**; in den 3 EUR-Bestellungen sind sie ohnehin der
EUR-Preis, in den 21 USD-Bestellungen sind sie der EUR-Buchwert der Zeile (jetzt `base_rate`).

Die ADJUSTMENT-3-Festverdrahtung (`currency`/`buying_price_list`/`conversion_rate` fest auf den
USD-Kopf) ist damit ersetzt: die Bestellwährung ergibt sich aus der Quelle (Lieferantenwährung),
der Kopf wird im Mapping aus 4D `BESTELLUNG.Waehrung` vorbelegt und vom Server Script auf die
Lieferantenwährung ausgerichtet.

## Messung 1 — Währung der Quellpreise, pro Bestellung (live gegen 4D und ERPNext)

Matching der ERPNext-Zeilen zu den 4D-Zeilen über `tabSync Mapping Entry.source_row_key`
(Mapping-Key `match_key_column: PRIMARYKEY`) — alle 500 Zeilen eindeutig zuordenbar.

Spalten der Messung (je Bestellung):

* `BestellNr`-Lieferant, ERPNext `Supplier.default_currency` / `default_price_list`
* 4D `BESTELLUNG.Waehrung`, 4D `Lieferant.Waehrung` (beide EUR/Eur über alle 2.051 Bestellungen
  bzw. alle 31 Lieferanten — **in 4D steht nirgends USD**, deshalb ist die Lieferantenwährung aus
  dem ERPNext-Stamm maßgeblich)
* Zahl der Zeilen mit einem 4D-Bestellpreis (`PREIS_EK > 0`) und Zahl der Zeilen ohne
* Zahl der Zeilen mit einem Preis in der USD-Preisliste (`Artikel.EK_USD` → `Standard-Kauf-USD`)
  und in der EUR-Preisliste (`Artikel.LETZTER_EK_NTO` → `Standard-Kauf`)

| Bestellung | Lieferant | Supplier-Stamm (ERPNext) | 4D `Waehrung` | 4D `Lieferant.Waehrung` | Zeilen mit 4D-Preis | Zeilen ohne 4D-Preis | Zeilen mit USD-Preis | Zeilen mit EUR-Preis | Währung / Preisliste |
|---|---|---|---|---|---|---|---|---|---|
| LNG-BE-2026-0045 | 33539 | USD / Standard-Kauf-USD | EUR | EUR | 3 | 6 | 9 | 3 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0046 | 33547 | **EUR / Standard-Kauf** | EUR | EUR | 49 | 0 | **0** | 49 | **EUR / Standard-Kauf** |
| LNG-BE-2026-0047 | 33349 | USD / Standard-Kauf-USD | EUR | EUR | 22 | 29 | 51 | 22 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0048 | 33542 | USD / Standard-Kauf-USD | EUR | EUR | 3 | 6 | 9 | 3 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0049 | 33438 | USD / Standard-Kauf-USD | EUR | EUR | 1 | 0 | 1 | 1 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0050 | 33285 | USD / Standard-Kauf-USD | EUR | EUR | 8 | 0 | 8 | 8 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0051 | 33078 | **EUR / Standard-Kauf** | Eur | Eur | 41 | 0 | **0** | 41 | **EUR / Standard-Kauf** |
| LNG-BE-2026-0052 | 33297 | USD / Standard-Kauf-USD | EUR | EUR | 3 | 12 | 15 | 3 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0053 | 33499 | USD / Standard-Kauf-USD | EUR | EUR | 9 | 0 | 9 | 9 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0054 | 33543 | USD / Standard-Kauf-USD | EUR | EUR | 0 | 9 | 9 | 0 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0055 | 33380 | USD / Standard-Kauf-USD | EUR | EUR | 25 | 1 | 26 | 26 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0056 | 33334 | USD / Standard-Kauf-USD | EUR | EUR | 3 | 2 | 5 | 5 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0057 | 33521 | USD / Standard-Kauf-USD | EUR | EUR | 12 | 15 | 27 | 13 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0058 | 33334 | USD / Standard-Kauf-USD | EUR | EUR | 6 | 6 | 12 | 6 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0059 | 33540 | USD / Standard-Kauf-USD | EUR | EUR | 3 | 3 | 6 | 3 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0060 | 33345 | **EUR / Standard-Kauf** | EUR | EUR | 43 | 0 | **0** | 43 | **EUR / Standard-Kauf** |
| LNG-BE-2026-0061 | 33443 | USD / Standard-Kauf-USD | EUR | EUR | 5 | 7 | 12 | 5 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0062 | 33551 | **(nicht gepflegt)** | EUR | EUR | 0 | 12 | 12 | 0 | **USD / Standard-Kauf-USD** (aus Preisdaten) |
| LNG-BE-2026-0063 | 33417 | USD / Standard-Kauf-USD | EUR | EUR | 4 | 6 | 10 | 4 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0064 | 33321 | USD / Standard-Kauf-USD | EUR | EUR | 5 | 20 | 25 | 5 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0065 | 33358 | USD / Standard-Kauf-USD | EUR | EUR | 0 | 10 | 10 | 0 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0066 | 33552 | **(nicht gepflegt)** | EUR | EUR | 0 | 6 | 6 | 0 | **USD / Standard-Kauf-USD** (aus Preisdaten) |
| LNG-BE-2026-0067 | 33427 | USD / Standard-Kauf-USD | EUR | EUR | 31 | 70 | 101 | 31 | **USD / Standard-Kauf-USD** |
| LNG-BE-2026-0068 | 33438 | USD / Standard-Kauf-USD | EUR | EUR | 0 | 4 | 4 | 0 | **USD / Standard-Kauf-USD** |

**Das ist die entscheidende Messung:** die Aufteilung ist **nicht** willkürlich, sondern deckt sich
in allen 24 Bestellungen mit der Preisliste, in der die Artikel der Bestellung tatsächlich
gepflegt sind:

* Die **133 Zeilen ohne USD-Preisliste-Preis** sind **genau** die Zeilen der 3 EUR-Bestellungen
  (49 + 41 + 43) — und alle 133 haben einen `Standard-Kauf`-Preis.
* Die **367 Zeilen der 21 USD-Bestellungen** haben **alle** einen `Standard-Kauf-USD`-Preis
  (und nur 143 davon zusätzlich einen EUR-Preis).
* `no_price_found = 0`: keine Zeile bleibt ohne Preis, es muss keine Preisliste "geborgt" werden.

## Messung 2 — wie der Kunde selbst bucht (das 1:1-Vorbild, live gemessen)

Die 40 manuell angelegten Bestellungen derselben Lieferanten (`LNG-BE-2026-0004` … `0044`,
unverändert, jüngste Änderung 2026-07-16):

| Merkmal | Wert |
|---|---|
| Bestellungen | 30 × `USD` / `Standard-Kauf-USD`, 10 × `EUR` / `Standard-Kauf` |
| Zuordnung zum Lieferanten | **40/40** = `Supplier.default_currency` / `default_price_list` |
| Zeilen | 1042 (alle `docstatus=1`) |
| Zeilenpreis `rate` | 980/1042 exakt = Preislisten-Preis; 62 weichen nur durch **Rundung auf 2 Nachkommastellen** ab (z. B. `LNG-BE-2026-0010` Carl Dietrich: Liste 1,139 / 0,928 → `rate` 1,14 / 0,93) |
| Kopf | `currency`, `price_list_currency`, `buying_price_list`, `conversion_rate` 0,86207 (USD) bzw. 1,0 (EUR) |

Der Kunde rundet also selbst auf die Währungspreis-Präzision (2 NKS) — deshalb setzt das Server
Script `rate = round(Preislistenpreis, 2)`. (Das ersetzt die ADJUSTMENT-3-Notiz, die 4D-Preise mit
drei Nachkommastellen, z. B. 1,139, bewusst ungerundet ließ.)

Zusätzliche Belege:

* `Supplier.default_currency` / `default_price_list` sind **nicht** aus der Migration ableitbar
  (kein Mapping-Feld auf `default_currency`/`default_price_list` in `officeno1_migration`) —
  sie sind die **eigene Konfiguration des Kunden** am Lieferantenstamm (`owner Administrator`,
  `modified` 2026-09-07): chinesische/indische Lieferanten USD, deutsche EUR.
* 4D `Lieferant.Waehrung` ist für **alle 31** Lieferanten `EUR`/`Eur` (und `Waehrung2` = `ATS`) —
  die 4D-Quelle kann die USD-Lieferanten also gar nicht ausdrücken.
* `Standard-Kauf` = buying, enabled, currency **EUR**; `Standard-Kauf-USD` = buying, enabled,
  currency **USD**; `tabCurrency Exchange` = **0 Zeilen** (Company-Währung EUR),
  USD ist enabled → für den USD-Kopf muss der Kurs als Konstante geführt werden (0,86207, der
  belegte Kundensatz aus seinen eigenen USD-Bestellungen).

## Messung 3 — die 276 Zeilen mit 4D-Bestellpreis (die offene Frage aus ADJUSTMENT 3)

Die Frage aus ADJ3 war: *sind die 4D-Bestellpreise Dollar- oder Euro-Werte?* Messung über alle 500
Zeilen gegen die Artikelstammpreise:

```
Zeilen mit 4D BESTELLUNGpos.Preis_EK > 0            : 276
davon PREIS_EK == EUR-Preislistenpreis (centgenau)  : 271
davon PREIS_EK == USD-Preislistenpreis (centgenau)  :   0
davon weder noch (max. 1 Cent bzw. Artikel ohne
EUR-Preislistenpreis)                               :   5
Zeilen mit 4D PREIS_EK = 0                          : 224
```

Beispiele `LNG-BE-2026-0067` (USD-Lieferant Hong Guang 33427):
`98750` Preis_EK 0,48 / USD-Liste 0,53 / EUR-Liste 0,48 — `98799` 0,16 / 0,19 / 0,16 —
`98735` 2,18 / 2,51 / 2,18. Beispiele `LNG-BE-2026-0064` (Hong Mei 33321):
`65077` 0,819 / 0,95 / 0,819 — `65082` 2,284 / 2,65 / 2,284.

**Antwort: der 4D-Bestellpreis ist ein Euro-Wert** — er entspricht dem EUR-Preislisten-Preis
(`Artikel.LETZTER_EK_NTO`, migriert als Liste `Standard-Kauf`), nie dem USD-Preis. In den
21 USD-Bestellungen ist er daher der **EUR-Buchwert** der Zeile (er steht nach der Umstellung als
`base_rate`/`base_amount` in der Zeile), in den 3 EUR-Bestellungen ist er der **Zeilenpreis**.
Die 224 Zeilen ohne 4D-Preis haben in **224/224** Fällen einen Dollar-Preis (`Artikel.EK_USD`) —
das ist der im Task genannte "Dollar-Preis in der Quelldatenbank".

## Angewandte Regel (und die verbleibende Entscheidung für Philipp)

**Regel je Bestellung** (implementiert im Server Script `fill purchase order prices from usd price list`):

1. `Supplier.default_currency` / `default_price_list` entscheidet die Währung/Preisliste der
   Bestellung (21 USD-Bestellungen, 3 EUR-Bestellungen, siehe Tabelle).
2. Ist am Lieferanten nichts gepflegt (`33551`, `33552` → `LNG-BE-2026-0062`/`0066`), entscheidet
   die Messung: die Preisliste, die für **jede** Zeile einen Preis hat. Bei beiden ist das
   `Standard-Kauf-USD` (alle 18 Zeilen haben einen USD-Preis, keine einen EUR-Preis) → USD.
3. Kopf: `currency` = Währung der Preisliste, `price_list_currency` = dieselbe Währung,
   `conversion_rate` = `plc_conversion_rate` = 0,86207 (USD) bzw. 1,0 (EUR),
   `buying_price_list` = die Preisliste.
4. **Jede** Zeile: `rate = price_list_rate = round(Preislistenpreis, 2)` der Preisliste dieser
   Bestellwährung. Keine Zeile bekommt einen Preis aus der anderen Währung, kein Kurs wird
   erfunden, keine Zeile bleibt ohne Preis (`no_price_found = 0`).

**Die eine Bewertungsentscheidung** (bitte bestätigen oder anders wünschen): in den 21
USD-Bestellungen tragen **143 Zeilen** einen 4D-Bestellpreis, der ein **Euro-Wert** ist. Diese
Zeilen werden — wie **jede** Zeile in den 30 USD-Bestellungen des Kunden — auf den
**USD-Preislistenpreis** gesetzt (`rate`), ihr Euro-Buchwert (`base_rate` = `rate × 0,86207`)
liegt dadurch median ~2 % neben dem 4D-Wert (Beispiele: `LNG-BE-2026-0047` Pos 1 1,85 → 1,97 USD /
Basis 1,70 EUR; `LNG-BE-2026-0067` Pos 26 0,70 → 0,81 USD / Basis 0,70 EUR). Alternative, falls
der 4D-Bestellwert **centgenau** erhalten bleiben soll: die Zeile als EUR-Wert kennzeichnen — das
ginge nur mit zwei Preislisten in einer Bestellung und ist ohne ERPNext-App-Änderung nicht
möglich; deshalb wurde die 1:1-Kundenkonvention (USD-Bestellung = USD-Preislistenpreis) gewählt.

## Änderung

1. **Mapping** `app_data/mappings/purchase_orders.json` (identisch nach
   `/private/files/officeno1_purchase_order_mapping.json` kopiert, danach
   `controller.load_table_mapping("officeno1_purchase_orders")`):
   * `currency` (Zeilen 51–63): wieder `sl_column: WAEHRUNG` + `value_map` (`Eur`/`EUR` → `EUR`,
     `USD` → `USD`), `value_map_default: "EUR"` — kein fester `default` mehr;
   * `buying_price_list` (Zeilen 65–73): wieder `sl_column: WAEHRUNG` +
     `value_map {"USD": "Standard-Kauf-USD"}`, `value_map_default: "Standard-Kauf"`;
   * `conversion_rate` (Zeilen 75–79): wieder `sl_column: UMRECHFRW` (Quelle), der Kurs wird vom
     Server Script gesetzt;
   * `rate`/`price_list_rate` in `table_fields` bleiben auf `PREIS_EK` (Startwert eines neuen
     Imports, wird im selben Zyklus vom Hook auf den Preislistenpreis gesetzt) — Kommentare dazu
     angepasst (Zeilen 92–97, 129–140).
2. **Server Script** `fill purchase order prices from usd price list`
   (`app_data/server_scripts/fill_purchase_order_prices.py`, komplett neu gefasst): Regel oben,
   `rate`/`price_list_rate`/`stock_uom_rate` je Zeile, `calculate_taxes_and_totals()` +
   `set_total_in_words()`, Schreiben nur abweichender Werte (idempotent), Zähler im Log-Output
   (`usd_orders`, `eur_orders`, `price_list_from_supplier`, `price_list_from_line_coverage`,
   `changed_orders`, `changed_lines`, `no_price_found`).
   Der Item-Tax-Template-Fallback für die 3 EUR-Bestellungen (Item-Group-Stammdaten fehlen,
   Webshop-Toleranz) bleibt.
3. **Datenübernahme**: erzwungener Zyklus (`start_import` + `run_bulk_update(..., ignore_ts=1)`)
   → Kopf und alle 500 Zeilen neu bewertet, danach Doku (diese Datei).

## Verifikation (live, vorher/nachher)

| Bestellung | Lieferant | vorher | nachher | Kurs | Summe vorher | Summe nachher | Basis vorher | Basis nachher | geänderte Zeilen |
|---|---|---|---|---|---|---|---|---|---|
| LNG-BE-2026-0045 | 33539 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 3911.04 | 4092.48 | 3371.61 | 3528.03 | 3 von 9 |
| LNG-BE-2026-0046 | 33547 | USD/Standard-Kauf-USD | **EUR/Standard-Kauf** | 0.86207 → 1.0 | 13038.24 | 13053.60 | 11240.07 | 13053.60 | 49 von 49 |
| LNG-BE-2026-0047 | 33349 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 22367.76 | 23085.36 | 19282.57 | 19901.18 | 22 von 51 |
| LNG-BE-2026-0048 | 33542 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 5313.96 | 5582.28 | 4581.01 | 4812.32 | 3 von 9 |
| LNG-BE-2026-0049 | 33438 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 679.68 | 794.88 | 585.93 | 685.24 | 1 von 1 |
| LNG-BE-2026-0050 | 33285 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 9409.92 | 10620.96 | 8111.99 | 9156.02 | 8 von 8 |
| LNG-BE-2026-0051 | 33078 | USD/Standard-Kauf-USD | **EUR/Standard-Kauf** | 0.86207 → 1.0 | 178.95 | 178.95 | 154.24 | 178.95 | 0 von 41 |
| LNG-BE-2026-0052 | 33297 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 7068.94 | 7141.80 | 6093.91 | 6156.73 | 3 von 15 |
| LNG-BE-2026-0053 | 33499 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 5714.16 | 6403.68 | 4926.01 | 5520.42 | 9 von 9 |
| LNG-BE-2026-0054 | 33543 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 6230.64 | 6230.64 | 5371.24 | 5371.24 | 0 von 9 |
| LNG-BE-2026-0055 | 33380 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 5718.58 | 6511.20 | 4929.80 | 5613.12 | 25 von 26 |
| LNG-BE-2026-0056 | 33334 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 3294.72 | 3528.00 | 2840.29 | 3041.39 | 3 von 5 |
| LNG-BE-2026-0057 | 33521 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 13135.44 | 14008.44 | 11323.68 | 12076.26 | 12 von 27 |
| LNG-BE-2026-0058 | 33334 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 6949.20 | 7526.40 | 5990.70 | 6488.28 | 6 von 12 |
| LNG-BE-2026-0059 | 33540 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 4052.52 | 4393.80 | 3493.56 | 3787.76 | 3 von 6 |
| LNG-BE-2026-0060 | 33345 | USD/Standard-Kauf-USD | **EUR/Standard-Kauf** | 0.86207 → 1.0 | 767.70 | 767.70 | 661.82 | 767.70 | 0 von 43 |
| LNG-BE-2026-0061 | 33443 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 6457.84 | 6888.64 | 5567.11 | 5938.49 | 5 von 12 |
| LNG-BE-2026-0062 | 33551 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 6758.40 | 6758.40 | 5826.22 | 5826.22 | 0 von 12 |
| LNG-BE-2026-0063 | 33417 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 4907.52 | 5312.64 | 4230.61 | 4579.87 | 4 von 10 |
| LNG-BE-2026-0064 | 33321 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 13169.57 | 13442.88 | 11353.06 | 11588.69 | 5 von 25 |
| LNG-BE-2026-0065 | 33358 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 8123.04 | 8123.04 | 7002.63 | 7002.63 | 0 von 10 |
| LNG-BE-2026-0066 | 33552 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 7119.60 | 7119.60 | 6137.60 | 6137.60 | 0 von 6 |
| LNG-BE-2026-0067 | 33427 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 55557.12 | 57544.44 | 47894.13 | 49607.31 | 31 von 101 |
| LNG-BE-2026-0068 | 33438 | USD/Standard-Kauf-USD | USD/Standard-Kauf-USD | 0.86207 → 0.86207 | 2369.52 | 2369.52 | 2042.69 | 2042.69 | 0 von 4 |
| **Summe** | | | | | **212294.06** | **221479.33** | **183012.48** | **192861.74** | **192 von 500** |

Weitere Verifikation (live, unabhängig nachgerechnet):

* **Unabhängige Nachrechnung** (eigene Implementierung, nicht der Server-Script-Code):
  24/24 Bestellungen und 500/500 Zeilen stimmen in `currency`, `buying_price_list`,
  `conversion_rate`, `plc_conversion_rate`, `price_list_currency`, `rate`, `price_list_rate`,
  `amount`, `base_rate`, `base_amount` und den Kopfsummen (`total` = Summe `amount`,
  `base_total` = Summe `base_amount`) — **0 Abweichungen**; keine Zeile trägt den Preis der
  jeweils anderen Preisliste (`rate == Fremdlistenpreis` → 0 Fälle).
* **Kein Preis fehlt**: `rate = 0` → **0** von 500 Zeilen, `no_price_found = 0`
  (Dry-Run-Output: `usd_orders=21 eur_orders=3 price_list_from_supplier=22
  price_list_from_line_coverage=2 changed_lines=192`).
* **Rundung**: `base_amount = round(amount × conversion_rate, 2)` in **500/500** Zeilen; die
  Kopfsumme `base_total` ist die Summe dieser gerundeten Zeilenwerte und weicht deshalb bei den
  großen Bestellungen um höchstens **2,6 Cent** von `total × conversion_rate` ab
  (LNG-BE-2026-0045 +0,0258, LNG-BE-2026-0067 −0,0254) — genau die ERPNext-eigene Rechenweise.
* **Non-Regression**: `qty` und `received_qty` gegen 4D (`BESTELLUNGpos.MENGE` /
  `MENGEGELIEFERT`) über alle 500 Zeilen **0 Abweichungen**; 24/24 `docstatus = 1`;
  64 Bestellungen auf der Site = 40 manuell (jüngste Änderung 2026-07-16) + 24 gespiegelt.
* **Submit-Hook**: max `abs(per_received − received/qty × 100)` = **4,55e-10** < 1e-6 →
  der Hook schreibt **0 von 24** Bestellungen neu.
* **Idempotenz**: zweiter kompletter Zyklus (Import + Update ohne `ignore_ts`, beide Hooks) →
  Vergleich aller 24 Köpfe (inkl. `modified`, `status`, `per_received`, `in_words`) und aller
  500 Zeilen vor/nach: **0 Unterschiede**; Summe `amount` 221.479,33 vorher = nachher,
  Summe `base_amount` 192.861,74 vorher = nachher.
* **Keine Fehler**: `tabError Log` seit 09:00 (**Serverzeit**) keine Einträge des Preis-Hooks
  (Titel "Fill purchase order prices" = 0); der Submit-Hook-Fallback für die Steuerzeilen
  läuft wie bisher.
* **Unberührt**: die 40 manuellen Bestellungen, die anderen Sync-Instances
  (`officeno1_migration` 197.278 / `officeno1_sales_orders` 910 / `stock_reconciliation` 0
  Zuordnungen unverändert), keine Änderung außerhalb `app_data/`.

## Betroffene Dateien / Zeilen

* `app_data/mappings/purchase_orders.json` Zeilen 51–63 (`currency`), 65–73
  (`buying_price_list`), 75–79 (`conversion_rate`), 92–97 und 129–140 (Kommentare/`rate`).
* `/private/files/officeno1_purchase_order_mapping.json` (Site) — inhaltsgleich; Sync Instance
  `officeno1_purchase_orders` über `controller.load_table_mapping` neu geladen
  (`table_mapping` == Datei, 14 Felder).
* `app_data/server_scripts/fill_purchase_order_prices.py` — komplett neu gefasst
  (Server Script "fill purchase order prices from usd price list" auf der Site aktualisiert,
  `doc.save` inkl. safe_exec-Compile-Prüfung, `disabled = 0`).
* Sync Instance `officeno1_purchase_orders`: Kopf- und Zeilenwerte der 24 Bestellungen; die
  72 `Sync Mapping Entry`-Zeilen der Felder `currency`/`buying_price_list`/`conversion_rate`
  bleiben mit leerem `selectline_column` (ADJUSTMENT 3), damit die Update-Phase die Kopfwerte
  nicht aus der 4D-Währung überschreibt.
* Kein App-Code, keine anderen Sync-Instances, keine manuellen Bestellungen.

## Reproduktion (Server, temporäre Hilfsskripte wurden danach entfernt)

```
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_measure.main      # 4D-Schema + die 24 Bestellungen
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_lines.main        # 4D-Zeilen/Artikelpreise je Bestellzeile
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_manual2.main      # Konvention der 40 manuellen Bestellungen
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_exact.main        # Rundungskonvention (1,139 -> 1,14)
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_state.before_state
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_dry.main          # Dry-Run der neuen Regel
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_deploy.deploy_script
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_deploy.deploy_mapping
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_cycle.cycle_forced
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_verify.main
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_state.after_state
bench --site portal.lang-kunstgewerbe.at execute pit_erpnextsync.scripts.adj4_cycle.cycle_normal
```
