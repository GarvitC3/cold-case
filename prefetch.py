#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

from app import nasa
from app.config import CACHE_DIR, SITES, SITE_BY_ID

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-download the full record")
    ap.add_argument("--site", choices=sorted(SITE_BY_ID), help="only this site")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    today = date.today()
    sites = [SITE_BY_ID[args.site]] if args.site else SITES
    print(f"NASA POWER daily T2M  ->  {CACHE_DIR}\nToday: {today}   Record starts: {nasa.RECORD_START}\n")

    ok, failed = 0, []
    for i, site in enumerate(sites):
        cached = nasa.read_cache(site.id)
        if cached and not args.force and cached.as_of and (today - cached.as_of).days <= 8 \
                and (today - date.fromisoformat((cached.meta.get("fetched_at") or "2000-01-01")[:10])).days < 1:
            print(f"  {site.short:<12} already fresh (as of {cached.as_of}) — skipped")
            ok += 1
            continue
        t0 = time.time()
        try:
            s = nasa.refresh_site(site, today, full=args.force)
            miss = int(__import__("numpy").isnan(s.values).sum())
            print(f"  {site.short:<12} ok   {len(s.values):>6} days  as of {s.as_of}  "
                  f"missing {miss:>3}  ({time.time() - t0:.1f}s)")
            ok += 1
        except Exception as e:
            print(f"  {site.short:<12} FAILED  {e}")
            failed.append(site.short)
        if i < len(sites) - 1:
            time.sleep(1.0)

    print()
    if failed:
        print(f"{ok}/{len(sites)} sites ready. Failed: {', '.join(failed)}. Existing caches (if any) were left untouched.")
        print("Check the network and run this again — it resumes where it left off.")
        return 1
    print(f"All {ok} sites ready. COLD CASE can now run fully offline.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
