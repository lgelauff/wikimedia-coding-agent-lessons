# Playbook: BLS Public Data API v1, keyless, by the documentation

Route `bls-api-v1` in `settings/mandated-services.json` (list B, Lodewijk, 2026-10-19). Only
`https://api.bls.gov/publicAPI/v1/…` is on the route. Lodewijk asked for a recipe "that
follows the docs exactly", so everything below is from BLS's developer pages. Where the docs
contradict each other, this playbook says so. Sources and capture dates are at the end.

**Status: never called.** No request has gone to the API from this project yet. Treat the
first call as a test: one series, one request, then read the body.

## Limits: BLS's numbers and ours

| | BLS v1 (unregistered) | BLS v2 (registered) | **Our policy** |
|---|---|---|---|
| Queries per day | 25 | 500 | **within 25** |
| Series per query | 25 | 50 | up to 25 |
| Years per query | 10 | 20 | up to 10 |
| Request rate | 50 per 10 s | 50 per 10 s | **≤1 request per 10 s**, one at a time |

- **Pack each query.** The daily cap counts queries, not series: 25 series × 10 years in one POST
  costs one of the 25. Plan the whole job as a list of POSTs before sending any.
- **Count every request** against the 25, failed ones included. The docs do not say whether a
  request that returns an error counts [unverified], so assume it does.
- On HTTP **429**, stop for the day: the FAQ ties 429 to the query limits, and the terms let
  BLS block a user who "attempted to exceed or circumvent these limits". On 5xx, wait 10 minutes,
  then try once more; on a second failure, stop for the day.
- **v2 is not ours yet.** Registration (email, organisation name, a CAPTCHA, renewed yearly) is
  Lodewijk's task and has not been done. Never send a `registrationkey`; never call `/v2/`.
  v1 signatures also work on v2, so nothing here changes when the key arrives, except the limits.

## The three v1 requests (no others exist)

All use the same URL. JSON requests need `Content-Type: application/json`, or BLS answers
**415 Unsupported Media Type**.

1. **Single series, last three years**: `GET`, series id appended to the URL.
   ```
   GET https://api.bls.gov/publicAPI/v1/timeseries/data/LAUCN040010000000005
   ```
2. **Several series, last three years**: `POST`, up to 25 ids.
   ```
   POST https://api.bls.gov/publicAPI/v1/timeseries/data/
   Content-Type: application/json

   {"seriesid":["LAUCN040010000000005","LAUCN040010000000006"]}
   ```
3. **One or more series, chosen years**: `POST`, `startyear` and `endyear` both required, as
   four-digit strings, at most a 10-year span.
   ```
   {"seriesid":["LAUCN040010000000005"],"startyear":"2010","endyear":"2012"}
   ```

Not in v1: `calculations` (net and percent changes), `annualaverage`, `catalog` (series
titles and metadata), the latest/popular/all-surveys endpoints. The FAQ is explicit: v1
"only returns raw data from BLS surveys; it does not include metadata". So a v1 response
does not tell you what a series *is*; record the id's meaning from the format lookup below.

Send the project User-Agent. See *Open questions* on contact details.

## Reading the response: check the body, not the status

A request with a wrong series id still returns `"status":"REQUEST_SUCCEEDED"`, with the
problem in `message` and an empty `data` list. The FAQ's own example:

```
{"status":"REQUEST_SUCCEEDED","responseTime":104,
 "message":["Invalid Series for Series laucn21219003!"],
 "Results":[{"series":[{"seriesID":"laucn21219003!","data":[]}]}]}
```

So after every call:

1. HTTP status. 200 = success, 202 = "Your request is processing" (the docs say no more;
   wait at least 10 s before repeating, and count the repeat against the 25), 400 bad syntax, 401 not authorised, 404 not found,
   415 = missing JSON content type, 429 = over the limit, 500 = server error.
2. `status`: anything other than `REQUEST_SUCCEEDED` is a failure; keep the body.
3. **`message`: must be empty.** Known messages and what the FAQ says they mean:
   - "Series does not exist" / "Invalid Series": the id is malformed. Ids are upper case,
     with no special characters except `_`, `-`, `#`.
   - "No Data Available for Series": the year range is outside the database.
   - "Database is locked for Series": the data is temporarily unavailable; try another day.
