# Retrieving Files from a Folder in a Large SharePoint Library with Power Automate

## Investigation Report

| | |
|---|---|
| **Prepared by** | Shaji Sivaraman, Microsoft |
| **Date** | 3 September 2026 |
| **Customer site** | `https://nhorgau.sharepoint.com/sites/pc` — library `wfpp`, folder `PD-AD Library/Position Descriptions` |
| **Test tenant** | `m365cpi10857483.sharepoint.com` — sites `DemoFiles` (small library) and `hr-policies-compliance` (≈27,000-item library) |
| **Status** | Root cause isolated. Working method identified and verified on a library at customer scale. |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Requirement](#2-the-requirement)
3. [The Environment](#3-the-environment)
4. [The Constraints That Govern Everything](#4-the-constraints-that-govern-everything)
5. [Chronology of the Investigation](#5-chronology-of-the-investigation)
6. [Every Method Tried, in Detail](#6-every-method-tried-in-detail)
7. [Every Error Encountered, and What Each One Meant](#7-every-error-encountered-and-what-each-one-meant)
8. [Hypothesis Register — Final State](#8-hypothesis-register--final-state)
9. [The Working Solution](#9-the-working-solution)
10. [Alternatives Considered but Not Implemented](#10-alternatives-considered-but-not-implemented)
11. [Recommended Architecture](#11-recommended-architecture)
12. [What Could Be Next](#12-what-could-be-next)
13. [Lessons Learned](#13-lessons-learned)
14. [Appendix A — Reference Configurations](#appendix-a--reference-configurations)
15. [Appendix B — Field Name Mapping Between Actions](#appendix-b--field-name-mapping-between-actions)
16. [Appendix C — Microsoft Documentation Cited](#appendix-c--microsoft-documentation-cited)
17. [Appendix D — Test Data Inventory](#appendix-d--test-data-inventory)

---

## 1. Executive Summary

The customer needs a Power Automate flow that lists every `.docx`, `.doc` and `.pdf` file under one folder in a SharePoint document library, including files in every subfolder at any depth, while excluding the contents of folders named `Archive` and `AD Documents`. The library holds well over 5,000 items.

The standard approach — the **Get files (properties only)** action with **Limit entries to folder** and **Include nested items** — returned nothing on the customer's library, with no error. Over two days, seven distinct retrieval methods were tested across three SharePoint sites. Every method that asked SharePoint for "everything under this path" in a single request failed once the library exceeded SharePoint's **list view threshold** of 5,000 items — regardless of whether the request was made through the native connector action, an OData REST query, or a CAML query. Several methods worked perfectly on a small library and failed identically on a large one, with no configuration change between the two, which isolated library size as the sole cause.

One method survived at scale: reading **one folder's direct children at a time** using the `GetFolderByServerRelativeUrl(...)/Folders` and `/Files` REST endpoints, with the flow supplying the recursion through a queue-driven loop. This "folder walk" was verified on the 27,000-item test library, including a folder with 587 immediate subfolders that had just caused a CAML query to throttle.

Two platform limits were confirmed along the way that constrain any future design: SharePoint's 5,000-item scan threshold, and Power Automate's 16 MB cap on a single action's output (roughly 2,000 file-property rows).

The investigation concludes that the customer's problem is not a misconfiguration but a platform boundary. The flow-level fix is the folder walk. The durable fix is architectural: write enumeration results to a destination table rather than a flow variable, switch to event-driven processing for ongoing changes, and address the library's size through splitting or indexed metadata.

---

## 2. The Requirement

### 2.1 Functional requirement

Produce, from within Power Automate, a list of files that satisfies all of the following:

| # | Requirement | Detail |
|---|---|---|
| R1 | **Scoped to one folder** | Only files under `/wfpp/PD-AD Library/Position Descriptions`. Nothing from elsewhere in the library. |
| R2 | **Recursive to any depth** | Files in subfolders, sub-subfolders, and so on, with no assumption about how deep the tree goes. |
| R3 | **File-type filtered** | Only `.docx`, `.doc` and `.pdf`. Everything else ignored. |
| R4 | **Folder exclusions** | Skip the contents of any folder named `Archive` or `AD Documents`, wherever it appears in the tree — including nested cases such as `AD Documents/Archive`. |
| R5 | **Clean output** | A flat list with, at minimum, file name and full path, suitable for a downstream Apply to each. |
| R6 | **Standard licensing** | Standard SharePoint connector only. No premium connectors, no Azure AD app registration. |

### 2.2 Non-functional constraints discovered during the work

| # | Constraint | Source |
|---|---|---|
| C1 | The customer's `wfpp` library exceeds SharePoint's 5,000-item list view threshold. | Confirmed by `SPQueryThrottledException` on an unscoped query against the customer site. |
| C2 | The customer's folder picker in Power Automate cannot enumerate the library. | "Could not load items" in the Limit entries to folder field. |
| C3 | The investigation had no direct access to the customer's tenant. All customer-side evidence arrived as relayed screenshots and browser output. | Working arrangement. |
| C4 | The solution must be explainable to the customer's SharePoint and Power Platform teams, who will own it. | Customer context. |

---

## 3. The Environment

### 3.1 Customer environment

| Item | Value | How established |
|---|---|---|
| Tenant | `nhorgau.sharepoint.com` | Screenshot of folder URL |
| Site | `/sites/pc` (display name *PeopleAndCulture*) | Power Automate site picker |
| Library | `wfpp` (URL name) | `/sites/pc/wfpp/_api/...` returned 404, proving `wfpp` is a library not a subsite |
| Folder | `PD-AD Library/Position Descriptions` | Browser: `GetFolderByServerRelativeUrl('/sites/pc/wfpp/PD-AD%20Library/Position%20Descriptions')` returned the folder |
| Library size | Over 5,000 items | Unscoped REST query threw `SPQueryThrottledException` |
| Connection | `AliEmami@nhorgau` | Power Automate connection shown in screenshots |

A naming trap worth recording: the folder is called **PD-AD Library** but it is a *folder*, not a library. The library is `wfpp`. Anyone reading the URL will assume the opposite. Two early attempts failed on exactly this.

### 3.2 Test environments

| Site | Library | Size | Purpose |
|---|---|---|---|
| `DemoFiles` | `Shared Documents` (display: *Documents*) | Small, well under threshold | Prove flow logic and filter expressions in isolation |
| `hr-policies-compliance` | `Shared Documents` (display: *Documents*) | ≈27,000 items (IDs up to 26,958 observed) | Reproduce the customer's threshold condition on a tenant we control |

The `hr-policies-compliance` library's size comes from a folder `Rich-Content Copy2` containing repeated duplications of a 23-file folder, nested several levels (`AML-Compliance Copy Copy Copy Copy Copy Copy Copy Copy...`). A further folder `Rich-Content` has **587 immediate subfolders**. This made it an unusually harsh stand-in for the customer's library.

### 3.3 Test folder structure (`001NH`, on `hr-policies-compliance`)

Built to mirror the customer's `Position Descriptions` tree:

```
Shared Documents/001NH/
├── Document.docx
├── Knowledge Vault - Final Architecture.pdf
├── Knowledge Vault - Final Architecture.pptx
├── Power Automate - SharePoint Folder Files - Customer Test Guide.docx
├── Positions/
│   ├── IT/                          (empty)
│   ├── Marketing/                   (empty)
│   ├── HR/                          (empty)
│   ├── Tech/                        (empty)
│   └── Medical/
│       ├── (HiQ) Divisional Director Medicine and Cancer services - PD 2022.docx
│       ├── (LowQ) Divisional Director, Nursing (Medical and Subacute) - PD 2018.pdf
│       ├── (MedQ) Divisional Director Continuing Care - Sandra Brown PD 2016.pdf
│       ├── Archive/
│       │   └── (HiQ) Divisional Director Medicine and Cancer services - PD 2022_20260810-044330.pdf
│       └── AD Documents/
│           ├── (HiQ) Divisional Director Medicine and Cancer services - PD 2022 - AD.docx
│           ├── (LowQ) Divisional Director, Nursing (Medical and Subacute) - PD 2018 - AD.docx
│           ├── (MedQ) Divisional Director Continuing Care - Sandra Brown PD 2016 - AD.docx
│           └── Archive/
│               └── (HiQ) Divisional Director Medicine and Cancer services - PD 2022 - AD_20260820-180950.docx
└── Template/
    ├── AD Template.docx
    └── HR - Position Description Template.docx
```

Totals: 12 folders, 14 files. After applying R3 and R4, the correct answer is **9 files** (14 minus the `.pptx`, minus the 4 files under `Archive` or `AD Documents`). Under `Positions` alone, the correct unfiltered answer is 8 files; after R3 and R4, 3 files.

---

## 4. The Constraints That Govern Everything

Three hard limits were confirmed during the investigation. Every failure maps to one of them.

### 4.1 SharePoint list view threshold (5,000 items)

SharePoint Online refuses any request that would require it to examine more than 5,000 items to produce its answer. Microsoft documents this under the name *Large List Resource Throttling*; the default threshold is 5,000 and it cannot be changed in SharePoint Online.

The critical subtlety, confirmed repeatedly in testing: **the threshold applies to how many items SharePoint must scan, not how many it returns.** A query for a folder containing 10 files fails if answering it requires scanning 27,000 items. This is why a request for a tiny folder can throttle while the library around it is large.

Two mechanisms let a query stay under the threshold:

- **An indexed column** used in the filter, so SharePoint can locate candidates without a full scan.
- **A folder's internal index.** Microsoft's guidance states: *"When you create a folder, behind the scenes, you're creating an internal index... When you access items in a folder, you're effectively using this internal index to access the data."* A request for a folder's **direct** children uses this index. A request for everything **under** a folder (recursive) does not — it becomes a path-prefix scan across the library.

That distinction between *direct children* and *recursive subtree* turned out to be the entire story.

### 4.2 Power Automate action output cap (16 MB)

A single action's output cannot exceed 16,777,216 bytes. Exceeding it produces:

```
Cannot write more bytes to the buffer than the configured maximum buffer size: 16777216
```

Measured on `hr-policies-compliance`: **Get files (properties only)** returns approximately **8.2 KB per item** (each item carries expanded Author, Editor, Thumbnail, ContentType and other nested objects). A Top count of 2,000 produced 16.56 MB — within 1.3% of the cap. Top count 3,000 and unlimited-with-pagination both failed. The practical ceiling for that action on that library is about **2,000 items per call**.

### 4.3 Connector throttling (600 calls per connection per minute)

The SharePoint connector permits 600 API calls per connection every 60 seconds, counted per connection rather than per flow. Not hit during testing, but relevant to the folder-walk design on large trees: a walk of a 587-subfolder tree makes at least 1,174 calls and must be paced or accept automatic retry delays.

---

## 5. Chronology of the Investigation

### Day 1 — 2 September 2026

| Time (UTC) | Event |
|---|---|
| 03:34 | Customer reports **Limit entries to folder** picker shows "Could not load items" on Get files (properties only). Initial diagnosis: library size or connection. Manual path entry suggested. |
| 05:32 | Customer confirms manual path also returns empty; unscoped run returns *something*. Library has "thousands of folders." Three alternatives proposed: List folder, HTTP `GetFolderByServerRelativeUrl`, indexed metadata. |
| 05:39–05:43 | **List folder** action assessed and ruled out: one level deep only, returns folders as rows, and its `Id` is a path string that cannot feed Get file properties. |
| 05:45 | CAML `GetItems` with `Scope='RecursiveAll'` and `FolderServerRelativeUrl` proposed as the single-call recursive method. |
| 05:47 | Third-party article ("Top 3 best ways") assessed. Confirms all three of its methods either fail at scale, lack recursion, or drop custom metadata. |
| 05:57 onward | Building against `DemoFiles`. Sequence of configuration errors: placeholder `<list-id>` left in Uri; Uri truncated to `GetItems`; full `https://` URL pasted into Uri (site address doubled); library name vs URL name confusion. |
| 06:19–06:40 | CAML `GetItems` returns **empty** on `DemoFiles` even with no filter. Cause not identified at the time. Later found to be a mangled body / `getbytitle` mismatch — the mechanism itself was fine (see Day 2, 09:26). |
| 06:43 | Switched to REST GET `/items?$filter=startswith(FileRef,...)`. Browser test returns 8 files from `Positions`, all depths. **First working recursive result.** |
| 06:47–06:51 | Flow returns 481 items instead of 8: the `$filter` was silently dropped because `%20` in the Uri was double-encoded. Fixed by using `substringof` with no spaces, then by using plain spaces. |
| 06:54 | File-type filter (`File_x0020_Type eq 'pdf' or ...`) verified working in the Uri. |
| 06:57 | Folder exclusions in the Uri (`not substringof(...)`) rejected by SharePoint: *"Value does not fall within the expected range."* Exclusions moved permanently to a Filter array. |
| 07:08 | Customer test guide v1 written around the REST GET method. |

### Day 2 — 3 September 2026

| Time (UTC) | Event |
|---|---|
| 03:08 | Customer site details arrive. Values adjusted for `nhorgau.sharepoint.com/sites/pc`. Initial assumption that `wfpp` is a subsite. |
| 03:16–03:18 | Customer's browser test at `/sites/pc/wfpp/_api/` returns 404 → `wfpp` is a library, not a subsite. Values corrected. |
| 03:54 | Customer's `GetFolderByServerRelativeUrl(...)?$expand=Folders,Files` returns top-level only — confirms folder exists, confirms endpoint is non-recursive. |
| 03:58 | REST GET with path filter on customer library: **`SPQueryThrottledException`**. The v1 method fails at customer scale. |
| 04:01–04:28 | Fell back to Get files (properties only) with correct path `/wfpp/PD-AD Library/Position Descriptions`, nested items on, pagination on. Returns **empty**. Run inputs confirm scope was passed correctly. Picker also fails ("Could not load items"). |
| 05:19 | Full problem summary produced. Documentation sources located and cited. |
| 05:40 | Formal debugging framework applied: Problem Definition, Evidence, Hypothesis Register, Next Experiment. |
| 07:02 | Microsoft Q&A thread reviewed. Tietze (Jan 2026) reports the identical failure mode on an over-threshold library; his workaround is `GetFolderByServerRelativeUrl(...)/Files`. Hypothesis H17 (connector-level unreliability above threshold) raised. |
| 07:28–07:33 | Control experiments on `hr-policies-compliance` / `001NH`. Nested items **off** + folder of only subfolders = empty (config). No folder limit = oldest 100 items by ID (config). Then: with library reduced by deleting most of Rich-Content, the same action with nested items on returns all **26** items correctly. |
| 07:37–07:42 | Library restored to ≈27,000 items. Same action returns **96 mixed items** (partial scoping) then empty. **Customer's failure reproduced on a controlled tenant with no configuration change.** H17 validated. |
| 07:44–07:53 | Top count series (500 / 2000 / 3000 / unlimited) confirms 16 MB output cap and that unscoped retrieval cannot reach a newer folder. |
| 07:55–08:00 | Remedies enumerated and ranked. Folder walk recommended. |
| 08:01–08:23 | Folder walk endpoints tested in browser against `001NH` on the 27,000-item library: `/Files` returns 4, `/Folders` returns 2. **Both clean.** |
| 08:23 | Customer test guide v2 written around the folder walk. |
| 09:05 | First HTTP action in the flow returns the 4 root files. |
| 09:12 | Customer confirms depth must be dynamic. Queue-based Do until design provided. |
| 09:26 | CAML `GetItems` re-tested on `DemoFiles` with `GetList` by URL: **works** — 16 items (8 files, 8 folders). Day 1's E8 failure reclassified as a body/encoding fault, not a mechanism fault. |
| 09:31 | CAML with `$select` and `FSObjType=0` returns the 8 `Positions` files with full paths. Goal met on the small library. |
| 09:40 | CAML tested on `hr-policies-compliance` / `Rich-Content`: **`SPQueryThrottledException`**. CAML dies at scale like every other recursive method. |
| 09:41 | `/Folders` on the same `Rich-Content` folder, two minutes later: **587 subfolders, no error.** Folder walk confirmed on the heaviest available case. Investigation closed. |

---

## 6. Every Method Tried, in Detail

Each method is described with what it does, why it was tried, exact configuration, the observed result on each library, and the verdict.

### 6.1 Get files (properties only) — folder picker

**What it does.** The native SharePoint connector action. The **Limit entries to folder** field offers a dropdown of the library's folder tree.

**Why tried.** It is the standard, documented approach and the customer's starting point.

**Observed.**

| Library | Result |
|---|---|
| Customer `wfpp` | Picker: *"Could not load items. You can enter a path manually."* |
| `hr-policies-compliance` (27k) | Same |
| `DemoFiles` | Picker loads |

**Analysis.** The picker enumerates the library's folders to build its list. On a library over the threshold the enumeration is blocked or exceeds the picker's ~35-second timeout. The message is a symptom of library size, not of connection or permissions — the same connection ran other actions against the same library without an authentication error.

**Verdict.** Not a fault; the picker is not usable above the threshold. Manual entry is the designed fallback.

---

### 6.2 Get files (properties only) — manual path, Include nested items = Yes

**What it does.** Same action with the folder path typed in and recursion on.

**Configuration (final, correct form).**

| Field | Value |
|---|---|
| Site address | `https://nhorgau.sharepoint.com/sites/pc` |
| Library name | `wfpp` |
| Limit entries to folder | `/wfpp/PD-AD Library/Position Descriptions` |
| Include nested items | Yes |
| Filter query, Order by, Top count | empty |
| Pagination | On, threshold 5,000 |

Note the path format: it starts at the **library URL name** (`/wfpp/...`), not at the site or at the folder. Omitting `/wfpp` is the most likely cause of the customer's very first empty result, though that path was never recorded.

**Observed.**

| Library | Result | Run inputs |
|---|---|---|
| Customer `wfpp` | Empty, no error | `viewScopeOption: RecursiveAll`, `folderPath` correct, `$top: 100000` |
| `hr-policies-compliance` at ≈27k | Empty, no error; on one run 96 mixed items including 70 from outside the scoped folder | as above |
| `hr-policies-compliance` after reducing library | **26 items, all correct** | as above |
| `hr-policies-compliance` after restoring library | Back to empty / partial | as above |

**Analysis.** The controlled reduce-and-restore sequence on the test library is the decisive evidence of this investigation. Identical configuration; the only variable was library size; the result flipped from empty to correct to empty. Recursive folder scoping asks SharePoint for every item whose path starts with the folder — a path-prefix scan across the whole library — and the connector degrades silently (empty, partial, or occasionally an explicit threshold error) rather than failing cleanly.

This matches the independent report by Tietze on Microsoft Q&A (January 2026): *"this action started returning no results, even though the target folder clearly contained files... it turned out that the library had crossed the 5,000-item threshold."*

**Verdict.** Correctly configured and cannot work above the threshold. Closed.

---

### 6.3 Get files (properties only) — no folder limit, varying Top count

**What it does.** Same action, no scope, relying on Top count or pagination to fetch enough of the library to include the target folder.

**Why tried.** To understand what the "other values" the customer saw were, and whether brute force could reach the folder.

**Observed on `hr-policies-compliance`.**

| Top count | Items returned | Output size | From target folder |
|---|---|---|---|
| default (100) | 100 — IDs 1–100 | — | 0 |
| 500 | 500 — IDs 1–546 | — | 0 |
| 2,000 | 2,000 — IDs 1–2,184 | 16.56 MB | 0 |
| 3,000 | **buffer overflow** | >16.78 MB | — |
| unlimited + pagination | **buffer overflow** | — | — |

**Analysis.** Without a folder limit the action returns items in **ID order from the oldest**. The target folder `001NH` was created recently and holds IDs 26,923–26,958. Reaching it would require passing ≈26,900 older items — about 220 MB at 8.2 KB each, thirteen times the 16 MB cap. The "other values" the customer saw were simply the oldest items in their library.

**Verdict.** Cannot reach a newer folder in a large library under any setting. Closed. Useful only as the measurement that established the 16 MB cap and the 8.2 KB-per-item cost.

---

### 6.4 Get files (properties only) — folder limit, Include nested items = No

**What it does.** Same action, folder scoped, recursion off — reads only the folder's direct children.

**Why tried.** Hypothesis H18: if the folder's *internal index* serves direct-children requests, this should survive the threshold where the recursive form fails. It would allow a native-only walk with no HTTP actions.

**Observed.** On a small library, returns the direct children including subfolders as rows with `{IsFolder}: true`. The decisive run on the 27,000-item library was **not executed** — the HTTP folder walk (6.9) was proven first and made the question academic.

**Verdict.** Inconclusive but plausible. Would be worth confirming if a customer refuses HTTP actions.

---

### 6.5 List folder

**What it does.** Returns the contents of one folder, given its identifier.

**Why tried.** Suggested by community guidance as the folder-scoped alternative.

**Analysis.** Ruled out on three counts before testing:
- Returns **one level only**; no recursion option exists.
- Returns folders in the same array as files, flagged `IsFolder: true`.
- Its `Id` field is an encoded path string, not the integer `ItemId` that **Get file properties** and **Update file properties** require, so results cannot feed the column actions without a second lookup.
- Returns no custom metadata columns.

**Verdict.** Not suitable. Closed without a run.

---

### 6.6 REST GET `/items` with OData path filter (v1 guide method)

**What it does.** **Send an HTTP request to SharePoint**, GET, against the list items endpoint with `$filter=substringof('/NH/Positions/',FileRef)` (or `startswith`) to scope by path, plus `File_x0020_Type eq ...` for extension.

**Configuration (working form, `DemoFiles`).**

```
Method:  GET
Uri:     _api/web/lists/getbytitle('Documents')/items?$select=FileLeafRef,FileRef,ID&$filter=substringof('/NH/Positions/',FileRef) and (File_x0020_Type eq 'pdf' or File_x0020_Type eq 'docx' or File_x0020_Type eq 'doc')&$top=5000
Headers: Accept: application/json;odata=verbose
Body:    (empty)
```

**Observed.**

| Library | Result |
|---|---|
| `DemoFiles`, browser | 8 files, all depths — correct |
| `DemoFiles`, flow (Uri with `%20`) | 481 items — `$filter` and `$select` silently dropped; Power Automate double-encoded `%20` to `%2520` |
| `DemoFiles`, flow (plain spaces) | 8 files — correct |
| Customer `wfpp`, browser | **`SPQueryThrottledException`** |

**Analysis.** A path filter on `FileRef` cannot use an index — `FileRef` is not indexable in a useful way for `substringof` — so SharePoint must scan the whole library to evaluate it. Works on a small library, throttles on a large one. Two further findings from this method:
- Power Automate URL-encodes the Uri field itself. Pre-encoded `%20` becomes `%2520`, silently breaking the query string. **Type plain spaces in the flow; use `%20` only in a browser.**
- SharePoint's OData `$filter` does **not** support `not substringof(...)`. Attempting it returns *"Value does not fall within the expected range."* Folder exclusions cannot live in the Uri.

**Verdict.** Correct and efficient for libraries under the threshold. Fails above it. Withdrawn from the customer guide.

---

### 6.7 REST GET `GetFolderByServerRelativeUrl(...)/Files` with `$expand`

**What it does.** Reads a folder object directly and lists its files. `$expand=Folders,Folders/Files,Files` was attempted to pull one level of subfolder contents in the same call.

**Observed.** Customer's browser test returned the folder's own files and the names of its subfolders, but **not** the files inside those subfolders. `$expand` reaches one level only; there is no recursive option on this endpoint.

**Verdict.** Non-recursive by design. On its own it does not meet R2. **It became the building block of the working solution (6.9).**

---

### 6.8 CAML query via `GetItems` POST — `Scope='RecursiveAll'` + `FolderServerRelativeUrl`

**What it does.** **Send an HTTP request to SharePoint**, POST, sending a CAML `ViewXml` with recursive scope and a folder-scoping property in the body.

**Configuration (working form, `DemoFiles`).**

```
Method:  POST
Uri:     _api/web/GetList('/sites/DemoFiles/Shared Documents')/GetItems?$select=ID,FileLeafRef,FileRef,FSObjType
Headers: Accept: application/json;odata=verbose
         Content-Type: application/json;odata=verbose
Body:    {"query":{"__metadata":{"type":"SP.CamlQuery"},
          "ViewXml":"<View Scope='RecursiveAll'><Query><Where><Eq><FieldRef Name='FSObjType'/><Value Type='Integer'>0</Value></Eq></Where></Query><RowLimit>5000</RowLimit></View>",
          "FolderServerRelativeUrl":"/sites/DemoFiles/Shared Documents/NH/Positions"}}
```

**Observed.**

| Library | Result |
|---|---|
| `DemoFiles`, Day 1 | Empty, even with no `<Where>` clause. Not explained at the time. |
| `DemoFiles`, Day 2 (with `GetList` by URL) | **16 items** — 8 files + 8 folders, all depths. Then with `FSObjType=0` and `$select`: **8 files with full paths.** |
| `hr-policies-compliance` / `Rich-Content` | **`SPQueryThrottledException`** |

**Analysis.** Day 1's failure was most likely a body corrupted in transit (smart quotes, or a `getbytitle` mismatch) — the mechanism itself works, as Day 2 proved. This was the investigator's error and is recorded as such.

CAML with `RecursiveAll` is, however, semantically the same request as Get files with nested items on: everything whose path starts with the folder. It throttles on a large library for the same reason.

Three implementation notes worth preserving:
- `ViewFields` inside `ViewXml` was **not honoured** for `FileRef`/`FileLeafRef`. Use `$select` on the Uri instead — the endpoint respects that.
- If the `Content-Type` header lacks `;odata=verbose`, the `__metadata` block is rejected: *"The property '__metadata' does not exist on type 'SP.CamlQuery'."* Either add the header or omit `__metadata` from the body — both work.
- `GetList('<library server-relative URL>')` avoids the display-name/URL-name confusion that `getbytitle()` invites.

**Verdict.** The cleanest single-call method for libraries **under** the threshold — full paths, no picker, folders excluded at source. Fails above the threshold. Retained in the guide as the small-library shortcut.

---

### 6.9 Folder walk — `GetFolderByServerRelativeUrl(...)/Folders` + `/Files`, one folder at a time ✅

**What it does.** Instead of asking for everything under a path, ask two narrow questions about **one folder**: what subfolders are directly in it, and what files are directly in it. Each answer uses the folder's internal index and involves only its immediate children. The flow then repeats the questions for each subfolder, using a queue so that depth is unbounded.

**Configuration.** See [Section 9](#9-the-working-solution) and [Appendix A](#appendix-a--reference-configurations).

**Observed.**

| Library / folder | Call | Result |
|---|---|---|
| `hr-policies-compliance` (27k) / `001NH` | `/Files` | 4 files, no error — browser and flow |
| `hr-policies-compliance` (27k) / `001NH` | `/Folders` | 2 folders, no error |
| `hr-policies-compliance` (27k) / `Rich-Content` | `/Folders` | **587 folders, no error** — two minutes after CAML on the same folder threw `SPQueryThrottledException` |
| Customer `wfpp` / `Position Descriptions` | `GetFolderByServerRelativeUrl(...)` | Folder returned with its files (Day 2, 03:54) |

**Analysis.** The only method that produced correct results on the large library. The `Rich-Content` result is the strongest single piece of evidence: same folder, same library, same connection; recursive query blocked, direct-children query answered. This is precisely what Microsoft's documentation on folder internal indexes predicts.

Cost scales with **number of folders**, not files — two calls per folder visited. Excluded folders are filtered *before* they are queued, so their contents are never requested at all (an efficiency gain over post-filtering, and it also means an excluded subtree of any size costs nothing).

Independent corroboration: Tietze's Microsoft Q&A workaround (January 2026) uses the identical `/Files` endpoint for the identical reason.

**Verdict.** **The working solution.** Verified on both small and large libraries, including the heaviest folder available.

---

### 6.10 Summary matrix

| # | Method | Recursive | Full paths | Custom columns | Small library | 27k library | Verdict |
|---|---|---|---|---|---|---|---|
| 6.1 | Get files — picker | — | — | — | picker loads | picker fails | not usable at scale |
| 6.2 | Get files — path, nested **Yes** | ✅ | ✅ | ✅ | ✅ 26 items | ❌ empty / partial | **fails at scale** |
| 6.3 | Get files — no limit, Top count | n/a | ✅ | ✅ | oldest N only | ❌ 16 MB cap | cannot reach folder |
| 6.4 | Get files — path, nested **No** | via loop | ✅ | ✅ | ✅ | untested | plausible, unconfirmed |
| 6.5 | List folder | ❌ | ✅ | ❌ | — | — | ruled out |
| 6.6 | REST `/items` path filter | ✅ | ✅ | ✅ | ✅ 8 files | ❌ throttled | **fails at scale** |
| 6.7 | `GetFolder...` + `$expand` | ❌ one level | ✅ | ❌ | ✅ | ✅ | building block only |
| 6.8 | CAML `RecursiveAll` | ✅ | ✅ via `$select` | ✅ | ✅ 8 files | ❌ throttled | **fails at scale**; best small-library method |
| **6.9** | **Folder walk** | **via loop** | **✅** | via `ListItemAllFields` | **✅** | **✅ 587 folders** | **✅ WORKING** |

---

## 7. Every Error Encountered, and What Each One Meant

Recorded verbatim where possible. Several look alike but have entirely different causes; the *source* address inside the error is usually the fastest discriminator.

| # | Error text (abridged) | Where | Actual cause | Fix |
|---|---|---|---|---|
| E-01 | `Could not load items. You can enter a path manually.` | Limit entries to folder picker | Library over threshold; picker enumeration times out | Enter custom value |
| E-02 | `A potentially dangerous Request.Path value was detected from the client (<)` — status 401 | HTTP action | Placeholder `<list-id>` left literally in the Uri | Replace with real GUID; note the **401 is misleading** — it is request validation, not auth |
| E-03 | `401 UNAUTHORIZED` — source `.../sites/DemoFiles/GetItems` | HTTP action | Uri truncated to `GetItems`; path fragment lost on paste | Re-enter full Uri from `_api` |
| E-04 | `404` — source `.../sites/DemoFiles/https://.../sites/DemoFiles/_api/...` | HTTP action | Full `https://` URL pasted into the Uri field; action prepends site address | Uri starts at `_api` |
| E-05 | `BadGateway 502 / UnknownError` | HTTP action | `GetItems` called with empty body | Provide body, or change Uri for a GET test |
| E-06 | `The parameter query does not exist in method GetFolderByServerRelativeUrl` | HTTP action | Body left populated while Uri was changed to a GET diagnostic | Clear body for GET |
| E-07 | `This nhorgau.sharepoint.com page can't be found` at `/sites/pc/wfpp/_api/` | Browser | `wfpp` is a library, not a subsite | Site address is `/sites/pc` |
| E-08 | `The expression "startswith(FileRef,'/sites/DemoFiles/Shared" is not valid` | Browser | Unencoded space in browser URL | `%20` in browser |
| E-09 | 481 items returned instead of 8; no `FileRef` fields | Flow | Pre-encoded `%20` in Uri double-encoded to `%2520`; `$select`/`$filter` dropped | Plain spaces in flow Uri |
| E-10 | `Value does not fall within the expected range` — `System.ArgumentException` | Browser | `not substringof(...)` in `$filter` unsupported | Exclusions in Filter array |
| E-11 | `The attempted operation is prohibited because it exceeds the list view threshold` — `SPQueryThrottledException` | REST GET on customer site; CAML on `Rich-Content`; Get files nested=Yes (one run) | Library over 5,000; query requires full scan | Folder walk |
| E-12 | `Cannot write more bytes to the buffer than the configured maximum buffer size: 16777216` | Get files, Top count ≥ 3,000 or unlimited | Power Automate 16 MB action output cap | Never fetch unscoped; walk per folder |
| E-13 | `The property '__metadata' does not exist on type 'SP.CamlQuery'` | CAML POST | `Content-Type` header missing `;odata=verbose` | Add header, or drop `__metadata` from body |
| E-14 | `File Not Found` — source shows `/sites/DemoFiles/_api/web/GetList('/sites/hr-policies-compliance/...')` | HTTP action | Site address and Uri pointed at different sites | All three (site, Uri, body) from the same site |
| E-15 | Empty result, no error, no `viewScopeOption` in run inputs | Get files | Include nested items **off** and target folder contains only subfolders | Set nested items to Yes (small library) or use walk |
| E-16 | Correct items plus 70 from outside the scoped folder (96 total) | Get files nested=Yes at 27k | Connector partially applying scope under threshold pressure | Same as E-11 |

**Pattern worth naming.** Eight of these sixteen (E-02, 03, 04, 05, 06, 08, 09, 13, 14) are *configuration-entry* errors — field contents mangled between a chat window and a form field. They consumed roughly as much time as the real platform investigation. A copy-paste-safe reference (Appendix A) and a "check the source address first" habit would have halved Day 1.

---

## 8. Hypothesis Register — Final State

### Validated

| ID | Hypothesis | Evidence |
|---|---|---|
| H1 | The customer's `wfpp` library exceeds the list view threshold | `SPQueryThrottledException` on unscoped REST GET, customer site |
| H2 | `wfpp` is a library; `PD-AD Library` is a folder inside it | 404 at `/sites/pc/wfpp/_api/`; folder call succeeds at `/sites/pc/_api/...('/sites/pc/wfpp/PD-AD Library/...')` |
| H3 | The target folder exists and contains files | Customer's `GetFolderByServerRelativeUrl` browser output |
| H4 | Downstream flow logic (Filter array exclusions, extension filter, Select) is correct | Verified on `DemoFiles`: 8 → 3 |
| H5 | Connection permissions are sufficient | Same connection reads folder via REST and runs actions without auth error |
| H14 | Volume, not configuration, triggers the failure | Reduce-and-restore on `hr-policies-compliance`: identical config, result flips with library size |
| H17 | Recursive folder scoping in the native action is unreliable above the threshold | Same as H14; corroborated by Tietze (Q&A, Jan 2026), Nogueira (Feb 2025), Kesharwani (Apr 2025) |
| H19 | `GetFolderByServerRelativeUrl(...)/Files` and `/Folders` return a folder's direct children regardless of library size | 4 files / 2 folders on `001NH` at 27k; **587 folders on `Rich-Content`** immediately after CAML throttled on it |

### Invalidated

| ID | Hypothesis | Why |
|---|---|---|
| H6 | Picker failure indicates a permissions or connection fault | Same connection works elsewhere; failure is threshold/timeout |
| H7 | Recursion achievable via REST GET path filter at scale | Throttled on customer site |
| H8 | `GetFolderByServerRelativeUrl` can return subfolder contents | One level only, confirmed |
| H9 | Folder exclusions expressible in OData `$filter` | `not substringof` rejected |
| H11 | Customer's original path omitted `/wfpp` (as root cause) | Correctly-formed path also fails; plausible for first attempt only |
| H12 / H16 | Dropdown "wfpp" maps to a different library GUID | Made moot by H14/H17 — failure reproduced with a known-correct library |
| H13 | Hidden character in pasted path | Same |
| H20 | CAML `RecursiveAll` + `FolderServerRelativeUrl` survives the threshold | `SPQueryThrottledException` on `Rich-Content` |

### Reclassified

| ID | Original | Revised |
|---|---|---|
| E8 (Day 1) | "CAML via this connector returns no data on this tenant" | **Investigator error.** Body or `getbytitle` reference was corrupted. Mechanism confirmed working Day 2 with `GetList` by URL. |

### Inconclusive

| ID | Hypothesis | Status |
|---|---|---|
| H18 | Non-recursive folder scoping in the native action (nested items = No) survives the threshold | Consistent with the folder-index model and with H19, but the deciding run at 27k was not executed. Worth confirming if a native-only solution is ever required. |

---

## 9. The Working Solution

### 9.1 Design principle

Never ask SharePoint for more than one folder's direct children in a single request. Supply recursion from the flow, not from the query.

### 9.2 Flow structure

```
1  Initialize variable   FoldersToVisit  (Array)  = [ "<target folder server-relative path>" ]
2  Initialize variable   AllFiles        (Array)  = [ ]

3  Do until   length(variables('FoldersToVisit')) is equal to 0
   │           (Change limits → Count: 5000)
   │
   ├─ 3a  Compose            CurrentFolder  = first(variables('FoldersToVisit'))
   ├─ 3b  Set variable       FoldersToVisit = skip(variables('FoldersToVisit'), 1)
   │
   ├─ 3c  HTTP (GET)         Get files      …GetFolderByServerRelativeUrl('@{outputs('CurrentFolder')}')/Files?$select=Name,ServerRelativeUrl,TimeLastModified
   ├─ 3d  Apply to each      over body('Get_files')['d']['results']
   │        └─ Append to array variable   AllFiles ← item()
   │
   ├─ 3e  HTTP (GET)         Get folders    …GetFolderByServerRelativeUrl('@{outputs('CurrentFolder')}')/Folders?$select=Name,ServerRelativeUrl
   ├─ 3f  Filter array       Filter folders — drop Archive / AD Documents
   │        From:      body('Get_folders')['d']['results']
   │        Condition: @and(not(equals(toLower(item()?['Name']), 'archive')),
   │                        not(equals(toLower(item()?['Name']), 'ad documents')))
   └─ 3g  Apply to each      over body('Filter_folders')
            └─ Append to array variable   FoldersToVisit ← item()?['ServerRelativeUrl']

4  Filter array   Keep only PDF and Word
   From:      variables('AllFiles')
   Condition: @or(endswith(toLower(item()?['Name']), '.pdf'),
                  endswith(toLower(item()?['Name']), '.docx'),
                  endswith(toLower(item()?['Name']), '.doc'))
```

### 9.3 Common settings for every HTTP action

| Field | Value |
|---|---|
| Action | **Send an HTTP request to SharePoint** (standard connector — not the premium **HTTP** action) |
| Site address | the site containing the library |
| Method | GET |
| Headers | `Accept` → `application/json;odata=verbose` |
| Body | empty |

### 9.4 Why the ordering inside the loop matters

- **3a before 3b.** Compose must read the first queue entry *before* Set variable removes it. Reversed, one folder is skipped every iteration.
- **3f before 3g.** Exclusions are applied before queuing, so excluded subtrees are never visited. This is both correct (R4) and cheaper.
- **`@{outputs('CurrentFolder')}` must be a live expression.** Entered via the **fx** button so it renders as a token. If it stays as literal text, SharePoint receives the string `@{outputs('CurrentFolder')}` and returns *File Not Found*.

### 9.5 Expected trace on `001NH`

| Iteration | CurrentFolder | Files | Subfolders queued | Queue after |
|---|---|---|---|---|
| 1 | 001NH | 4 | Positions, Template | 2 |
| 2 | Positions | 0 | IT, Marketing, Medical, HR, Tech | 6 |
| 3 | Template | 2 | — | 5 |
| 4 | IT | 0 | — | 4 |
| 5 | Marketing | 0 | — | 3 |
| 6 | Medical | 3 | *(Archive, AD Documents dropped)* | 2 |
| 7 | HR | 0 | — | 1 |
| 8 | Tech | 0 | — | 0 → stop |

Collected: 10. After step 4: **9**.

### 9.6 Verification status

| Component | Verified |
|---|---|
| `/Files` on a folder in a 27k library | ✅ browser and flow, `001NH` |
| `/Folders` on a folder in a 27k library | ✅ browser, `001NH` (2) and `Rich-Content` (587) |
| Full Do until loop end-to-end | ⚠️ **Not yet run as a complete flow.** Both calls are proven; the queue mechanics, variable accumulation and final filter are standard Power Automate patterns but have not been executed together on `001NH`. **Recommended before handing to the customer.** |
| Exclusion filter (`Filter folders`) | ✅ logic verified on `DemoFiles` equivalent |
| Extension filter | ✅ verified on `DemoFiles` |

### 9.7 Known limitations of this solution

| Limitation | Impact | Mitigation |
|---|---|---|
| Sequential — Do until cannot parallelise | Slow on trees with many folders (Rich-Content: ≥1,174 calls) | Acceptable for scheduled/background runs. For interactive use, scope tighter or pre-compute. |
| `AllFiles` variable accumulates in memory | Will exceed 16 MB on very large trees | Write each folder's files to a destination table as they arrive (see Section 11). |
| A single folder with >5,000 direct children will throttle its own `/Files` call | Rare in practice | Split that folder, or index File Type for that library. |
| Connector rate limit 600/min | Long walks may hit it | Connector auto-retries; or add a small Delay per iteration. |
| Depth of `Change limits → Count` | Default 60 iterations is too low | Set to 5,000 (the maximum). |
| Returns only file-system properties, not library columns | Custom metadata absent | Add `$expand=ListItemAllFields&$select=...,ListItemAllFields/YourColumn` to the `/Files` call. |

---

## 10. Alternatives Considered but Not Implemented

| # | Alternative | Recursion | Survives threshold | Effort | Why not implemented |
|---|---|---|---|---|---|
| A1 | **Native-action folder walk** — Get files (properties only), folder limit, nested = No, looped via `{IsFolder}` | via loop | probably (H18) | Medium | Deciding test not run; HTTP walk proven first. Fallback if HTTP actions are unacceptable to the customer. |
| A2 | **Indexed column + Filter Query** | native | only if the filter is selective | Low, needs site owner | `File Type` alone is not selective on a document library. Would require a stamped, indexed metadata column (e.g. `Department`) — a content-tagging project, not a fix. Right long-term design (Section 11). |
| A3 | **Microsoft Graph** — `/drives/{id}/root:/path:/children` recursive, or `/search(q='')` | native | yes (no list view threshold in Graph) | High | Requires premium HTTP connector, Azure AD app registration, admin consent. Violates R6. Right answer if that infrastructure already exists. |
| A4 | **Child flow calling itself** (recursive flow) | native | yes | Medium-High | Only allowed within a solution; adds deployment complexity. The queue-based Do until achieves unbounded depth in a single flow, so this was unnecessary. |
| A5 | **Restructure the library** — move Position Descriptions to its own library, or split `wfpp` | native | yes (new library under threshold) | High, organisational | Governance decision, not a flow fix. The only option that fixes the problem for every consumer of the library. Recommended for the roadmap (Section 12). |
| A6 | **Event-driven** — *When a file is created or modified (properties only)*, folder-scoped | n/a | yes | Low | Does not backfill existing files. Ideal **companion** to the walk: walk once, then trigger keeps the result current. Recommended (Section 11). |
| A7 | **SharePoint Search API** | native | yes (search index is not subject to the threshold) | Medium | Results depend on crawl freshness (minutes to hours behind); security-trimmed; result count capped per query. Viable for read-mostly scenarios; not tested. |
| A8 | **Power Automate Desktop / PnP PowerShell** | native | yes | Medium | Outside the customer's stated tooling. PnP `Get-PnPFolderItem -Recursive` would work in one line for a one-off inventory. |

---

## 11. Recommended Architecture

The flow-level fix (Section 9) solves R1–R6. It does not, on its own, produce a design that will keep working as the library grows or that other consumers can rely on. Three changes turn it into one.

### 11.1 Enumerate in small units — done

The folder walk already respects this. No request ever exceeds one folder's direct children.

### 11.2 Stream results to a destination table — not a variable

Replace **Append to array variable `AllFiles`** (step 3d) with a write to a durable store, one row per file, as each folder is read:

| Destination | Action | When to prefer |
|---|---|---|
| SharePoint list | Create item | Simplest; same connector; queryable by other flows and Copilot agents |
| Dataverse table | Add a new row | If the customer already uses Dataverse / Power Apps; better for scale and relationships |
| Excel Online table | Add a row into a table | Ad-hoc reporting; avoid for >10k rows |
| Azure SQL / Storage | premium | Only if already in the estate |

Effect: the flow never holds more than one folder's files in memory; the 16 MB cap becomes irrelevant; the result persists between runs; and downstream consumers read a table rather than hitting SharePoint.

Add columns for `Name`, `ServerRelativeUrl`, `ParentFolder`, `TimeLastModified`, `Extension`, and a `LastSeenRunId` so stale rows can be identified after a re-walk.

### 11.3 Walk once, then go event-driven

```
INITIAL LOAD  /  PERIODIC RECONCILIATION  (e.g. weekly, off-hours)
  Folder walk (Section 9) → upsert rows in destination table
  Mark rows not seen this run as "possibly deleted"

ONGOING
  Trigger: When a file is created or modified (properties only)
           Site: <site>   Library: <library>   Folder: <target folder>
  → if extension in (.pdf, .docx, .doc) and path does not contain /Archive/ or /AD Documents/
  → upsert that one row in the destination table

CONSUMERS  (Copilot agent, reports, other flows)
  Read the destination table. Never query SharePoint directly for the list.
```

The trigger is not affected by library size. The walk runs rarely and can be slow. The table is always current.

### 11.4 Address the library itself

Every item above is a workaround for a library that is over the threshold. Microsoft's guidance is unambiguous: keep libraries under 5,000 items where possible, or ensure every view and query filters on an indexed column that brings the candidate set under 5,000.

For the customer, two options to raise with the SharePoint owners:

- **Split.** Move `Position Descriptions` (and its siblings under `PD-AD Library`) into a dedicated library. Every native action then works as documented, the picker loads, and no HTTP actions are needed.
- **Tag and index.** Add a `Department` (or similar) choice column to `wfpp`, stamp it on existing files, index it. Then `Filter Query: Department eq 'Medical'` on Get files works at any library size — because the index keeps the scan under 5,000.

Either is a governance conversation, not a flow change. Neither blocks the folder walk being deployed now.

---

## 12. What Could Be Next

### 12.1 Immediate (before customer hand-off)

| # | Action | Owner | Why |
|---|---|---|---|
| N1 | Run the complete Do until flow end-to-end on `001NH`; confirm 9 files | Shaji | Both calls are proven; the assembled loop is not. The guide's "reference result" should be observed, not predicted. |
| N2 | Run `/Folders` and `/Files` in the customer's browser against `Position Descriptions` and one subfolder | Ali | Confirms the endpoints on the customer's tenant (the folder call already succeeded on Day 2 03:54; this adds `/Folders`). |
| N3 | Ask Ali for the deepest folder level under `Position Descriptions` and the approximate number of folders | Ali | Sizes the walk; determines whether the memory-variable version is acceptable or Section 11.2 is needed from day one. |
| N4 | Move the Customer Test Guide out of `001NH` before any customer-facing screenshot | Shaji | It currently appears in the test results. |
| N5 | Delete or mark superseded the v1 guide in OneDrive | Shaji | Prevents the customer testing the withdrawn method. |

### 12.2 Short term (first customer iteration)

| # | Action | Why |
|---|---|---|
| N6 | Replace `AllFiles` variable with a SharePoint list write (Section 11.2) | Removes the 16 MB risk before it bites on a real tree. |
| N7 | Add the folder-scoped *created or modified* trigger (Section 11.3) | Stops the need to re-walk for routine updates. |
| N8 | Add `$expand=ListItemAllFields` to the `/Files` call if any library column is needed downstream | The file-system endpoint alone omits custom metadata. |
| N9 | Add a Delay (e.g. 200 ms) inside the Do until if the customer's tree has >250 folders | Stays under 600 calls/min without relying on connector retry. |
| N10 | Test hypothesis H18 (native action, nested = No, at 27k) | Gives the customer a no-HTTP option if their governance prefers it. |

### 12.3 Medium term (architecture)

| # | Action | Why |
|---|---|---|
| N11 | Raise library split or indexed-metadata design with the customer's SharePoint owners | The root condition. Every flow, view and integration touching `wfpp` is affected, not just this one. |
| N12 | Evaluate whether the downstream consumer (likely a Copilot agent, given the PD/AD context) should read from the destination table rather than enumerate at runtime | Decouples the agent from SharePoint limits entirely. |
| N13 | If Graph infrastructure exists in the customer tenant, prototype A3 as a comparison | Graph has no list view threshold; may simplify the long-term design. |

### 12.4 Open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Why did CAML `GetItems` return empty on Day 1 when the identical mechanism worked on Day 2? | Recorded as investigator error (body corruption). Not fully proven. Low impact — mechanism fails at scale anyway. |
| Q2 | Does the native action with nested items = No survive the threshold (H18)? | Determines whether a no-HTTP variant exists. |
| Q3 | Why did the 96-item run (Day 2, 07:38) return correct scoped items *plus* 70 unscoped ones? | Suggests the connector partially applies scope under threshold pressure. Reinforces "do not trust the native action above 5k." Mechanism unexplained. |
| Q4 | What is the actual folder count and depth under the customer's `Position Descriptions`? | Determines walk duration and whether Section 11.2 is needed immediately. |
| Q5 | Are there folders with special characters (parentheses, `#`, `%`) in the customer's tree? | `GetFolderByServerRelativeUrl` does not support `%` and `#`; `GetFolderByServerRelativePath(decodedurl='...')` does. Community reports parentheses can also require encoding. Check Ali's Call A output. |

---

## 13. Lessons Learned

### About the platform

1. **The threshold is about scanning, not returning.** A 10-file folder can throttle. Every recursive-by-path method — native, OData, CAML — is a full scan in disguise.
2. **A folder's direct children are always reachable.** Microsoft's "internal index" claim held up on a 587-subfolder folder in a 27,000-item library, seconds after a recursive query on the same folder was refused.
3. **"Empty, no error" is the connector's most common failure mode above the threshold**, and it is indistinguishable from three configuration mistakes (wrong path root, nested items off on a folder of folders, no folder limit). The run **inputs** — `viewScopeOption`, `folderPath`, `$top` — discriminate them; the outputs do not.
4. **Power Automate encodes the Uri field.** `%20` becomes `%2520`. Type spaces in the flow; encode only in a browser. This one silent fault cost an hour and produced a 481-item red herring.
5. **16 MB is the real row cap.** At ≈8 KB per Get files item, about 2,000 rows. `$select` on an HTTP action reduces this by an order of magnitude.
6. **SharePoint's OData `$filter` has no `not substringof`.** Exclusions must be post-filtered.
7. **`GetList('<url>')` beats `getbytitle('<name>')`.** Display name vs URL name (`Documents` vs `Shared Documents`) tripped both the investigator and the customer.

### About the process

8. **Reproduce on a controlled tenant before diagnosing the customer's.** The reduce-and-restore experiment on `hr-policies-compliance` settled in twenty minutes what relayed screenshots could not settle in a day.
9. **Read the `source` address in every error first.** It exposed E-03, E-04 and E-14 instantly; each would otherwise have looked like an authentication or permissions problem.
10. **Write a hypothesis register early.** The formal framework (Day 2, 05:40) immediately reordered priorities: three "check the config" hypotheses were about to consume the morning when the community thread and the control experiment showed the config was never the problem.
11. **Configuration-entry errors were half the effort.** Eight of sixteen errors were mangled field contents. A copy-safe reference file (Appendix A) should be the *first* deliverable, not the last.
12. **Retract quickly.** Day 1's "CAML doesn't work on this tenant" was wrong, and saying so on Day 2 cost nothing. Leaving it unretracted would have removed the best small-library method from the guide.

---

## Appendix A — Reference Configurations

All values copy-safe. Straight quotes throughout. Replace `<...>` placeholders.

### A.1 Folder walk — HTTP actions (recommended, any library size)

**Get files**
```
Method:  GET
Uri:     _api/web/GetFolderByServerRelativeUrl('@{outputs('CurrentFolder')}')/Files?$select=Name,ServerRelativeUrl,TimeLastModified
Headers: Accept = application/json;odata=verbose
Body:    (empty)
```

**Get folders**
```
Method:  GET
Uri:     _api/web/GetFolderByServerRelativeUrl('@{outputs('CurrentFolder')}')/Folders?$select=Name,ServerRelativeUrl
Headers: Accept = application/json;odata=verbose
Body:    (empty)
```

**FoldersToVisit initial value (example, test tenant)**
```
["/sites/hr-policies-compliance/Shared Documents/001NH"]
```

**FoldersToVisit initial value (example, customer)**
```
["/sites/pc/wfpp/PD-AD Library/Position Descriptions"]
```

**Filter folders — condition**
```
@and(not(equals(toLower(item()?['Name']), 'archive')), not(equals(toLower(item()?['Name']), 'ad documents')))
```

**Keep only PDF and Word — condition**
```
@or(endswith(toLower(item()?['Name']), '.pdf'), endswith(toLower(item()?['Name']), '.docx'), endswith(toLower(item()?['Name']), '.doc'))
```

### A.2 CAML single call (small libraries only — under 5,000 items)

```
Method:  POST
Uri:     _api/web/GetList('/sites/<Site>/<LibraryUrlName>')/GetItems?$select=ID,FileLeafRef,FileRef,FSObjType
Headers: Accept       = application/json;odata=verbose
         Content-Type = application/json;odata=verbose
Body:
{"query":{"__metadata":{"type":"SP.CamlQuery"},"ViewXml":"<View Scope='RecursiveAll'><Query><Where><Eq><FieldRef Name='FSObjType'/><Value Type='Integer'>0</Value></Eq></Where></Query><RowLimit>5000</RowLimit></View>","FolderServerRelativeUrl":"/sites/<Site>/<LibraryUrlName>/<Folder>"}}
```

If the `Content-Type` header cannot be set, drop `"__metadata":{"type":"SP.CamlQuery"},` from the body — it is optional without the verbose content type.

**Post-filter (Filter array on `body(...)['d']['results']`)**
```
@and(not(contains(toLower(item()?['FileRef']), '/archive/')), not(contains(toLower(item()?['FileRef']), '/ad documents/')), or(endswith(toLower(item()?['FileLeafRef']), '.pdf'), endswith(toLower(item()?['FileLeafRef']), '.docx'), endswith(toLower(item()?['FileLeafRef']), '.doc')))
```

### A.3 Browser diagnostics (use `%20` for spaces)

**List document libraries on a site (Title and Id)**
```
https://<site>/_api/web/lists?$select=Title,Id&$filter=BaseTemplate%20eq%20101
```

**Confirm a library by URL and get its Title/Id**
```
https://<site>/_api/web/GetList('/sites/<Site>/<LibraryUrlName>')?$select=Title,Id
```

**List subfolders of a folder**
```
https://<site>/_api/web/GetFolderByServerRelativeUrl('/sites/<Site>/<LibraryUrlName>/<Folder>')/Folders?$select=Name,ServerRelativeUrl
```

**List files in a folder**
```
https://<site>/_api/web/GetFolderByServerRelativeUrl('/sites/<Site>/<LibraryUrlName>/<Folder>')/Files?$select=Name,ServerRelativeUrl
```

**For folder names containing `%` or `#`**
```
https://<site>/_api/web/GetFolderByServerRelativePath(decodedurl='/sites/<Site>/<LibraryUrlName>/<Folder>')/Files
```

### A.4 Get files (properties only) — correct form (small libraries only)

| Field | Value |
|---|---|
| Library name | `<library>` |
| Limit entries to folder | `/<LibraryUrlName>/<Folder>` — starts with the library URL name, real spaces, no trailing slash |
| Include nested items | Yes |
| Top count | blank |
| Pagination (Settings) | On, 5000 |

---

## Appendix B — Field Name Mapping Between Actions

The same file property has a different name depending on which action returned it.

| Meaning | Get files (properties only) | REST `/items` / CAML `GetItems` | `GetFolder...(/Files)` |
|---|---|---|---|
| File name with extension | `{FilenameWithExtension}` | `FileLeafRef` | `Name` |
| Full server-relative path | `{FullPath}` (no leading `/sites/`) | `FileRef` | `ServerRelativeUrl` |
| Parent folder path | `{Path}` | `FileDirRef` | *(derive from `ServerRelativeUrl`)* |
| Integer item ID | `ID` | `ID` | *(via `ListItemAllFields/ID`)* |
| Is a folder | `{IsFolder}` | `FSObjType` (1) / `FileSystemObjectType` (1) | *(folders come from `/Folders`, never mixed)* |
| Last modified | `Modified` | `Modified` | `TimeLastModified` |
| Result array | `body(...)?['value']` | `body(...)['d']['results']` | `body(...)['d']['results']` |

---

## Appendix C — Microsoft Documentation Cited

| Topic | Source | Key statement |
|---|---|---|
| List view threshold cause | [The number of items in this list exceeds the list view threshold](https://learn.microsoft.com/en-us/troubleshoot/sharepoint/lists-and-libraries/items-exceeds-list-view-threshold) | *"SharePoint Online uses the Large List Resource Throttling feature. By default, the list view threshold is configured at 5,000 items."* |
| Folders as internal indexes | [Working with the List View Threshold limit](https://support.microsoft.com/en-us/sharepoint/data-and-lists/working-with-the-list-view-threshold-limit-for-all-versions-of-sharepoint) | *"When you create a folder, behind the scenes, you're creating an internal index... When you access items in a folder, you're effectively using this internal index."* Also: *"A folder can contain more items than the List View Threshold, but to avoid being blocked, you might still need to use a filtered view based on column indexes."* |
| Get files / Get items behaviour in Power Automate | [In-depth analysis into Get items and Get files](https://learn.microsoft.com/en-us/sharepoint/dev/business-apps/power-automate/guidance/working-with-get-items-and-get-files) | Top count up to 5,000; Limit Entries to Folder + Include Nested Items; pagination note for lists over 5,000. |
| Send HTTP request to SharePoint | [Working with the SharePoint Send HTTP Request flow action](https://learn.microsoft.com/en-us/sharepoint/dev/business-apps/power-automate/guidance/working-with-send-sp-http-request) | Developer-focused action; REST API knowledge required. |
| Folder and file REST endpoints | [Working with folders and files with REST](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/working-with-folders-and-files-with-rest) | `GetFolderByServerRelativeUrl('...')/Files`; `%` and `#` unsupported on this endpoint. |
| Community corroboration | [Microsoft Q&A: No files returned from Get files (properties only)](https://learn.microsoft.com/en-us/answers/questions/) — Tollefson thread | Tietze (Jan 2026): identical failure on an over-threshold library; `GetFolderByServerRelativeUrl(...)/Files` as workaround. Nogueira (Feb 2025), Kesharwani (Apr 2025): same symptom. Gillissen (Mar 2026): parentheses in folder names may require encoding. |

---

## Appendix D — Test Data Inventory

Outputs captured during the investigation, with what each one established.

| Capture | Library | Method | Items | Established |
|---|---|---|---|---|
| Day 1, 06:44 | DemoFiles | REST GET browser | 8 files | First recursive success; file list baseline |
| Day 1, 06:48 | DemoFiles | REST GET flow | 481 | `%20` double-encoding drops `$filter` |
| Day 1, 06:54 | DemoFiles | REST GET + File Type | 8 | Extension filter in Uri works |
| Day 2, 03:54 | Customer | `GetFolder...$expand` | top level | Folder exists; endpoint non-recursive |
| Day 2, 03:58 | Customer | REST GET | throttle | Customer library over threshold |
| Day 2, 04:20 | Customer | Get files nested=Yes | 0 | Correct config, empty — customer's core symptom |
| Day 2, 07:28 | hr-p-c | Get files, no limit | 100 | Oldest 100 by ID; nested off |
| Day 2, 07:33 | hr-p-c (reduced) | Get files nested=Yes | 26 | **Works when library is small** |
| Day 2, 07:37 | hr-p-c (restored) | Get files, no limit | 100 | IDs 1–26954; recycle-bin holes |
| Day 2, 07:38 | hr-p-c (restored) | Get files nested=Yes | 96 | **Partial scoping at 27k** — 26 correct + 70 leaked |
| Day 2, 07:49 | hr-p-c | Get files Top 500 | 500 | All Rich-Content |
| Day 2, 07:51 | hr-p-c | Get files Top 2000 | 2,000 | 16.56 MB — cap measured |
| Day 2, 07:51 | hr-p-c | Get files Top 3000 | error | 16 MB cap confirmed |
| Day 2, 08:02 | hr-p-c | `/Files` browser | 4 | **Folder walk endpoint works at 27k** |
| Day 2, 08:23 | hr-p-c | `/Folders` browser | 2 | Second walk endpoint works at 27k |
| Day 2, 09:05 | hr-p-c | `/Files` flow | 4 | Endpoint works from inside the flow |
| Day 2, 09:26 | DemoFiles | CAML | 16 | **CAML works** (Day 1 retraction) |
| Day 2, 09:31 | DemoFiles | CAML + `$select` + `FSObjType=0` | 8 files w/ paths | Goal met on small library |
| Day 2, 09:40 | hr-p-c / Rich-Content | CAML | throttle | CAML fails at scale |
| Day 2, 09:41 | hr-p-c / Rich-Content | `/Folders` browser | **587** | **Folder walk survives the heaviest case** |

---

*End of report.*
