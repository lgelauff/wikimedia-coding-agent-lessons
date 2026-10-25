# Privacy review before publishing a talk's transcript and OCR

A Wikimania talk recording (already public on Wikimedia Commons) is getting its machine transcript (Whisper) and the
OCR text of video frames published next to it. Before that, find personal data that must be replaced.

Files in your talk folder:
- `transcript.txt`: `[mm:ss] text`, the speech (recognition errors are common).
- `ocr.txt`, `screen_text.txt`: OCR of the screen in sampled frames (noisy tokens; often slide text).
- `speakers.txt`: the programme's speakers for this session (public; keep their names).

Replace (list them):
1. Names of **private individuals**: audience members (often in Q&A or when the speaker invites someone: "Maybe Anna, do you want to answer?"),
   people addressed by first name who are not on the programme, family members, friends, colleagues mentioned in a
   private context, people in anecdotes.
2. E-mail addresses, phone numbers, postal addresses, usernames + passwords, anything from a private screen (inbox,
   chat, file explorer) in the OCR.

Keep (do not list):
- programme speakers (`speakers.txt`) and anyone introducing themselves on stage as a panelist or moderator, the session
  chair, the next speaker being announced if they are on stage in a public role;
- public figures (politicians, heads of organisations in their role, authors of works cited, Wikimedia Foundation staff
  or board members named in their public role), organisations, projects, places;
- names that are part of slide content shown publicly (titles, credits, quotes with attribution).

When unsure whether someone is a private individual, list them with `"confidence": "low"` and say why.

Output: write JSON to the output path you were given:
```
{"terms": [{"term": "Anna", "variants": ["Ana"], "where": "transcript", "times": ["00:48", "16:08"],
            "confidence": "high|low", "reason": "audience member invited to speak"}],
 "ocr_blank": [{"from": "12:00", "to": "12:45", "reason": "e-mail inbox on screen"}],
 "notes": "max 40 words"}
```
`term` must be the exact spelling as it appears (case-insensitive match is applied; list every variant spelling).
Read ALL of transcript.txt; skim the OCR files for private screens or contact data. Reply with one line:
`done <n> terms`. Do not open other files, do not search the web, do not run shell commands.
