# New item sources for Kringum

Researched 2026-11-24. Three research agents checked 30+ candidate sources, mostly by opening the live site. Reviewed and updated the same day against the post-LMÍ `kringum.db` (10,266 active items), `Tools/`, and external copyright/source checks. Claims based only on a search result or memory are marked. Nothing has been imported yet.

**Recommendation:**
1. **Email for permission today** on **Dysjar hinna dæmdu (`dhd.hi.is`)**, **`stridsminjar.is`**, and **Árnastofnun** (Sagnagrunnur / Ísmús / `nafnið.is`). The first two are already geocoded, compact (~230 sites combined), and add fresh genres with minimal TTS overhead.
2. **Build a text-grounded saga pipeline** starting with **Eyrbyggja**, **Gísla**, **Fóstbræðra**, and **Grettis** (plus **Íslendingaþættir**)—these directly fill thin tourist regions (Snæfellsnes, Northern Westfjords) and outlaw stories.
3. **Curate Landnámabók selectively** (`score ≥ 4` stories only, ~150–250 winners) rather than bulk-importing dry settlement genealogies.

### Current DB baseline & real gaps (post-LMÍ curation)
- **Scale & TTS backlog:** `10,266` active items (`6,244` non-LMÍ + `4,022` newly curated LMÍ items still awaiting TTS audio rendering). High-signal, moderate-volume sets beat dumping thousands of routine farm pins.
- **Geographic gaps (all active items, including curated LMÍ):**
  - *Dense:* North Iceland (`3,347` — Mývatn/Húsavík/Eyjafjörður `1,741`, Skagafjörður/Húnavatnssýsla `1,365`), Golden Circle / Árnessýsla (`1,193`), **East Iceland (`1,304`** — Eastfjords `873`, Fljótsdalshérað `606`), Reykjavík (`831`).
  - *Actually thin:* **SE / Kirkjubæjarklaustur–Höfn (`242`)**, **Strandir (`246`)**, **NE / Langanes–Vopnafjörður (`293`)**, **Snæfellsnes (`318`)**, **Northern Westfjords (`327`)**, **Highlands (`374`)**.
- **Thematic balance:** Folklore and nature are already abundant (`álfar/huldufólk`: `1,423`; `laug/hver`: `2,344`; `Jón Árnason`: `386`), whereas dramatic historical categories are thin: `WWII/flugslys` (`100`), `sjóslys` (`81`), `aftökur/galdrabrennur` (`80`), `snjóflóð` (`69`), `vitar` (`69`), `eldgos` (`50`), `jarðskjálftar` (`48`), `útilegumenn` (`43`), `Spánverjavígin` (`9`).

---

## A. Ready to use now: public domain or open licence, clean text

### 1. Targeted Íslendingasögur & Íslendingaþættir
- **Text:**
  - Icelandic for all 40+ sagas and þættir: sagadb.org and snerpa.is/net/isl/isl.htm
  - Public-domain English on sagadb.org:
    - Morris & Magnússon: Eyrbyggja, Grettis, Hænsna-Þóris, Bandamanna, Heiðarvíga
    - Dasent: Gísla
    - Edmund Head: Víga-Glúms
    - Collingwood & Stefánsson: Kormáks
  - Vatnsdæla, Fóstbræðra and Reykdæla have no public-domain English, but the translation pipeline covers that.
- **Content:** roughly 20–80 places per saga. Prioritize by geographic/thematic impact:
  - **Eyrbyggja** → fills **Snæfellsnes** (`318` active items; currently 0 dedicated saga items, 14 passing mentions).
  - **Gísla** & **Fóstbræðra** → fill **Westfjords** (`327` in Northern Westfjords; currently 0 dedicated saga items, only 3 Gísla mentions).
  - **Grettis** → arguably the best driving-audio outlaw saga (currently 0 dedicated saga items, 77 passing mentions).
  - **Íslendingaþættir** → short saga tales, naturally bite-sized for audio and easy to anchor to 1–3 spots each.