4. Per series: a non-empty `data` list. Each point has `year`, `period` (`M01`–`M12`
   for months; `M13` with `periodName` "Annual" in the docs' sample; other surveys use other
   codes, so read `periodName`), `periodName`, `value` (a **string** in every sample: parse it,
   and treat a non-numeric value as missing [unverified: no such case seen]), and `footnotes` (e.g. `{"code":"P","text":"Preliminary."}`).
   Keep the footnotes: preliminary values are revised later.

**The docs disagree on one shape.** The v1 signature page's sample responses show
`"Results": [ { "series": [...] } ]`, a list, while BLS's own Python sample code reads
`json_data['Results']['series']`, an object. Accept both: if `Results` is a list, take its
first element.

## Finding a series id

The FAQ says: "The BLS Public Data API requires users to know the series ID… We do not
currently have a catalogue of series IDs, but all BLS series IDs follow a similar format."
So the id is built, not searched:

1. **Find the survey's format** on `www.bls.gov/help/hlpforma.htm`: each survey shows its
   prefix and the positions of its fields. Example from that page, National Employment,
   Hours, and Earnings, `CEU0800000003`: positions 1–2 `CE` prefix, 3 `U` seasonal adjustment
   code (meanings in the survey's `.seasonal` file), 4–11 `08000000` supersector and industry, 12–13 `03` data type.
2. **Look up the codes** in the survey's code files, linked from the same page:
   `download.bls.gov/pub/time.series/<prefix>/<prefix>.<field>` (e.g. `ce/ce.industry`,
   `ce/ce.datatype`, `ce/ce.seasonal`).
3. **Neither host is on our route.** `www.bls.gov` returned 403 "Access Denied" to our
   User-Agent on 2026-10-19, and `download.bls.gov` is not approved. Read both through the
   Internet Archive (`web.archive.org/web/2026id_/<url>`; the bodies may arrive gzip-compressed),
   or ask the human for the ids. Do not fetch them directly.
4. **Write down what each id means** (survey, area, industry, measure, seasonal adjustment),
   with the code-file capture you read it from. v1 will not tell you later.
5. **Validate with one GET** (signature 1) before a batch: a malformed id costs one query
   instead of a wasted 25-series POST.

## Citing

The API terms require two things: cite **the date the data were retrieved through the API**,
and state verbatim: "BLS.gov cannot vouch for the data or analyses derived from these data
after the data have been retrieved from BLS.gov." Name the series id, its meaning, and
whether it is seasonally adjusted. Never use the BLS logo.

## Must not

- **Modify or misrepresent the data** and still cite BLS (terms).
- **Exceed or circumvent the limits**, for example by spreading calls over several clients or
  addresses. The terms allow BLS to block the user permanently.
- **Scrape `www.bls.gov` or `data.bls.gov`** for data the API does not give. BLS's usage
  policy prohibits "excessive robot activity" and it blocks in real time.
- Call `/v2/`, send a registration key, or register.

## Open questions (Lodewijk)

1. **Contact details in the User-Agent?** BLS's usage policy (`/bls/pss.htm`) reserves the
   right "to block robots that do not contain information that can be used to contact the
   owner". Our UA carries a GitHub URL but no e-mail, and `www.bls.gov` blocked it with a 403
   on 2026-10-19. Whether `api.bls.gov` does the same is unknown until the first call. Adding
   your e-mail is an identifying header, so it needs your yes (route-vetting, registration rule).
2. **v2 registration** (your task): 500 queries/day, 50 series, 20 years, and series
   metadata. Needs an e-mail, an organisation name and a CAPTCHA, renewed yearly.

## Sources (Internet Archive captures; `www.bls.gov` answers 403 to our UA)

- FAQs, `bls.gov/developers/api_faqs.htm`: capture 20261012035934 (page modified 2023-08-30).
- v1 signatures, `bls.gov/developers/api_signature.htm`: 20260819054557 (modified 2014-10-16).
- v2 signatures, `api_signature_v2.htm`: 20261012055645 (read for the v1/v2 differences only).
- Python sample code, `api_python.htm`: 20260929155415.
- API terms of service, `termsOfService.htm`: 20260929155216 (modified 2023-08-30).
- Series id formats, `bls.gov/help/hlpforma.htm`: 20261012051350 (modified 2026-01-22).
- Privacy and usage policy, `bls.gov/bls/pss.htm`: 20260927005432, section "Automated
  retrieval program (robot) activity".
- Robots: `www.bls.gov/robots.txt` 20260819054307 (crawlers barred only from admin and print
  paths); `api.bls.gov/robots.txt` 20250524180626 (`Disallow: /`, overridden by the documented
  API under the route-vetting rule).
