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
