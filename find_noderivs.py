#!/usr/bin/env python3
"""
Find Internet-Drafts in an rsync'd id-archive that restrict derivative works,
and print them grouped by year.

Detects:
  * The "derivative works of it may not be created" boilerplate in all its
    forms (RFC 3667 / RFC 3978 era and the post-2009 Trust Legal Provisions),
    split into:
      - "except-rfc": derivatives only to publish as an RFC / translate
      - "id-only":    may not be published except as an Internet-Draft
      - "other":      any other wording (e.g. extract-section carve-outs)
  * The RFC 2026 opt-out: "NOT offered in accordance with Section 10 of
    RFC 2026" (author grants no rights beyond publishing as an I-D).
  * For drafts that exist only as XML, an ipr="noDerivatives..." or
    ipr="noModification..." attribute.

Usage:
  python3 find_noderivs.py ./id-archive
  python3 find_noderivs.py ./id-archive --unique      # one line per draft name
  python3 find_noderivs.py ./id-archive --csv out.csv
"""

import argparse
import csv
import os
import re
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

# draft-foo-bar-07.txt -> ("draft-foo-bar", "07")
NAME_RE = re.compile(r"^(draft-.+)-(\d{2})\.(txt|xml)$")

NODERIV_RE = re.compile(r"derivative works of (?:it|this document) may not be created", re.I)
EXCEPT_RFC_RE = re.compile(
    r"may not be created,? (?:except|other than) to (?:publish it as an? rfc|format it for publication as an? rfc)",
    re.I,
)
ID_ONLY_RE = re.compile(r"may not be published except as an? internet-draft", re.I)
RFC2026_RE = re.compile(r"not offered in accordance with section 10 of rfc ?2026", re.I)
XML_IPR_RE = re.compile(r'\bipr\s*=\s*["\'](no(?:Derivatives|Modification)[^"\']*)["\']', re.I)

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
DATE_RE = re.compile(rf"\b(?:{MONTHS})\.?\s+(?:\d{{1,2}},?\s+)?((?:19|20)\d\d)\b", re.I)
XML_DATE_RE = re.compile(r'<date\b[^>]*\byear\s*=\s*["\']((?:19|20)\d\d)["\']', re.I)

WS_RE = re.compile(r"\s+")


def header_year(text, is_xml):
    """Year from the draft's own first-page date; None if not found."""
    if is_xml:
        m = XML_DATE_RE.search(text)
        return int(m.group(1)) if m else None
    for line in text.splitlines()[:80]:
        if "expire" in line.lower():
            continue
        m = DATE_RE.search(line)
        if m:
            return int(m.group(1))
    return None


def classify(path):
    """Return (kind, year, year_source) if restricted, else None."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    is_xml = path.endswith(".xml")

    kind = None
    if is_xml:
        m = XML_IPR_RE.search(text)
        if m:
            kind = "xml:" + m.group(1)
    if kind is None:
        # Collapse whitespace so boilerplate wrapped across lines/pages matches.
        flat = WS_RE.sub(" ", text)
        if NODERIV_RE.search(flat):
            if ID_ONLY_RE.search(flat):
                kind = "id-only"
            elif EXCEPT_RFC_RE.search(flat):
                kind = "except-rfc"
            else:
                kind = "other"
        elif RFC2026_RE.search(flat):
            kind = "rfc2026-opt-out"
    if kind is None:
        return None

    year = header_year(text, is_xml)
    src = "header"
    if year is None:
        year = time.gmtime(os.path.getmtime(path)).tm_year
        src = "mtime"
    return kind, year, src


def collect(root):
    """One file per draft revision: prefer .txt, fall back to .xml."""
    revs = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            m = NAME_RE.match(fn)
            if not m:
                continue
            key = (m.group(1), m.group(2))
            path = os.path.join(dirpath, fn)
            if m.group(3) == "txt" or key not in revs:
                revs[key] = path
    return revs


def work(item):
    (name, rev), path = item
    r = classify(path)
    return (name, rev, path, *r) if r else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="path to the rsync'd id-archive")
    ap.add_argument("--unique", action="store_true",
                    help="one entry per draft name, under the year of its first restricted revision")
    ap.add_argument("--csv", metavar="FILE", help="also write all matches to a CSV")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    args = ap.parse_args()

    revs = collect(args.root)
    print(f"Scanning {len(revs):,} draft revisions...", file=sys.stderr)

    hits = []
    with Pool(args.jobs) as pool:
        for i, r in enumerate(pool.imap_unordered(work, revs.items(), chunksize=256), 1):
            if r:
                hits.append(r)
            if i % 25000 == 0:
                print(f"  {i:,} done, {len(hits):,} restricted", file=sys.stderr)

    hits.sort(key=lambda h: (h[4], h[0], h[1]))  # year, name, rev

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["year", "draft", "rev", "kind", "year_source", "path"])
            for name, rev, path, kind, year, src in hits:
                w.writerow([year, name, rev, kind, src, path])

    by_year = defaultdict(list)
    if args.unique:
        first = {}
        for h in hits:  # sorted by year, so first seen is earliest
            first.setdefault(h[0], h)
        for name, rev, path, kind, year, src in first.values():
            by_year[year].append(f"{name}-{rev}  [{kind}]")
    else:
        for name, rev, path, kind, year, src in hits:
            mark = "" if src == "header" else " (date from mtime)"
            by_year[year].append(f"{name}-{rev}  [{kind}]{mark}")

    for year in sorted(by_year):
        entries = sorted(by_year[year])
        print(f"\n== {year} ({len(entries)}) ==")
        for e in entries:
            print("  " + e)

    kinds = defaultdict(int)
    for h in hits:
        kinds[h[3]] += 1
    print(f"\nTotal: {len(hits):,} restricted revisions across "
          f"{len({h[0] for h in hits}):,} drafts", file=sys.stderr)
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {k:30s} {n:,}", file=sys.stderr)


if __name__ == "__main__":
    main()