#!/bin/sh
# arXiv conformance checks. Run from the directory holding main.tex, AFTER a build
# (it reads main.log and main.pdf). Portable /bin/sh; needs pdffonts and pdfinfo
# from poppler for the font and figure checks, which it skips rather than fails
# if they are absent.
#
# Requires these lines in the preamble, because class defaults cannot be assumed:
#   \typeout{ARXIVDIMS textwidth=\the\textwidth}      (and textheight, paperwidth,
#   paperheight, oddsidemargin, topmargin, headheight, headsep)
#
# See agent-tooling/playbooks/arxiv-submission.md for why each check exists.
#
# These assert the rules on arXiv's "Policies for Format Requirements" page
# (retrieved 2026-08-28) that a LaTeX source can actually violate silently.
# Everything here is a returnable defect, not a style preference -- arXiv's own
# wording is "If your submission does not meet these requirements, it may be
# returned to you for correction."
#
# What this does NOT check, so nobody reads a pass as more than it is:
#   complete references, author list, whether code/data links resolve, and
#   whether the figures were regenerated rather than merely clamped.
set -u
fail=0
say() { printf '   %s\n' "$1"; }
bad() { printf '   FAIL: %s\n' "$1"; fail=1; }

echo "-- arXiv format requirements --"

# 1. Type size. arXiv: "10 to 14 point type".
pt=$(sed -n 's/^\\documentclass\[\([0-9]*\)pt.*/\1/p' main.tex | head -1)
case "$pt" in
  1[0-4]) say "type size ${pt}pt (arXiv allows 10-14)" ;;
  "")     bad "no NNpt option on \\documentclass -- LaTeX defaults to 10pt, which passes, but say so explicitly" ;;
  *)      bad "type size ${pt}pt is outside arXiv's 10-14pt range" ;;
esac

# 2. Margins. arXiv: "Minimum 1\" page margin" = 72.27pt.
# Read the geometry \typeout writes into main.log on every build, rather than
# assuming the class defaults still hold after a geometry or class change.
dims=$(grep -h '^ARXIVDIMS ' main.log 2>/dev/null | sed 's/^ARXIVDIMS //; s/pt$//' | sort -u)
if [ -z "$dims" ]; then
  bad "no ARXIVDIMS lines in main.log -- build first (make), then re-run"
else
  eval "$dims"
  # Measured to the TEXT BODY, which is what the rule is about. \topmargin runs
  # to the top of the head and goes negative under geometry, so it needs
  # headheight and headsep added back; using it raw reported 0.67in for a page
  # whose text starts at 3cm. The head is empty under \pagestyle{plain}.
  left=$(awk "BEGIN{printf \"%.2f\", 72.27 + $oddsidemargin}")
  right=$(awk "BEGIN{printf \"%.2f\", $paperwidth - 72.27 - $oddsidemargin - $textwidth}")
  top=$(awk "BEGIN{printf \"%.2f\", 72.27 + $topmargin + $headheight + $headsep}")
  bottom=$(awk "BEGIN{printf \"%.2f\", $paperheight - (72.27 + $topmargin + $headheight + $headsep) - $textheight}")
  say "body margins: left ${left}pt  right ${right}pt  top ${top}pt  bottom ${bottom}pt  (1in = 72.27pt)"
  awk "BEGIN{exit !($left >= 72.27 && $right >= 72.27 && $top >= 72.27 && $bottom >= 72.27)}" \
    || bad "a body margin is under arXiv's 1in minimum"
fi

# 3. \today. arXiv rebuilds the PDF on its own machines, and again on every
# later version, so \today stamps their build date rather than the author's.
if grep -q '\\date{[^}]*\\today' main.tex; then
  bad "\\today in \\date -- arXiv's own guidance names this; use a fixed string"
else
  say "\\date carries no \\today"
fi

# 4. Line numbers are on arXiv's "should not have" list.
if grep -qE '^[^%]*\\usepackage(\[[^]]*\])?\{lineno\}|\\linenumbers' main.tex sections/[0-9][0-9]-*.tex 2>/dev/null; then
  bad "line numbers are enabled -- arXiv prohibits them"
else
  say "no line numbers"
fi