- **Effort:** **medium (new pipeline needed).** `Tools/Sagas/import_sagas.py` **cannot** be reused as-is for extraction or geocoding: it only reads pre-authored JSON files, translates them, and assigns a random GPS coordinate within 50 km of Iceland's center (`64.96, -18.51`) for manual map placement. Inspecting `Tools/Sagas/njála.json` also shows LLM-from-memory errors (e.g., calling Hildigunnur Starkaðardóttir `"Hildigunnar læknis"` and typo `"baoar brennuna"`). Build a text-grounded extraction + geocoding script modeled on `Tools/OrnefniCurate`.
- **Verified:** fetched.

### 2. Landnámabók (the Book of Settlements — curated highlights only)
- **Text:**
  - Icelandic (Sturlubók): https://www.snerpa.is/net/snorri/landnama.htm and https://is.wikisource.org/wiki/Landnámabók
  - Icelandic, Guðni Jónsson's 1948 normalised text: heimskringla.no/wiki/Landnámabók *(**copyright note:** Guðni died in 1974, so his editorial normalization is technically in copyright in Iceland until 2045; the medieval text itself is public domain, so prefer older PD editions / Wikisource as input and write original Kringum summaries rather than copying modernized prose verbatim).*
  - English translation, Ellwood 1898 (public domain; Ellwood died 1911): archive.org/details/booksettlementi00ellwgoog
- **Content & real yield:** about 400 settlers and 1,000+ farms/landmarks, **but ~70–80% is dry genealogy and land-claim boundaries** that grow repetitive in a driving audio guide. Furthermore, **424 active items** already mention `landnám` (345 non-LMÍ + 79 curated LMÍ), not 94.
- **Approach:** score aggressively like `OrnefniCurate` (`score ≥ 4`) to keep only the ~150–250 genuinely vivid settlement stories (high-seat pillars washing ashore, Irish thralls, feuds, magic, shipwrecks, memorable nicknames), deduplicated against existing `landnám` items.
- **Location:** matched by farm name (see "Locating A-list items" below).
- **Effort:** low–medium (curation + dedup + geocoding).
- **Verified:** fetched.

### 3. Catalogue of Icelandic Volcanoes (`icelandicvolcanoes.is`)
- **Data:** official open-access resource by Veðurstofa Íslands (IMO), Institute of Earth Sciences (HÍ), and Civil Protection.
- **Content:** all ~32–34 Icelandic volcanic systems with major historical eruptions, geology, and hazard narratives. Directly strengthens one of the thinnest Ring Road corridors (**SE Iceland**: Öræfajökull, Grímsvötn, Lakagígar, Eldgjá, Katla) and a thin theme (`50` eruption items today).
- **Rights:** licensed **CC BY-SA 4.0**. Verify whether ShareAlike is compatible with Kringum's export licensing, or synthesize non-copyrightable historical/geological facts into original Kringum prose with attribution.
- **Effort:** low–medium (~30–60 high-value items).
- **Verified:** search-verified (live extraction not yet tested).

### Locating A-list items
- **Start locally first:** `kringum.db` already contains **57,682 LMÍ IS 50V place names** with clean coordinates. Test matching farm/landmark names against your local `items` table + `iceaddr` *before* depending on external APIs—that alone should resolve most active farms.
- **nafnið.is** (Árnastofnun): an unofficial data feed at `https://nafnid.arnastofnun.is/django/vefur/api/` (ornefnaskrar, baeir, ornefni).
  - 8,602 farms with lat/lng, 14,354 place-name registers and 465,863 place names—especially helpful for historical/abandoned farm names absent from LMÍ IS 50V.
  - **Rights clarification:** Árnastofnun does **not** publish its archive under a blanket CC-BY licence (mixed 20th-century informant rights on manuscripts). Basic factual coordinates are low risk, but do not scrape register texts without permission (see Section C).
