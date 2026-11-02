#!/usr/bin/env python3
"""Print Cursor usage cost for one person or a team.

Reads CURSOR_ADMIN_API_KEY. Never prints the key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API = "https://api.cursor.com/teams/filtered-usage-events"
PAGE_SIZE = 200
MAX_PAGES = 50


def money(cents: float) -> str:
    return f"${cents / 100:,.2f}"


def window(days: int) -> tuple[int, int]:
    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def post(key: str, body: dict) -> dict:
    request = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = __import__("base64").b64encode(f"{key}:".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"Cursor API {exc.code}: {detail}") from exc


def events(key: str, start: int, end: int, email: str | None) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        body: dict = {"startDate": start, "endDate": end, "page": page, "pageSize": PAGE_SIZE}
        if email:
            body["email"] = email
        payload = post(key, body)
        rows.extend(payload.get("usageEvents") or [])
        if not (payload.get("pagination") or {}).get("hasNextPage"):
            return rows
        page += 1
    raise SystemExit(f"Stopped after {MAX_PAGES} pages. Narrow the window with --days.")


def day_of(event: dict) -> str:
    raw = event.get("timestamp") or "0"
    stamp = int(raw) / 1000
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d")


def report(rows: list[dict], scope: str, days: int) -> str:
    by_day: dict[tuple[str, str], float] = defaultdict(float)
    models: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_model: dict[str, float] = defaultdict(float)
    for event in rows:
        email = event.get("userEmail") or "(unknown)"
        day = day_of(event)
        charged = float(event.get("chargedCents") or 0)
        model = event.get("model") or "(unknown)"
        by_day[(day, email)] += charged
        models[(day, email)][model] += 1
        by_model[model] += charged

    day_word = "day" if days == 1 else "days"
    lines = [f"Cursor {scope} usage, last {days} {day_word} (UTC). Charged includes the Cursor token fee when it applies."]
    if not rows:
        lines.append("No events in this window.")
        return "\n".join(lines)

    total = sum(by_day.values())
    event_word = "event" if len(rows) == 1 else "events"
    lines.append(f"Charged: {money(total)} across {len(rows)} {event_word}.")
    lines.append("")
    if scope == "team":
        lines.append(f"{'Day':<12} {'Email':<36} {'Charged':>10}  Top model")
    else:
        lines.append(f"{'Day':<12} {'Charged':>10}  Top model")
    for day, email in sorted(by_day):
        top = max(models[(day, email)], key=models[(day, email)].get)
        charged = money(by_day[(day, email)])
        if scope == "team":
            lines.append(f"{day:<12} {email:<36} {charged:>10}  {top}")
        else:
            lines.append(f"{day:<12} {charged:>10}  {top}")
    if scope == "team":
        people: dict[str, float] = defaultdict(float)
        for (_day, email), charged in by_day.items():
            people[email] += charged
        lines.append("")
        lines.append("By person")
        for email, person_cents in sorted(people.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  {email:<36} {money(person_cents):>10}")
    lines.append("")
    lines.append("By model")
    for model, charged in sorted(by_model.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"  {model:<36} {money(charged):>10}")
    lines.append("")
    lines.append("Members with no events in this window are omitted.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cursor usage cost for one person or a team.")
    parser.add_argument("--scope", choices=("me", "team"), default="me")
    parser.add_argument("--email", default=os.environ.get("CURSOR_USER_EMAIL", ""))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.days <= 30:
        raise SystemExit("--days must be from 1 to 30.")
    key = os.environ.get("CURSOR_ADMIN_API_KEY", "")
    if not key:
        raise SystemExit("Set CURSOR_ADMIN_API_KEY to a team Admin API key. Do not commit it.")
    email = args.email.strip() if args.scope == "me" else None
    if args.scope == "me" and not email:
        raise SystemExit("Set CURSOR_USER_EMAIL or pass --email for --scope me.")
    start, end = window(args.days)
    print(report(events(key, start, end, email), args.scope, args.days))


if __name__ == "__main__":
    main()