# 5. Figures reaching the page at anything other than their natural size. Not
# an arXiv rule -- it is the house rule (matplotlib/lessons.md: "design figures
# at final physical size and insert without LaTeX rescaling, so point sizes are
# real"). Reported, never fatal: \maxwidth clamping an oversized figure is the
# correct behaviour, and this is how you see that it is still happening.
echo "-- figure sizing: rescaled, or short of the measure (house rule: neither) --"
awk -v TW="${textwidth:-0}" '/^<.*figures.*id=[0-9]+, [0-9.]+pt x /{
       f=$1; sub(/^</,"",f); sub(/,$/,"",f); sub(/.*\//,"",f);
       for(i=1;i<=NF;i++) if($i ~ /pt$/){nat=$i; break}
     }
     /Requested size:/{
       if(f!=""){
         req=$4;
         gsub(/pt/,"",nat); gsub(/pt/,"",req);
         d = (nat>0) ? (req/nat) : 1;
         # RASTER AND VECTOR FAIL DIFFERENTLY, so they are judged differently.
         # "Never rescale" is a rule about VECTOR charts: their text is drawn at a
         # designed point size and scaling it breaks the 7pt floor. A screenshot has
         # no point sizes -- it has pixels, and shrinking it RAISES its effective
         # resolution. Scoring a downscaled PNG as "RESCALED to 44%" is a false alarm
         # that would sit in this report forever, training everyone to ignore it.
         # For raster the real question is dpi: natural pt at 72dpi is the pixel
         # count, so dpi = 72 * natural / requested.
         israster = (f ~ /\.(png|jpg|jpeg|PNG|JPG|JPEG)$/);
         if (israster) {
           dpi = (req>0) ? 72*nat/req : 0;
           if (dpi < 150)       tag = sprintf("LOW RES, %.0f dpi as placed", dpi);
           else if (dpi < 300)  tag = sprintf("%.0f dpi -- fine on screen, soft in print", dpi);
           else                 tag = sprintf("%.0f dpi", dpi);
         }
         else if (d<=0.999 || d>=1.001) tag = sprintf("RESCALED to %.0f%%", d*100);
         else if (req < TW*0.95)        tag = sprintf("UNDERSIZED, %.0fpt short of the measure", TW-req);
         else                           tag = "1:1";
         printf "   %-28s %8.2fpt -> %8.2fpt   %s\n", f, nat, req, tag;
         f=""
       }
     }' main.log 2>/dev/null > /tmp/arxiv_figsizes.$$
if [ -s /tmp/arxiv_figsizes.$$ ]; then
  cat /tmp/arxiv_figsizes.$$
  n=$(grep -c RESCALED /tmp/arxiv_figsizes.$$)
  [ "$n" -gt 0 ] && say "^ $n figure(s) rescaled: clamped so they stay out of the margin, but they should be regenerated at the document width"
  # THE OTHER HALF OF THE SAME DEFECT, and the half that hid for two days. The Gin
  # default is width=\maxwidth, which clamps an oversized figure but never enlarges
  # an undersized one -- so a figure built at the OLD 360pt block arrives at its
  # natural size, scores a clean "1:1", and is simply 67pt short of the measure.
  # It does not look broken. Nothing else in the build says a word about it.
  # A deliberately narrow figure is a legitimate exception; this reports, never fails.
  lr=$(grep -c 'LOW RES' /tmp/arxiv_figsizes.$$)
  [ "$lr" -gt 0 ] && bad "$lr raster figure(s) under 150 dpi as placed -- recapture at a higher resolution"
  u=$(grep -c UNDERSIZED /tmp/arxiv_figsizes.$$)
  [ "$u" -gt 0 ] && say "^ $u figure(s) undersized: not rescaled, just narrower than the text -- regenerate at DOC_WIDTH_IN"
else
  say "no figures found in main.log"
fi
rm -f /tmp/arxiv_figsizes.$$

# 5b. OPTIONAL, PROJECT-SPECIFIC: if a plotting library sizes figures to the text
# width, assert that constant equals \textwidth from the built document. Nothing
# else links them and they drift silently. Wire it in per project -- there is no
# portable way to find the constant.

# 5c. Fonts in the built PDF. arXiv wants Type 1 outlines and complete embedding;
# a bitmap (Type 3) font renders badly on screen and prints worse, and a font that
# is not embedded may simply not be there on the reader's machine.
#
# THE ONE THAT ACTUALLY BIT US was neither. [T1]{fontenc} with no text font chosen
# silently resolved to CM-SUPER -- Type 1, embedded, and passing both of the checks
# above, while being machine-traced from bitmaps and visibly uneven on the page.
# The document was also set in two families at once, cm-super for text and original
# Computer Modern for math. Nothing complained; the author noticed it by eye.
# Hence the third assertion: this paper is set in Latin Modern, and an SF*/CM* face
# reappearing means \usepackage{lmodern} was dropped.
echo "-- fonts in the PDF --"
if ! command -v pdffonts >/dev/null 2>&1; then
  say "pdffonts not installed -- skipped"
elif [ ! -f main.pdf ]; then
  say "no main.pdf -- build first"
else
  t3=$(pdffonts main.pdf | awk 'NR>2 && $2=="Type" && $3=="3"' | wc -l | tr -d ' ')
  noemb=$(pdffonts main.pdf | awk 'NR>2 && $(NF-3)=="no"' | wc -l | tr -d ' ')
  legacy=$(pdffonts main.pdf | awk 'NR>2{print $1}' | grep -cE '\+(SF|CM)[A-Z]' | tr -d ' ')
  fams=$(pdffonts main.pdf | awk 'NR>2{sub(/^[A-Z]+\+/,"",$1); print $1}' | sed 's/[0-9].*//' | sort -u | tr '\n' ' ')
  say "families: $fams"
  [ "$t3" -eq 0 ]     && say "no Type 3 (bitmap) fonts"        || bad "$t3 Type 3 (bitmap) font(s) -- arXiv wants Type 1"
  [ "$noemb" -eq 0 ]  && say "every font embedded"             || bad "$noemb font(s) not embedded"
  [ "$legacy" -eq 0 ] && say "no cm-super / raw Computer Modern" \
    || bad "$legacy cm-super or CM face(s) -- has \\usepackage{lmodern} been dropped?"
fi


exit $fail