- Geocoding is where the legends import struggled (704 unresolved names in `Tools/LegendsScraper/unresolved_report.txt`), so test the local LMÍ + `nafnið.is` gazetteer early.
- The Icelandic Saga Map would be the best geocoder for saga items, but it is licensed for non-commercial use only (see "Possibly useful later").

---

## B. Public domain, but OCR quality is unchecked

Items 4, 5, 7, and 8 are on baekur.is (the National Library's scanned books). The "text files as ZIP" download is a JavaScript button the agent couldn't use, so OCR quality is unknown (modern roman type is usually decent; older/Gothic type is noisy). **First step for each: pull one volume and look at the text quality.**

### 4. Kristian Kålund, *Bidrag til en historisk-topografisk Beskrivelse af Island* (1877–1882) *(Top pick in Section B)*
- **Source:** both volumes scanned on `archive.org` (Vol. 1: South & West Quarters, 1877; Vol. 2: North & East Quarters + Highlands, 1879–82).
- **Content:** a farm-by-farm historical topography of **all four quarters of Iceland** (including thin **SE Iceland** and the **Westfjords**), documenting saga ruins, assembly sites (*þingstaðir*), burial mounds, and local historical traditions. One of the foundational pillars behind `sagamap.hi.is`, with much higher story-per-farm density than raw *Landnámabók*.
- **Language & rights:** **public domain** (Kålund died 1919). Original is in 1880s Danish, which modern LLMs read easily to synthesize clean IS + EN Kringum stories. **Avoid** copying the 1984–86 Icelandic translation (*Íslenskir sögustaðir*, trans. Haraldur Matthíasson), which is still in copyright.
- **Verified:** search-verified on `archive.org` (OCR quality not yet inspected).

### 5. Sigfús Sigfússon, *Íslenzkar þjóðsögur og sagnir* *(Lower priority post-LMÍ)*
- baekur.is/bok/3ff03903-b5af-4886-aa2e-3e1715cf44bb
- 11 volumes, about 4,900 pages (the 1982–93 edition), East Iceland farm by farm.
- **Priority reassessment:** East Iceland is **no longer thin** after the curated LMÍ import (`1,304` active items: Eastfjords `873`, Fljótsdalshérað `606`, vs `540` non-LMÍ). Given the heavy lift (4,900 pages of unchecked OCR, farm geocoding, and separating copyrighted editorial notes), this is lower priority than DHD, `stridsminjar`, sagas, or Kålund. Better to revisit if **Sagnagrunnur** (which already indexes Sigfús with farm coordinates) becomes accessible.
- **Rights:** the tales are public domain (Sigfús died 1935). The edition's editorial notes are not, and one editor is alive, so use only the tales.
- **Verified:** fetched.

### 6. Ólafur Davíðsson (*Íslenzkar þjóðsögur*, 1895–99) & Brynjúlfur Jónsson frá Minna-Núpi
- **Sources:** Google Books (1895/1945 editions of Ólafur Davíðsson) and `baekur.is` / `snerpa.is`. Both are major post-Jón Árnason folklore collections and are confirmed to be indexed in **Sagnagrunnur**.
- **Rights:** **cleanly public domain** (Ólafur died 1903, Brynjúlfur died 1914) without Sigfús's 1982–93 co-editor copyright complication.
- **Verified:** search-verified (digital text/OCR quality not yet inspected).

### 7. Collingwood & Stefánsson, *A Pilgrimage to the Saga-Steads of Iceland* (1899)
- baekur.is/bok/5eb07dd1-c676-4174-a58e-fd0c69d3b7c8 (264 pages)
- Free colour facsimile, with Collingwood's watercolours, from the Viking Society: vsnr.org/wp-content/uploads/2026/02/Collingwood_Pilgrimage.pdf (233 MB). Egeler's 2015 introduction in it is not public domain.
- English, arranged site by site, about 100–150 places. Public domain (Jón Stefánsson died 1952).
- **Verified:** fetched.

### 8. Jón Þorkelsson, *Þjóðsögur og munnmæli* (1899)
- baekur.is/bok/aa597fab-04ed-49bc-9cf1-49cb2f5773d9 (468 pages)
- More folklore (also indexed in Sagnagrunnur). Public domain (he died 1924). Avoid the 1956 edition.
- **Verified:** fetched.

### 9. 19th-century travellers (English, public domain)
- **Sources:**
  - Dufferin, *Letters from High Latitudes*: Gutenberg #3701
  - Burton, *Ultima Thule*: Gutenberg #59584 and #59585
  - Pfeiffer: Gutenberg #1894
  - Morris, *Journals of Travels in Iceland*: archive.org (in.ernet.dli.2015.183981)
  - Henderson, Mackenzie, Hooker and Baring-Gould: baekur.is and archive.org
- **Content:** "how it looked in 1860" colour. Coverage is mostly along the Þingvellir–Geysir–Hekla route—already your densest corridor (`1,193` items in Árnessýsla alone). Better used selectively for *Area* introductions or "time-capsule" enrichment on major landmarks than for hundreds of new pins. Morris and Dufferin are the best written.
- **Verified:** fetched. The Gutenberg book numbers come from the gutenberg.pglaf.org mirror catalogue, because the main site was down.

---

## C. Strong content, but permission needed or licence unstated

**Rights & synthesis note:** Historical facts, dates, coordinates, and public-domain annals are not copyrightable—and Kringum already synthesizes original concise audio stories (like `Tools/Sinkings` and `Tools/Eruptions`) rather than copying prose verbatim. Asking permission is still strongly recommended to respect Icelandic/EEA *gagnagrunnsréttur* (sui generis database right) and maintain goodwill with researchers and hobbyists; pitching original attributed summaries with `ref` and `link` back to their site makes "yes" much easier.

### 10. Dysjar hinna dæmdu (execution sites) *(Top-priority outreach)*
- University of Iceland research project: https://dhd.hi.is, with a map at dhd.hi.is/kort.html.
- **Data:** public CSVs, e.g. `https://dhd.hi.is/gogn/CSV/Aftokustadir.csv`. The same folder has 150 home farms and 74 "dys" place names.
- **Content:**
  - 168 executions with exact coordinates plus 19 placed approximately, 1550–1830, at about 70 sites.
  - Each record has name, year, home farm, crime, punishment, an Icelandic narrative (median about 450 characters) and annal sources.
  - Crimes include incest (40), theft (32), murder (24), infanticide (16) and witchcraft burnings (14). 27 executions were drownings.
- **Why top priority:** exact coordinates already exist, compact (~70 sites = tiny TTS cost), high listener engagement, and distinct from existing folklore.
- **Rights:** marked "©2019 DHD", so ask before using.
- **Verified:** fetched.

### 11. stridsminjar.is (WWII aircraft crash sites) *(Top-priority outreach)*
- https://stridsminjar.is/en
- 260 aircraft incidents: 214 from 1940–45 and 46 after the war. 164 of them are map points embedded in the home page, each linked to its article.
- **Story quality:** excellent. For example, a 1943 B-17 crew that crash-landed at Eldvörp thought they were in occupied Norway and set up their machine guns.
- **Why top priority:** already geocoded, nationwide (including Reykjanes, East, Westfjords, and Highlands), and adds vivid 20th-century history (`100` WWII/crash items today).
- **Rights:** no licence stated, so ask.
- **Verified:** fetched.

### 12. Árnastofnun archives: Ísmús, Sagnagrunnur & `nafnið.is` *örnefnaskrár* *(Bundle into one outreach email)*
- **Ísmús** (https://www.ismus.is, unofficial feed `https://ismus.is/django/api/`): 50,859 folk recordings, mostly folklore, each with a 1–3 sentence Icelandic summary + MP3 audio; 12,347 locations have coordinates (some in Canada). Huge volume; needs LLM curation. *Verified: fetched.*
- **`nafnið.is` *örnefnaskrár* as a story source:** beyond farm coordinates, the 14,354 full farm place-name manuscripts hold far richer local stories than LMÍ's clipped `athugasemd` notes—especially for **Westfjords, Strandir, and SE Iceland**. *Rights:* mixed 20th-century informant manuscripts, no blanket CC-BY.
- **Sagnagrunnur** (https://sagnagrunnur.arnastofnun.is/s/): ~10,000 mapped printed legends (confirmed to index **Sigfús Sigfússon**, **Jón Þorkelsson**, and **Ólafur Davíðsson** alongside Jón Árnason) with summaries, sources, and coordinates. Its `/grunnur/api/...` returned HTTP 500 on 2026-11-24—ask Árnastofnun about API access and licensing for all three datasets together.

### 13. Minjastofnun narrative pages (*Friðlýst hús og kirkjur*)
- https://www.minjastofnun.is (beyond the facts-only WFS listed below).
- **Content:** the website holds short historical descriptions (architects, building history, disputes, alterations) for protected houses and churches nationwide, backed by the 31-volume *Kirkjur Íslands* (216 historic churches).
- **Rights:** no licence stated, so ask alongside DHD.
- **Verified:** search-verified (scraping structure not yet tested).

### 14. Veðurstofa avalanche records (snjóflóðaannálar)
- One PDF per town, e.g. https://eldri.vedur.is/gogn/snjoflod/haettumat/si/si_annall.pdf (Siglufjörður, 133 pages). The old www.vedur.is/gogn/ links no longer serve the PDFs.
- Eyewitness descriptions of fatal avalanches, with deaths, damage and named avalanche paths—especially strong for **Westfjords** and **Eastfjords** (`69` avalanche items today).
- **Effort:** manual/LLM extraction, about 50 strong items.
- **Rights:** no licence stated.
- **Verified:** fetched.

### 15. Reykjavík hidden-beings map layer (Huliðsvættir)
- `https://lukrgatt.reykjavik.is/server/rest/services/Hulidsvaettir/MapServer/0`
- 73 points from Erla Stefánsdóttir's 1988 map of elves and hidden people, a direct fit for the elf AR models.
- The descriptions are generic per type of being, so each needs writing up. (Note: Reykjavík already has 831 items and DB already has 1,423 elf/hidden-folk items, so mainly useful if expanding AR `Sýn` items.)
- **Rights:** no licence found.
- **Verified:** fetched.

### 16. Kvennasöguslóðir í Reykjavík (Women's Heritage Walk)
- PDF: https://rafhladan.is/bitstream/handle/10802/10973/kvennasoguganga-vefur.pdf (2014; text by Auður Styrkársdóttir; City of Reykjavík with Kvennasögusafn).
- 27 street-address stops with real narrative text in both Icelandic and English.
- **Rights:** no licence stated.
- **Verified:** fetched.

---

## Possibly useful later

- **Icelandic Saga Map:** https://sagamap.hi.is, with an unofficial data feed at `/data/data.php`.
  - 120 texts (sagas, þættir, Landnámabók, Sturlunga, annals, travel accounts) with geotagged places and the chapters that mention them.
  - Licensed **CC BY-NC 4.0** (another notice on the site says BY-NC-SA), so non-commercial use only. Whether Kringum qualifies is your call; if it does, it is the best way to place saga items.
- **Curated historical mini-sets (same model as `Tools/Sinkings` & `Tools/Eruptions`):**
  - **Major historical earthquakes** (*Suðurlandsskjálftar* 1784, 1896, 2000, 2008; *Norðurlandsskjálftar* 1872, 1934, 1976 — only `48` mentions today).
  - **Iconic lighthouses (*Vitar Íslands*)**: Vegagerðin's *Vitaskrá* provides exact coordinates; combine with keeper/shipwreck history from Wikipedia and local histories (~30–60 coastal items; only `69` mentions today).
  - **Foreign maritime history:** Spánverjavígin (the 1615 killing of Basque whalers — only `9` mentions today, fills Westfjords/Strandir), Norwegian whaling stations, and French fishermen's hospitals and graves. About 30 hand-curated items from Wikipedia and tourism pages (CC BY-SA); not checked site by site.
- **Minjastofnun WFS:** http://gis.lmi.is/geoserver/Minjastofnun/wfs
  - 37,734 registered archaeological sites, 3,763 protected houses and structures, and 4 protected heritage areas.
  - Facts only, so useful for placing items rather than as stories (for stories, see #13 above). No licence stated.
- **OpenStreetMap via Overpass (ODbL):** 808 `historic=*` features, of which 360 are named and 27 carry a wikidata tag. Again useful for placing items only.
- **Protected areas (Umhverfisstofnun) WFS:** https://gis.ust.is/geoserver/wfs
  - `fridlyst_svaedi` (141 protected areas) and `natturuminjaskra` (324 sites).
  - Each links to a short factual description on nattura.is.
- **Reykjavík public art layer:** `OpinGognThjonusta/Listaverk/MapServer/0` on lukrgatt.reykjavik.is.
  - 194 works, with art-history text rather than stories.
- **Next-tier texts:**
  - Sturlunga saga: heimskringla.no, or Kålund 1906 on baekur.is. Dramatic but heavy with genealogy (`78` active items already mention Sturlunga).
  - Annals and Biskupasögur on baekur.is.
  - Espólín's *Árbækur*, set in Gothic type, so expect weak OCR.

---

## Rejected

- **Wikidata:**
  - People are tied to towns, not spots: of 2,629 people born or died at an Icelandic place, Reykjavík has 1,348 and the country item "Ísland" has 420.
  - Only 38 items have a "significant event" property, mostly eruptions you already have.
- **English Wikipedia extras:** 216 articles with coordinates and no Icelandic Wikipedia article, mostly airports, meridians and peaks.
- ***Icelandic Legends*** (Powell & Magnússon 1864–66): only an English version of the Jón Árnason legends you already have.
- **Sarpur:** museum records with no public API, private non-commercial terms, and narrative content not checked.
- **gardur.is:** grave register with no "notable people" feature, and it holds personal data.
- **Geoparks** (Reykjanes, Katla): geology only and all rights reserved.
- **Film locations:** promotional, like the deleted Wikipedia items.
- **Skrímslasetrið:** only 4 monster accounts online.
- **Photo archives:** images, not stories.
- **Lighthouse register PDF (alone):** technical register with no per-lighthouse narrative (use only as a coordinate list if building a curated lighthouse mini-set above).
- **Jarðabók Árna Magnússonar:** farm records are mostly rent and livestock, so its stories would have to be mined.
- **Sýslu- og sóknalýsingar:** no digital text found.
- **ferlir.is:** Reykjanes only, no coordinates, ©.

---

## Suggested next steps

1. **Send 3 permission emails in parallel** (zero dev cost, highest payoff):
   - **DHD (`dhd.hi.is`)** for the execution CSVs (pitching original attributed audio summaries).
   - **`stridsminjar.is`** for the WWII crash-site locations and facts.
   - **Árnastofnun** in one combined inquiry covering **Sagnagrunnur** (API/export), **Ísmús**, and **`nafnið.is` *örnefnaskrár***.
2. **Build a text-grounded saga pipeline** (don't reuse `Tools/Sagas`'s random-GPS script) and run **Eyrbyggja, Gísla, Fóstbræðra, and Grettis** first to fill Snæfellsnes, Northern Westfjords, and outlaw stories; test geocoding against your local 57.7k LMÍ table + `iceaddr` before calling `nafnið.is`.
3. **Run a small curated pilot** on either **Landnámabók** (`score ≥ 4` stories only, deduped against 424 existing `landnám` items) or **Kålund** (`archive.org` Vol. 1/2, targeting thin SE Iceland & Westfjords), or build a quick **Catalogue of Icelandic Volcanoes** / **earthquakes** set for SE Iceland.
4. **Defer `baekur.is` OCR work (Sigfús, Collingwood, Jón Þorkelsson)** until after steps 1–3—and keep TTS rendering for the 4,022 newly curated LMÍ items in mind before adding another multi-thousand-item batch.
