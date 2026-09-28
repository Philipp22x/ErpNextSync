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

