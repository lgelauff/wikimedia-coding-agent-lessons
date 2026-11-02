"""LiftWing llm-clef-flash decision model (:predict only), per fuzheado/Wikipedia-AI-Skills
(.claude/skills/wikimedia-ml-services/references/clef-flash-decision-models.md):
state + typed questions + up to 4 base64 images (downscaled to 640 px server-side) -> a probability per answer.
The question set changes the scores, so schemas are fixed and versioned here. Errors are UNMEASURED, never 0.
"""
import base64
import io
import json
import time
import urllib.request

import cv2

URL = "https://api.wikimedia.org/service/lw/inference/v1/models/llm-clef-flash:predict"
UA = None                # set by wmvid.configure()
SCHEMA_VERSION = "2026-10-19.1"
CHARGE = None        # set by wmvid.stage_clef: charges every attempt against the batch budget

SCREEN_Q = {"screen": {"type": "choice",
                       "instructions": "What does the projection screen (or the full frame, if the video shows a "
                                       "screen capture) show at this moment?",
                       "criteria": {"slide": "a presentation slide",
                                    "browser": "a web browser, website, or other software, not a slide",
                                    "blank": "a projection screen that is blank or shows nothing readable",
                                    "none": "no projection screen or slide is visible (speaker, audience, room)"}}}


def b64(path, width=640):
    img = cv2.imread(path)
    if img.shape[1] > width:
        img = cv2.resize(img, (width, int(img.shape[0] * width / img.shape[1])))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return base64.b64encode(buf.tobytes()).decode()


def predict(state, questions, images, tries=6):
    body = json.dumps({"model": "llm-clef-flash", "state": state, "questions": questions,
                       "images": [b64(p) for p in images]}).encode()
    for i in range(tries):
        if CHARGE:
            CHARGE("clef_calls")                 # before the attempt; a spent budget raises out of here
        try:
            req = urllib.request.Request(URL, data=body, headers={"User-Agent": UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())["answers"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                # the gateway rate-limits anonymous use and says how long to wait (seen: 804 s); honour it
                wait = e.headers.get("Retry-After")
                time.sleep(min(int(wait), 1200) + 5 if wait and wait.isdigit() else 30 * (i + 1))
                continue
            return {"error": f"HTTP {e.code}"}
        except Exception as e:                   # noqa: BLE001
            if i == tries - 1:
                return {"error": str(e)[:200]}
            time.sleep(10)
    return {"error": "unmeasured"}


def screen_type(frame_path):
    return predict("A frame from a recorded conference talk.", SCREEN_Q, [frame_path])


def which_page(frame_path, page_paths, spoken=""):
    """frame + up to 3 candidate page renders -> choice among them (or none)."""
    crit = {f"page{i + 1}": f"image {i + 2} (candidate slide {i + 1})" for i in range(len(page_paths))}
    crit["none"] = "none of the candidate slides is the one shown"
    q = {"match": {"type": "choice",
                   "instructions": "Image 1 is a frame from a recorded talk. Which candidate slide image is the one "
                                   "shown on the projection screen in image 1?",
                   "criteria": crit}}
    state = "Spoken around this moment: " + spoken[:1500] if spoken else "A frame from a recorded conference talk."
    return predict(state, q, [frame_path] + list(page_paths))
