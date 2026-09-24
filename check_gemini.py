#!/usr/bin/env python3
"""Check the Gemini setup and say plainly what is wrong.

    python check_gemini.py
"""
from __future__ import annotations

import os
import sys

from costmodel import assistant
from costmodel.loader import load_degrees


def main() -> int:
    key = assistant.api_key()
    print("1. API key")
    if not key:
        print("   NOT SET. The app runs fine without it, but the assistant stays hidden.")
        print("   Windows:  setx GEMINI_API_KEY \"your-key\"   then open a NEW terminal")
        print("   macOS/Linux:  export GEMINI_API_KEY=your-key")
        return 1
    print(f"   found, {len(key)} characters, starts {key[:6]}…")
    if key.strip() != key:
        print("   WARNING: the key has leading or trailing whitespace — a quoting slip.")

    print("\n2. Reaching Google")
    try:
        models = assistant.list_models()
    except assistant.GeminiError as exc:
        print(f"   FAILED: {exc}")
        text = str(exc)
        if "API key not valid" in text or "API_KEY_INVALID" in text:
            print("   -> The key is wrong or was revoked. Make a fresh one at aistudio.google.com.")
        elif "HTTP 403" in text:
            print("   -> The key is real but the Generative Language API isn't enabled for its project,")
            print("      or the key has referrer/IP restrictions. Check it in Google AI Studio.")
        elif "HTTP 429" in text:
            print("   -> Rate limited. Wait a minute and try again.")
        elif "certificate" in text.lower() or "ssl" in text.lower():
            print("   -> A TLS problem, usually a corporate network or missing certificates.")
        elif "could not connect" in text:
            print("   -> No network route: check your connection, VPN, or firewall.")
        return 1
    print(f"   reached it; {len(models)} model(s) available to this key")

    print("\n3. Model")
    pinned = os.environ.get("GEMINI_MODEL")
    if pinned:
        print(f"   GEMINI_MODEL is set to '{pinned}'")
        if pinned not in models:
            print(f"   '{pinned}' is NOT in the list above. Clear it and let the app choose:")
            print("     Windows:  setx GEMINI_MODEL \"\"    then open a NEW terminal")
            print("   Or set one of:", ", ".join(models[:8]))
    else:
        print(f"   none pinned; the app will try {assistant.resolve_model()}")
        print("   (a retired name is skipped automatically, so this usually needs no setting)")

    print("\n4. A real request")
    try:
        out = assistant.parse_query("78% average, $30k tuition, computer science with co-op",
                                    load_degrees())
    except assistant.GeminiError as exc:
        print(f"   FAILED: {exc}")
        return 1
    print(f"   parsed: {out}")
    if not out:
        print("   The call worked but produced nothing usable. Odd, but not fatal.")
        return 1

    print(f"\nAll good — answered by {assistant.current_model()}. The assistant will work in the app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
