# NH new construction & housing: data sources

Checked 2026-11-03 by downloading the files. Each source is marked **[verified]** (file fetched and parsed) or **[unverified]** (site blocked automated fetch or the link wasn't opened).

---

## 1. US Census Building Permits Survey (BPS), place level  [verified]

**Base:** `https://www2.census.gov/econ/bps/Place/Northeast%20Region/` (NH is state FIPS `33`, in the NE file with CT/ME/MA/NJ/NY/PA/RI/VT).

| File | Pattern | Example | Content |
|---|---|---|---|
| Annual | `ne{YYYY}a.txt` | `.../ne2025a.txt` | All permit offices, full year (estimates incl. imputation) + reported-only columns. 1980–2025 available. |
| Monthly current | `ne{YYMM}c.txt` | `.../ne2609c.txt` | That month only. |
| Monthly YTD | `ne{YYMM}y.txt` | `.../ne2609y.txt` | Jan–month YTD incl. late reports/corrections. |

- Format: CSV text (~850 KB per annual NE file). **Two header lines plus one blank line**, so skip 3 lines and assign your own column names. Fields are padded with spaces, so strip them. Zip codes and codes must be read as strings.
- Latest available: annual **2025** (file modified 2026-05-14). Monthly runs through **Sep 2026** (`ne2609c/y`, modified 2026-10-27). The monthly files update about the 3rd–4th week of the following month, and the annual file comes out each May.
- Docs: `https://www2.census.gov/econ/bps/Documentation/placeasc.pdf` (record layout and source codes).
- One file for every geography and every month: `https://www2.census.gov/econ/bps/Master%20Data%20Set/BPS_Compiled_File_202609.zip` (**654 MB**, tidy named columns such as `UNITS_1_UNIT`, `VALUE_5_UNITS`, `*_REP`, `SOURCE_CODE`, `NUMBER_OF_MONTHS_REP`, `LOCATION_TYPE`, `PERIOD`). Sample: `.../Master%20Data%20Set/Compiled%20File%20Sample.csv`. It's too big to fetch routinely. The per-region txt files are lighter.

**Column layout (annual `a` and YTD `y`, 41 cols; 0-indexed):**
`0 survey date (YYYY annual / YYYYMM ytd) | 1 state FIPS | 2 6-digit BPS ID | 3 county FIPS | 4 census place code | 5 FIPS place | 6 FIPS MCD | 7 pop | 8 CSA | 9 CBSA | 10 footnote | 11 central city | 12 zip | 13 region | 14 division | 15 number of months reported | 16 place name | 17-19 1-unit bldgs,units,value | 20-22 2-unit | 23-25 3-4 unit | 26-28 5+ unit | 29-40 same 12 fields, REPORTED-ONLY (no imputation)`

**Monthly current `c` (29 cols):** same through col 14, then `15 = source code` (instead of months reported), then name and the 12 bldgs/units/value fields. There are no reported-only columns.

Value = construction cost on the permit in $ (not assessed value). Every 1/2/3-4/5+ class has buildings, units, and $ valuation.

**Sample rows (units / $value):**

| Year | Place | 1-unit | 2-unit | 3-4 | 5+ | months rep. |
|---|---|---|---|---|---|---|
| 2025 | Londonderry town | 551 / $106.2M | 0 | 3 / $0.8M | 0 | 12 |
| 2025 | Manchester | 24 / $9.0M | 12 / $3.0M | 18 / $3.7M | 168 / $39.9M | **1** |
| 2025 | Salem town | 28 / $14.3M | 0 | 0 | 96 / $16.9M | **0** |
| 2024 | Londonderry | 20 / $8.6M | 10 | 3 | 300 / $56.0M | 12 |
| 2024 | Manchester | 26 / $10.2M | 10 | 28 | 129 / $32.2M | 12 |
| 2024 | Salem | 32 / $16.8M | 2 | 0 | 113 / $19.9M | 9 |
| 2018 | Londonderry | 46 / $11.5M | 8 | 0 | 68 / $5.4M | 1 |
| 2026 Jan–Sep (y) | Londonderry | 126 / $30.4M | 0 | 0 | 6 | 7 |

IDs (col 2): Londonderry `525000` (MCD 43220), Manchester `553000` (place/MCD 45140), Salem `777000` (MCD 66660).

**Gotchas:**
- **Imputation is heavy.** In the 2025 annual file, 34 of 220 NH places reported **0 months** and are entirely imputed (Salem 2025). Another 168 reported all 12 months. Imputed values repeat across years. For example, Londonderry's 2-unit row shows 4 bldgs/8 units/$1,866,864 in both 2018 and 2019 with 0 months reported. Use cols 15 and 29–40 to flag or exclude imputed data, and show an "estimated" badge.
- In the Sep-2026 monthly `c` file, **139 of 220 NH rows are source code 5 (no report, imputed)**. Treat recent months as provisional.
- **Monthly coverage changed in 2022.** Before Jan 2022 the monthly `c`/`y` files hold only about **76 NH places** (the monthly sample). From 2022-01 on they hold about 219–220. For 2018–2021, monthly data exists only for that subset, so **use the annual files for 2018–2021**.
- Outlier: Londonderry 2025 = 551 single-family units / $106M, about 10–25× its usual level, and the OPD file shows nothing comparable. It's flagged as fully reported, but check it with the town before publishing.
- NH has 220 BPS permit offices, while DRA lists about 259 municipalities and unincorporated places. Some small towns and unincorporated places don't issue permits. Join on FIPS MCD (col 6) to county-subdivision codes, not on name. Name strings carry suffixes ("Londonderry town", "Salem town", but "Manchester").
- Population (col 7) is a stale base, so don't use it.
- New privately-owned residential only. Demolitions, conversions, and manufactured homes aren't counted.
- Footnote files: `.../Place/footnote2018.xls`, `foot2017.txt` etc.

**API / tools:** The Census API (`api.census.gov/data.json`) has only `timeseries/eits/resconst`, which is national/regional with no place level. So there's **no place-level BPS API, and the flat files are the machine-readable route.** HUD SOCDS (`https://socds.huduser.gov/permits/`) is a query UI over the same BPS place data. It returned a bot challenge to curl [unverified].

---

## 2. NH DRA: valuation, equalization, tax rates  [verified 2018–2025]

**Access gotcha:** revenue.nh.gov returns **HTTP 403 to curl and WebFetch**, so non-browser clients are blocked. The files downloaded fine from a real browser session. The pipeline will probably need a browser-like client (Playwright), or you can download manually once a year. These are statewide single files with one row per municipality, so you don't need anything per town.

Index pages:
- Equalization hub: `https://www.revenue.nh.gov/about-dra/municipal-and-property-division/property-bureau/equalization` (links to the 2018–2025 year pages)
- Year pages: `https://www.revenue.nh.gov/about-dra/municipal-and-property-division/property-bureau/equalization/{YYYY}-equalization-reports` (2025 also at `/2025-equalization-reports`)
- Tax rates: `https://www.revenue.nh.gov/about-dra/municipal-and-property-division/municipal-and-property-reports/municipal-and-village`

File host prefix `https://www.revenue.nh.gov/sites/g/files/ehbemt736/files/`. **The paths aren't consistent from year to year** (`inline-documents/sonh/municipal-property/` vs `inline-documents/sonh/` vs `documents/`), so take them from the table below or scrape the year page.

### (a) Local assessed valuation (MS-1 summary): "Tables by County" xlsx
One row per municipality, from MS-1 data. Sheet `Alpha Order` (2019+; in 2018 it's the 2nd sheet), with county sheets as well.
Columns (2025): Municipality, RSA 79-A Current Use Land, 79-B, 79-C, 79-D land, 79-F land, **Residential Land, Commercial/Industrial Land, Residential Buildings, Manufactured Housing, Commercial/Industrial Buildings**, 79-D bldgs, 79-F structures, Public Water / Gas-Oil / Electric Utilities, Other, Mature Wood Timber, **Gross Valuation**, Educational & Special Exemptions, **Modified Assessed Valuation**, Blind/Elderly/Local Optional exemptions, **Net Valuation**, Gross Property Taxes, Veterans' Credits, **Net Tax Commitment, Tax Rate**, Residents Tax.

| Year | Tables by County (xlsx) |
|---|---|
| 2025 | `documents/2025-tables-by-county.xlsx` |
| 2024 | `documents/2024-tables-by-county.xlsx` |
| 2023 | `inline-documents/sonh/2023-tables-by-county.xlsx` |
| 2018–2022 | `inline-documents/sonh/municipal-property/{YYYY}-tables-by-county.xlsx` |

Sample, Londonderry Net Valuation: 2018 $3.97B → 2023 $6.31B → 2025 $7.38B. Residential Buildings 2025 $3.56B. Rate 2025 $14.47.

**New construction / net valuation change:** I found **no published new-construction figure.** The MS-1 summary tables have no new-construction line. As a proxy you can year-over-year diff Residential Buildings or Net Valuation, **but revaluation years swamp it.** Londonderry's ratio swings 97.7→72.9→90.3, so pair the diff with the equalization ratio, or flag years where the ratio jumps. The per-town MS-1 forms are filed through DRA's Assessment Web Portal and aren't published as data (some towns post their own PDFs).

### (b) Equalized valuation: "Equalization Survey" xlsx
Columns: Municipality, [County in 2018], Modified Local Assessed Valuation, DRA Inventory Adjustment, Equalized Assessed Valuation, Equalized PILOT, Equalized Railroad Tax, **Total Equalized Valuation**, Local Tax Rate, **Equalization Ratio**, **Full Value Tax Rate**, % proportion to county tax, % proportion to state tax. There are "including utilities" and "not including utilities" variants.

| Year | File |
|---|---|
| 2025 | **PDF only**: `documents/2025-equalization-survey-including-utilities.pdf`, `documents/2025-equalization-survey-without-utilities.pdf`. Use the 2025 Tax Rate Comparison xlsx instead, which has the ratio and equalized valuation both incl. and excl. utilities. |
| 2024, 2023 | `documents/{YYYY}-equalization-survey-including-utilities.xlsx` (and `-not-including-utilities.xlsx`) |
| 2018–2022 | `inline-documents/sonh/municipal-property/{YYYY}-equalization-survey-including-utilities.xlsx` |

Also: `documents/ratio-median-ratio-cod-prd-ten-year-history.xlsx` (2 MB, 10-yr ratio/median/COD/PRD) and `inline-documents/sonh/municipal-property/ratio-median-ratio-cod-prd-history-2018-2009.xlsx`.

### (c) Tax rates (total / municipal / school / state ed / county)
Best source: the **Tax Rate Comparison** xlsx, sheet `Alpha order`. The header is on row 2, and from 2025 on there's a leading County column. It has Ratio, Total Equalized Valuation (incl. utilities), Total Taxes Assessed, Vets credits, Net Commitment, **Total Rate**, **Local School rate** + equalized + $, Equalized Valuation excl. utilities, **State Education rate** + $, **County rate** + $, **Municipal rate** + $, and Precinct/Village taxes.

| Year | Tax Rate Comparison (xlsx) | Also |
|---|---|---|
| 2025 | `documents/tax-rate-comparison-template-2025.xlsx` | `documents/2025-municipal-and-village-district-tax-rates.xlsx` (simple: date set, valuation, municipal/county/state-ed/local-ed/total rate, commitment); `documents/2025-tax-rate-calculation-data.xlsx` (appropriations, tax effort, rates per component) |
| 2024 | `documents/2024-tax-rate-comparison.xlsx` | `documents/2024-municipal-and-village-tax-rates.xlsx`, `documents/2024-tax-rate-calculation-data.xlsx` |
| 2023 | `documents/2023-tax-rate-comparison.xlsx` | `inline-documents/sonh/municipal-property/2023-municipal-and-village-tax-rates.xlsx`, `inline-documents/sonh/2023-tax-rate-calculation-data.xlsx` |
| 2022 | `inline-documents/sonh/municipal-property/2022-tax-rate-comparison.xlsx` | `.../2022-municpal-and-village-tax-rates.xlsx` (sic), `.../2022-tax-rate-caluclation-data.xlsx` (sic) |
| 2021 | `documents/2021-tax-rate-comparison.xlsx` | `inline-documents/sonh/municipal-property/2021-municipal-and-village-tax-rates.xlsx`, `.../2021-tax-rate-calculation-data.xlsx` |
| 2018–2020 | `inline-documents/sonh/municipal-property/{YYYY}-tax-rate-comparison.xlsx` | — |
| 2026 | PDF only so far: `documents/2026-municipal-tax-rates.pdf` (rates are set Oct–Dec, so this list is partial) | |

Sample, Londonderry 2025: total $14.47 = municipal 3.53 + county 0.58 + state ed 1.08 + local school 9.28. Ratio 95.2. Equalized valuation $7.90B.

**DRA gotchas:**
- **2015–2017 aren't on the current site** (404). The old site (`revenue.nh.gov/mun-prop/property/equalization-2015/documents/…`) had **PDFs only** (`eqswu-county.pdf`, `tax-rate-comparison-alpha.pdf` etc.), confirmed for 2015 in the Wayback CDX index. Wayback was offline for 2016/2017 when I checked. Realistic machine-readable coverage is **2018–2025**.
- The "year" is the tax year (April 1 assessment, rate set in the fall). Equalization reports for year N come out the following year.
- Layout drift: the header row index, a leading County column (2018 eq survey, tax-rate comparisons 2018–2022 and 2025), sheet names with stray spaces (`" Alpha Order"`), a junk row `Column1..ColumnN` under some headers, and 804-row sheets with blank padding. Find columns by header text, not position.
- Names: "Albany (P)" style suffixes, trailing spaces ("Albany "), plus unincorporated places. Normalize before joining to BPS.
- Rows include county subtotal and total rows. Filter to municipality names.

---

## 3. NH OPD: "Current Estimates and Trends in NH's Housing Supply"  [verified]

- Page: `https://www.nheconomy.com/Office-of-Planning-and-Development/What-We-Do/State-Data-Center-(Census-Data)/Housing-Data`
- Report (2025 update, PDF): `https://www.nheconomy.com/getmedia/5dc2e148-8afc-45f8-bf15-17e7a559057f/FY26_BEA_Housing-Supply-Report_FINAL.pdf`
- **Data (CSV, 95 KB, 239 municipalities):** `https://www.nheconomy.com/getmedia/10c857cf-d7df-44e2-b7c2-8ad38c515a4a/hse2020-2025-Analysis-Share_1.csv`
- Source: OPD's annual municipal Dwelling Unit survey (form plus per-town data review sheets at `.../housing-data/dwelling-unit-survey`). Published once a year, around January.
- Content: for each town (cols `cousub` = county-subdivision FIPS, `Town`, `County`, RPC region) it has 2020 Census units, then **net permits per year 2020–2024 by type (SF, 2F, Conversions, 3-4, 5+, MH, total)** and estimated housing stock ("Total {YYYY} Built") by type through 2025.
- Sample, 2024 permits (OPD vs Census BPS): Londonderry SF 39, 5+ 305, total 372 (BPS: 20 SF, 300 5+). Salem SF 19, 5+ 0, total 40 (BPS imputed: 113 5+). Manchester total 364, 5+ 179 (BPS 129).
- **Gotchas:** The header block is 2 rows, and column names repeat (`SF`, `5+` appear many times), so map by position plus the group label in row 2. Numbers mix `"1,659"` strings and plain ints. Values can be negative (net of demolitions, MH removals). Units only, no $ value. Earlier vintages (`https://www.nh.gov/osi/data-center/documents/hse2020-2029.xlsx`, `hse2010-2019.xlsx`) returned 403 [unverified]. This source is useful as a cross-check on imputed BPS values, and it covers manufactured housing and demolitions.

NHHFA (`https://www.nhhousing.org/resources/housing-demographic-data/`): xlsx downloads are MLS listings, sales, and absorption (2009–present), plus a Power BI dashboard. **No permit or unit-count file by municipality.**

---

## 4. Individual large multifamily projects (brief)

- **InvestNH (BEA, ARPA)**: per-project awardee PDFs with project, municipality, county, total and affordable units. They're tables in PDF, so parse them with pdfplumber. [verified PDFs download]
  - Capital Grant: `https://www.nheconomy.com/getmedia/43d45069-b220-41f6-9576-d284ed75cb1e/InvestNH-CAP-Awardees-2-14-24.pdf`
  - Municipal Per-Unit: `https://nheconomy.com/getmedia/3fe5d9d7-e287-4ba4-b5db-e1e16ceabf66/InvestNH-MPerUnit-Awardees-2-11-25.pdf`
  - Programs index: `https://www.nheconomy.com/investnh-housing/programs`
- **NH Housing (NHHFA) LIHTC**: board award announcements (news posts) and score PDFs (e.g. `https://www.nhhfa.org/wp-content/uploads/2025/01/2025-LIHTC-Final-Scores-by-Category.pdf`). Project names and towns appear in prose or PDF, and there's no structured list. LIHTC page: `https://www.nhhousing.org/developer-financing/lihtc/`.
- **HUD LIHTC database** (`https://lihtc.huduser.gov/`): national property-level CSV/zip with address, lat/lon, and units, but it lags about 2 years. It returned a bot challenge to curl [unverified].
- No source gives addresses for market-rate permits. For those, use town planning board agendas and minutes (this project's crawler).

---

## Recommended pipeline mapping
1. **BPS annual `ne{YYYY}a.txt` 2018–2025** for units + $ by structure type, flagged by months reported. **BPS monthly `ne{YYMM}c.txt` from 2022-01** for current-year progress, plus the YTD `y` file.
2. **DRA Tables by County + Tax Rate Comparison xlsx 2018–2025** for assessed/net valuation, equalized valuation, ratio, and component rates.
3. **OPD CSV** to cross-check net units (2020–2024) and estimate housing stock.
4. Join key: FIPS county-subdivision (BPS col 6 MCD = OPD `cousub`). DRA has names only, so keep a name→FIPS crosswalk.
