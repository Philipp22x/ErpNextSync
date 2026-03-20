# SelectLine Database Structure Knowledge Base

## Overview

This document provides comprehensive documentation of the SelectLine ERP database structure as used in the Hellatex implementation. SelectLine is a German ERP system that uses Microsoft SQL Server as its database backend.

**Database:** SL_M100  
**Total Tables:** 494  
**Schema:** dbo  
**Last Updated:** 2026-03-13

---

## Table of Contents

1. [Core Master Data Tables](#core-master-data-tables)
   - [ART - Articles/Items](#art---articlesitems)
   - [ADRESS - Addresses/Contacts](#adress---addressescontacts)
   - [DEBITOREN - Customers](#debitoren---customers)
   - [KREDITOREN - Suppliers](#kreditoren---suppliers)
2. [Variant Management](#variant-management)
   - [ARTVARI - Article Variants](#artvari---article-variants)
   - [MERKMAL - Attributes](#merkmal---attributes)
   - [MERKMALD - Attribute Values](#merkmald---attribute-values)
3. [Sales & Orders](#sales--orders)
   - [BELEG - Documents/Orders](#beleg---documentsorders)
   - [BELEGP - Document Positions](#belegp---document-positions)
4. [Common Field Patterns](#common-field-patterns)
5. [Data Type Mapping](#data-type-mapping)
6. [Relationship Diagrams](#relationship-diagrams)

---

## Core Master Data Tables

### ART - Articles/Items

**Primary Key:** `ART_ID` (int, NOT NULL)  
**Business Key:** `Artikelnummer` (nvarchar(40), NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The ART table is the central article/item master containing all product information.

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| ART_ID | int | Technical primary key | - |
| Artikelnummer | nvarchar(40) | Article number (business key) | item_code |
| EANNummer | nvarchar(18) | EAN/Barcode | barcode |
| Bezeichnung | nvarchar(80) | Description | item_name |
| Zusatz | nvarchar(80) | Additional description | description |
| Matchcode | nvarchar(80) | Search code | custom_matchcode |
| Artikelgruppe | nvarchar(13) | Article group | item_group |
| Mengeneinheit | nvarchar(10) | Unit of measure | stock_uom |
| Gewicht | float | Weight | weight_per_unit |
| Lagerartikel | bit | Stock item flag | is_stock_item |
| Stueckliste | nvarchar(1) | Bill of materials type | - |
| Variantenartikel | nvarchar(40) | Parent variant article | variant_of |
| Hersteller | nvarchar(13) | Manufacturer | manufacturer |
| Lieferant | nvarchar(13) | Default supplier | supplier |
| Inaktiv | bit | Inactive flag | disabled |

#### Variant-Related Fields

| Field | Type | Description |
|-------|------|-------------|
| Variantenartikel | nvarchar(40) | If set, this is a variant of the specified parent article |
| Stueckliste | nvarchar(1) | 'V' = Variant parent (has variants), 'S' = Standard BOM |

**Important:** Articles with `Stueckliste = 'V'` are variant parents (have `has_variants = 1` in ERPNext). Articles with `Variantenartikel` set are child variants.

#### Accounting Fields

| Field | Type | Description |
|-------|------|-------------|
| SSEinkauf | nvarchar(2) | Purchase tax code |
| KontoEinkauf | nvarchar(15) | Purchase account |
| SSVerkauf | nvarchar(2) | Sales tax code |
| KontoVerkauf | nvarchar(15) | Sales account |
| Erfolgskontengruppe | nvarchar(6) | Revenue account group |
| Aufwandskontengruppe | nvarchar(6) | Expense account group |

#### Full Column List

```
ART_ID: int NOT NULL
Artikelnummer: nvarchar(40) NOT NULL
EANNummer: nvarchar(18)
Bezeichnung: nvarchar(80)
Zusatz: nvarchar(80)
Matchcode: nvarchar(80)
Artikelgruppe: nvarchar(13)
Erfolgskontengruppe: nvarchar(6)
Aufwandskontengruppe: nvarchar(6)
Mengenstaffel: nvarchar(6)
SSEinkauf: nvarchar(2)
KontoEinkauf: nvarchar(15)
SSVerkauf: nvarchar(2)
KontoVerkauf: nvarchar(15)
Mengeneinheit: nvarchar(10)
Preismengeneinheit: nvarchar(10)
Preismengenfaktor: float
Preisverweis: nvarchar(40)
Preiseinheit: float
Gewicht: float
Lagerartikel: bit
LosgroesseVerkauf: float NOT NULL
Mengenformel: nvarchar(6)
Stueckliste: nvarchar(1)
SerieCharge: nvarchar(1)
Variantenartikel: nvarchar(40)
MinusWarnung: bit
Provisionsfaehig: bit
Rabattfaehig: bit
Skontofaehig: bit
Provisionsgruppe: nvarchar(4)
Hersteller: nvarchar(13)
HstArtikelnummer: nvarchar(40)
Lieferant: nvarchar(13)
Dispositionsart: nvarchar(1)
AutoBestellung: nvarchar(1)
Lagerstrategie: nvarchar(1)
Auslaufdatum: datetime
Bestandsauswahl: bit NOT NULL
Inaktiv: bit NOT NULL
AngelegtAm: datetime
AngelegtVon: nvarchar(2)
GeaendertAm: datetime
GeaendertVon: nvarchar(2)
FreierText1: nvarchar(80)
FreierText2: nvarchar(80)
FreieZahl1: smallint
FreieZahl2: smallint
FreieZahl3: float
FreieZahl4: float
FreiesDatum1: datetime
FreiesDatum2: datetime
FreiesKennzeichen1: bit
FreiesKennzeichen2: bit
FreiesKennzeichen3: bit
FreiesKennzeichen4: bit
SSEG: nvarchar(2)
SSImport: nvarchar(2)
SSExport: nvarchar(2)
ShopAktiv: bit
Ursprungsland: nvarchar(2)
Warencode: nvarchar(8)
Kostenstelle: nvarchar(15)
Kostentraeger: nvarchar(15)
DNExport: nvarchar(1)
Ausschussartikelnummer: nvarchar(40)
Produktionslager: nvarchar(10)
AusschussBewertung: float
Verfallsfrist: int
TS: timestamp NOT NULL
_BGEFAEHRBT: float
_BROHWARE: float
_BZUSCHNITT: float
_DGEWICHT: float
_FARBCODE: nvarchar(20)
_GEFAEHRBT: nvarchar(20)
_QUALITAET: nvarchar(20)
_ROHWARE: nvarchar(20)
_TYP: nvarchar(20)
_ZOLLTARIFNUMMER: nvarchar(20)
_ZUSCHNITT: nvarchar(20)
_BREITE: float
_LAENGE: float
_AUSLAUFARTIKEL: bit
_ETIKETTENPREIS: float
Leistungsartikel: bit
Aufschlagstyp: nvarchar(1)
_QVCART: nvarchar(20)
ArbeitsplanID: nvarchar(18)
AuftragsTypID: nvarchar(18)
Wiederbeschaffung: nvarchar(1) NOT NULL
Wiederbeschaffungsdauer: int NOT NULL
Vorlauftage: int NOT NULL
Zollbeschreibung: nvarchar(40)
MakeOrBuy: nvarchar(1) NOT NULL
_ALTEARTIKELNUMMER: nvarchar(18)
_ARTIKELNURNUMMER: nvarchar(18)
_ARTIKELNUMMERSUCHE: nvarchar(254)
_SOLLISTMANUELL: bit
```

---

### ADRESS - Addresses/Contacts

**Primary Key:** `ADRESS_ID` (int, NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The ADRESS table stores all address and contact information for customers, suppliers, and other business partners.

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| ADRESS_ID | int | Technical primary key | - |
| Adresse | int | Address number | - |
| Adresstyp | nvarchar(20) | Address type | - |
| Anrede | nvarchar(30) | Salutation | salutation |
| Titel | nvarchar(30) | Title | designation |
| Vorname | nvarchar(40) | First name | first_name |
| Name | nvarchar(80) | Last name/Company | last_name/customer_name |
| Zusatz | nvarchar(80) | Additional info | - |
| Zusatz2 | nvarchar(80) | Additional info 2 | - |
| Zusatz3 | nvarchar(80) | Additional info 3 | - |
| Firma | nvarchar(80) | Company name | company_name |
| Funktion | nvarchar(30) | Job function | designation |
| Abteilung | nvarchar(30) | Department | department |
| Strasse | nvarchar(80) | Street | address_line1 |
| PLZ | nvarchar(10) | Postal code | pincode |
| Ort | nvarchar(40) | City | city |
| Land | nvarchar(6) | Country | country |
| Postfach | nvarchar(20) | PO Box | - |
| PostfachPLZ | nvarchar(10) | PO Box ZIP | - |
| PostfachOrt | nvarchar(40) | PO Box City | - |
| PostfachLand | nvarchar(6) | PO Box Country | - |
| Telefon | nvarchar(30) | Phone | phone |
| Telefon2 | nvarchar(30) | Phone 2 | phone_ext |
| Telefon3 | nvarchar(30) | Phone 3 | mobile_no |
| Fax | nvarchar(30) | Fax | fax |
| EMail | nvarchar(80) | Email | email_id |
| HomePage | nvarchar(80) | Website | website |
| ILNNummer | nvarchar(35) | ILN/GLN number | - |

#### Full Column List

```
ADRESS_ID: int NOT NULL
Adresse: int
Adresstyp: nvarchar(20)
Briefanrede: nvarchar(50)
Anrede: nvarchar(30)
Vorname: nvarchar(40)
Name: nvarchar(80)
Zusatz: nvarchar(80)
Strasse: nvarchar(80)
Land: nvarchar(6)
PLZ: nvarchar(10)
Ort: nvarchar(40)
Telefon: nvarchar(30)
Telefon2: nvarchar(30)
Telefon3: nvarchar(30)
Fax: nvarchar(30)
EMail: nvarchar(80)
HomePage: nvarchar(80)
Firma: nvarchar(80)
Funktion: nvarchar(30)
Abteilung: nvarchar(30)
Prioritaet: int
Verweis: int
ILNNummer: nvarchar(35)
TS: timestamp NOT NULL
Titel: nvarchar(30)
Zusatz2: nvarchar(80)
Zusatz3: nvarchar(80)
Postfach: nvarchar(20)
PostfachOrt: nvarchar(40)
PostfachPLZ: nvarchar(10)
PostfachLand: nvarchar(6)
```

---

### DEBITOREN - Customers

**Primary Key:** `KUNDEN_ID` (int, NOT NULL)  
**Business Key:** `Nummer` (nvarchar(13), NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The DEBITOREN table contains all customer master data.

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| KUNDEN_ID | int | Technical primary key | - |
| Nummer | nvarchar(13) | Customer number | name/customer_name |
| Gruppe | nvarchar(6) | Customer group | customer_group |
| Mitarbeiter | nvarchar(6) | Employee responsible | account_manager |
| Vertreter | nvarchar(6) | Sales representative | sales_partner |
| Sprache | nvarchar(6) | Language | language |
| Fibukonto | nvarchar(15) | GL account | - |
| Steuernummer | nvarchar(20) | Tax number | tax_id |
| SteueridentNr | nvarchar(20) | VAT ID | tax_id |
| Zahlungsbedingung | nvarchar(2) | Payment terms | payment_terms |
| Kreditlimit | float | Credit limit | credit_limit |
| SonderRabatt | float | Special discount | - |
| Preisgruppe | nvarchar(2) | Price group | - |
| PreisTyp | nvarchar(1) | Price type | - |
| Rabattgruppe | nvarchar(6) | Discount group | - |
| Waehrung | nvarchar(3) | Currency | default_currency |
| Lieferbedingung | nvarchar(6) | Delivery terms | - |
| Lager | nvarchar(10) | Default warehouse | default_warehouse |
| Mahnsperre | bit | Dunning block | - |

#### Full Column List

```
KUNDEN_ID: int NOT NULL
Nummer: nvarchar(13) NOT NULL
Gruppe: nvarchar(6)
Mitarbeiter: nvarchar(6)
Vertreter: nvarchar(6)
Kostenstelle: nvarchar(15)
Sprache: nvarchar(6)
EigeneNummer: nvarchar(15)
Fibukonto: nvarchar(15)
Kontengruppe: nvarchar(6)
Steuernummer: nvarchar(20)
SteueridentNr: nvarchar(20)
Zahlungsbedingung: nvarchar(2)
AutoZahlung: nvarchar(1)
Kreditlimit: float
SonderRabatt: float
Mindestbestellwert: float
Mahnsperre: bit
Preisgruppe: nvarchar(2)
PreisTyp: nvarchar(1)
Rabattgruppe: nvarchar(6)
Waehrung: nvarchar(3)
Lieferbedingung: nvarchar(6)
Lager: nvarchar(10)
... (72 columns total)
```

---

### KREDITOREN - Suppliers

**Primary Key:** `LIEFER_ID` (int, NOT NULL)  
**Business Key:** `Nummer` (nvarchar(13), NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The KREDITOREN table contains all supplier/vendor master data.

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| LIEFER_ID | int | Technical primary key | - |
| Nummer | nvarchar(13) | Supplier number | name/supplier_name |
| Gruppe | nvarchar(6) | Supplier group | supplier_group |
| Mitarbeiter | nvarchar(6) | Employee responsible | account_manager |
| Vertreter | nvarchar(6) | Representative | - |
| Sprache | nvarchar(6) | Language | language |
| Fibukonto | nvarchar(15) | GL account | - |
| Steuernummer | nvarchar(20) | Tax number | tax_id |
| SteueridentNr | nvarchar(20) | VAT ID | tax_id |
| Zahlungsbedingung | nvarchar(2) | Payment terms | payment_terms |
| Kreditlimit | float | Credit limit | credit_limit |
| Waehrung | nvarchar(3) | Currency | default_currency |

---

## Variant Management

### ARTVARI - Article Variants

**Primary Key:** `ARTVARI_ID` (int, NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The ARTVARI table is a junction table that links articles to their variant attributes. It connects articles with their characteristics (MERKMAL) and characteristic values (MERKMALD).

#### Fields

| Field | Type | Description | Foreign Key |
|-------|------|-------------|-------------|
| ARTVARI_ID | int | Technical primary key | - |
| Typ | nvarchar(1) | Type | - |
| Artikelnummer | nvarchar(40) | Article number | ART.Artikelnummer |
| IdMerkmal | int | Attribute ID | MERKMAL.Id |
| IdAuspraegung | int | Attribute value ID | MERKMALD.Id |
| TS | timestamp | Timestamp | - |

#### Relationships

```
ART (parent variant with Stueckliste = 'V')
  ↓ (1:N via Artikelnummer)
ARTVARI
  ↓ (N:1 via IdMerkmal)
MERKMAL (attribute definition)
  ↓ (1:N via IdMerkmal)
MERKMALD (attribute values)
  ↑ (N:1 via IdAuspraegung)
ARTVARI
```

#### Usage in ERPNext

In ERPNext, variant attributes are stored as a child table `attributes` in the Item DocType:

```json
{
    "fieldname": "attributes",
    "multiple_query": true,
    "multiple_query_table": "ARTVARI A1 INNER JOIN MERKMALD A2 ON A1.IdAuspraegung = A2.Id",
    "multiple_query_condition": "A1.Artikelnummer = {sl_column:Artikelnummer}",
    "table_fields": [
        {
            "table_fieldname": "attribute",
            "sl_column": "A1.IdMerkmal"
        },
        {
            "table_fieldname": "attribute_value",
            "sl_column": "A2.Bezeichnung"
        }
    ]
}
```

---

### MERKMAL - Attributes

**Primary Key:** `MERKMAL_ID` (int, NOT NULL)  
**Business Key:** `Id` (int)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The MERKMAL table defines product attributes/characteristics (like "Color", "Size", "Material").

#### Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| MERKMAL_ID | int | Technical primary key | - |
| Id | int | Attribute ID (business key) | name |
| Bezeichnung | nvarchar(40) | Attribute name | attribute_name |
| TS | timestamp | Timestamp | - |

#### Example

```
Id | Bezeichnung
---|------------
1  | Farbe
2  | Größe
3  | Material
```

---

### MERKMALD - Attribute Values

**Primary Key:** `MERKMALD_ID` (int, NOT NULL)  
**Business Key:** `Id` (int)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The MERKMALD table contains the possible values for each attribute defined in MERKMAL.

#### Fields

| Field | Type | Description | Foreign Key | ERPNext Mapping |
|-------|------|-------------|-------------|-----------------|
| MERKMALD_ID | int | Technical primary key | - | - |
| Id | int | Value ID (business key) | - | - |
| IdMerkmal | int | Parent attribute ID | MERKMAL.Id | - |
| Bezeichnung | nvarchar(40) | Value name | - | attribute_value |
| Kuerzel | nvarchar(3) | Abbreviation | - | abbr |
| TS | timestamp | Timestamp | - | - |

#### Example

```
Id | IdMerkmal | Bezeichnung | Kuerzel
---|-----------|-------------|--------
1  | 1         | Rot         | RT
2  | 1         | Blau        | BL
3  | 2         | Klein       | KL
4  | 2         | Groß        | GR
```

---

## Sales & Orders

### BELEG - Documents/Orders

**Primary Key:** `BELEG_ID` (int, NOT NULL)  
**Business Key:** `Belegtyp` + `Belegnummer`  
**Timestamp:** `TS` (timestamp, NOT NULL)

The BELEG table contains all business documents (orders, invoices, quotes, etc.).

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| BELEG_ID | int | Technical primary key | - |
| Belegtyp | nvarchar(1) | Document type | - |
| Belegnummer | nvarchar(10) | Document number | name |
| Datum | datetime | Document date | transaction_date |
| Adressnummer | nvarchar(13) | Customer/Supplier number | customer |
| Name | nvarchar(80) | Customer name | customer_name |
| Anrede | nvarchar(30) | Salutation | - |
| Vorname | nvarchar(40) | First name | - |
| Zusatz | nvarchar(80) | Additional info | - |
| Strasse | nvarchar(80) | Street | address_display |
| Land | nvarchar(6) | Country | - |
| Plz | nvarchar(10) | Postal code | - |
| Ort | nvarchar(40) | City | - |
| Preisgruppe | nvarchar(2) | Price group | - |
| PreisTyp | nvarchar(1) | Price type | - |
| Rabattgruppe | nvarchar(6) | Discount group | - |
| Belegrabatt | float | Document discount | additional_discount_percentage |
| Zahlungsbedingung | nvarchar(2) | Payment terms | payment_terms_template |
| Waehrung | nvarchar(3) | Currency | currency |
| Kurs | float | Exchange rate | conversion_rate |
| Gesamtbetrag | float | Total amount | grand_total |
| Nettobetrag | float | Net amount | net_total |
| Steuerbetrag | float | Tax amount | total_taxes_and_charges |
| Gedruckt | bit | Printed flag | - |
| Barverkauf | bit | Cash sale flag | is_pos |

#### Document Types (Belegtyp)

| Type | Description | ERPNext DocType |
|------|-------------|-----------------|
| A | Offer/Quote | Quotation |
| B | Order Confirmation | - |
| F | Invoice | Sales Invoice |
| L | Delivery Note | Delivery Note |
| R | Credit Memo | Sales Invoice (is_return=1) |
| V | Order | Sales Order |
| X | Cancellation | - |

---

### BELEGP - Document Positions

**Primary Key:** `BELEGP_ID` (int, NOT NULL)  
**Timestamp:** `TS` (timestamp, NOT NULL)

The BELEGP table contains the line items/positions for each document in BELEG.

#### Key Fields

| Field | Type | Description | ERPNext Mapping |
|-------|------|-------------|-----------------|
| BELEGP_ID | int | Technical primary key | - |
| Belegtyp | nvarchar(1) | Document type | - |
| Belegnummer | nvarchar(10) | Document number | parent |
| Posnummer | int | Position number | idx |
| Postext | nvarchar(15) | Position text | - |
| Zeilentyp | nvarchar(1) | Line type | - |
| Umsatz | nvarchar(1) | Revenue type | - |
| Menge | float | Quantity | qty |
| Eingabemenge | float | Input quantity | - |
| EditMenge | nvarchar(80) | Edited quantity | - |
| Artikelnummer | nvarchar(40) | Article number | item_code |
| WarenCode | nvarchar(8) | Commodity code | - |
| Bestellnummer | nvarchar(40) | Order number | - |
| Bezeichnung | nvarchar(80) | Description | description |
| Zusatz | nvarchar(80) | Additional text | - |
| Mengeneinheit | nvarchar(10) | Unit of measure | uom |
| Preismengeneinheit | nvarchar(10) | Price UOM | - |
| Preismenge | float | Price quantity | - |
| Gewicht | float | Weight | total_weight |
| Kalkulationspreis | float | Cost price | valuation_rate |
| Einzelpreis | float | Unit price | rate |
| Preiseinheit | float | Price unit | - |
| Rabatt | float | Discount | discount_percentage |
| Rabatt2 | float | Discount 2 | - |
| Gesamtpreis | float | Total price | amount |
| Netto | float | Net amount | net_amount |
| Steuer | float | Tax amount | tax_amount |
| Steuerprozent | float | Tax percent | tax_rate |
| Steuerklasse | nvarchar(2) | Tax class | item_tax_template |
| Lager | nvarchar(10) | Warehouse | warehouse |
| Seriennummer | nvarchar(30) | Serial number | serial_no |
| Charge | nvarchar(20) | Batch number | batch_no |

#### Line Types (Zeilentyp)

| Type | Description |
|------|-------------|
| A | Article/Item |
| T | Text line |
| S | Subtotal |
| G | Grand total |
| Z | Page break |

---

## Common Field Patterns

### Timestamp Fields

All tables have a `TS` field of type `timestamp` (rowversion in SQL Server) used for:
- Optimistic locking
- Change tracking
- Incremental synchronization

**Mapping:**
```json
{
    "timestamp_column_name": "TS",
    "timestamp_column_type": "rowversion"
}
```

### Audit Fields

Most tables contain standard audit fields:

| Field | Type | Description |
|-------|------|-------------|
| AngelegtAm | datetime | Created on |
| AngelegtVon | nvarchar(2) | Created by (user code) |
| BearbeitetAm | datetime | Modified on |
| BearbeitetVon | nvarchar(2) | Modified by (user code) |

### Naming Conventions

- **Primary Keys:** Always named `{TABLE}_ID` (e.g., `ART_ID`, `KUNDEN_ID`)
- **Foreign Keys:** Usually named `{ReferencedTable}ID` or descriptive (e.g., `IdMerkmal`, `Artikelnummer`)
- **Business Keys:** Often `Nummer` (number) or `{Table}nummer` (e.g., `Artikelnummer`, `Belegnummer`)
- **Descriptions:** Usually `Bezeichnung`
- **Additional Info:** Usually `Zusatz` or `Zusatz2`, `Zusatz3`

---

## Data Type Mapping

### SQL Server to ERPNext/Python

| SQL Server Type | Python Type | ERPNext Type | Notes |
|-----------------|-------------|--------------|-------|
| int | int | Int | Integer values |
| bigint | int | Int | Large integers |
| smallint | int | Int | Small integers |
| tinyint | int | Int | 0-255 |
| bit | bool | Check | Boolean (0/1) |
| float | float | Float | Floating point |
| decimal/numeric | Decimal | Currency | Monetary values |
| nvarchar(n) | str | Data | Unicode strings |
| varchar(n) | str | Data | ASCII strings |
| datetime | datetime | DateTime | Date and time |
| date | date | Date | Date only |
| timestamp | bytes | - | Rowversion/binary |
| text | str | Text | Long text |
| nvarchar(MAX) | str | Text | Unlimited text |

### Special Handling

#### Timestamp/Rowversion
```python
# Convert rowversion to hex string for comparison
timestamp_hex = timestamp.hex() if timestamp else None
```

#### Bit Fields
```python
# Convert SQL bit to Python bool
is_active = bool(sql_bit_value) if sql_bit_value is not None else False
```

#### Decimal/Money
```python
# Use Decimal for precise monetary calculations
from decimal import Decimal
price = Decimal(str(sql_float_value))
```

---

## Relationship Diagrams

### Article Variant Hierarchy

```
┌─────────────────┐
│   ART (Parent)  │
│  Stueckliste='V'│
│  has_variants=1 │
└────────┬────────┘
         │ Artikelnummer
         │
         ▼
┌─────────────────┐
│     ARTVARI     │
│  (Junction)     │
│                 │
│  IdMerkmal ─────┼──► MERKMAL
│  IdAuspraegung ─┼──► MERKMALD
└─────────────────┘
         │
         │ Artikelnummer
         │
┌────────┴────────┐
│   ART (Child)   │
│ Variantenartikel│
│  = Parent.ArtNr │
│  has_variants=0 │
└─────────────────┘
```

### Order Document Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   DEBITOREN │     │    BELEG    │     │   BELEGP    │
│  (Customer) │────►│ (Document)  │◄────│ (Positions) │
│             │     │             │     │             │
│   Nummer    │     │  Belegtyp   │     │  Belegtyp   │
│             │     │ Belegnummer │     │ Belegnummer │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                     │
                           │                     │ Artikelnummer
                           │                     │
                           ▼                     ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   Status    │     │    ART      │
                    │   History   │     │  (Article)  │
                    └─────────────┘     └─────────────┘
```

### Address Structure

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   ADRESS    │◄────│  DEBITOREN  │     │  KREDITOREN │
│  (Contact)  │     │  (Customer) │     │  (Supplier) │
│             │     │             │     │             │
│   Adresse   │     │   Nummer    │     │   Nummer    │
│             │     │             │     │             │
│  Vorname    │     │  Adressnummer
│  Name       │     │  (links to  │
│  Firma      │     │  ADRESS)    │
│  Strasse    │     └─────────────┘
│  PLZ/Ort    │
└─────────────┘
```

---

## Query Examples

### Get Article with Variants

```sql
-- Get parent variant article
SELECT * FROM ART 
WHERE Stueckliste = 'V' 
AND Artikelnummer = 'HTX31';

-- Get variant attributes
SELECT 
    a.Artikelnummer,
    m.Id AS AttributeID,
    m.Bezeichnung AS AttributeName,
    md.Bezeichnung AS AttributeValue,
    md.Kuerzel AS Abbreviation
FROM ARTVARI a
INNER JOIN MERKMAL m ON a.IdMerkmal = m.Id
INNER JOIN MERKMALD md ON a.IdAuspraegung = md.Id
WHERE a.Artikelnummer = 'HTX31';

-- Get child variant articles
SELECT * FROM ART 
WHERE Variantenartikel = 'HTX31';
```

### Get Customer with Addresses

```sql
-- Get customer master data
SELECT * FROM DEBITOREN 
WHERE Nummer = '10001';

-- Get customer addresses
SELECT * FROM ADRESS 
WHERE Adresse IN (
    SELECT Adressnummer FROM DEBITOREN 
    WHERE Nummer = '10001'
);
```

### Get Order with Positions

```sql
-- Get order header
SELECT * FROM BELEG 
WHERE Belegtyp = 'V' 
AND Belegnummer = '20001';

-- Get order lines
SELECT * FROM BELEGP 
WHERE Belegtyp = 'V' 
AND Belegnummer = '20001'
ORDER BY Posnummer;
```

---

## Synchronization Notes

### Incremental Sync Strategy

1. **Initial Load:** Full table scan with ORDER BY primary key
2. **Delta Sync:** Use TS (timestamp) field for change detection
3. **Conflict Resolution:** Last-write-wins based on timestamp

### Important Considerations

1. **Rowversion Handling:** SQL Server rowversion is binary - convert to hex string for comparison
2. **Soft Deletes:** SelectLine uses `Inaktiv` bit flag instead of hard deletes
3. **Document Flow:** BELEG documents have status changes (created → printed → posted)
4. **Variant Articles:** Always sync parent before children
5. **Address Links:** ADRESS records can be shared between customers/suppliers

### Performance Tips

1. **Indexing:** Primary keys are indexed, but business keys (Nummer, Artikelnummer) may need indexes
2. **Batch Size:** Use TOP clause for large tables
3. **Joins:** Prefer INNER JOIN over subqueries for better performance
4. **Filtering:** Always filter by indexed columns first

---

## Additional Tables Reference

### Article-Related Tables

| Table | Description | Relationship |
|-------|-------------|--------------|
| ARTKALK | Article pricing/calculation | 1:1 with ART |
| ARTPREIS | Article prices by customer/group | N:1 with ART |
| ARTLIEF | Article suppliers | N:1 with ART |
| ARTSET | Article sets/components | N:1 with ART |
| ARTBEZ | Article descriptions by language | N:1 with ART |
| ARTVARI | Article variant attributes | N:1 with ART |
| ARTSUCH | Article search words | N:1 with ART |
| ARTBILD | Article images | N:1 with ART |

### Inventory Tables

| Table | Description |
|-------|-------------|
| LAGER | Warehouses |
| LAGERBESTAND | Stock levels |
| LAGERBEWEGUNG | Stock movements |
| CHARGE | Batch numbers |
| SERIENNUMMER | Serial numbers |

### Financial Tables

| Table | Description |
|-------|-------------|
| FIBU | General ledger accounts |
| FIBUBUCHUNG | GL postings |
| KONTEN | Account master |
| ZAHLUNG | Payments |

---

*Document Version: 1.0*  
*Last Updated: 2026-03-13*  
*Maintained by: PIT ERPNextSync Team*
