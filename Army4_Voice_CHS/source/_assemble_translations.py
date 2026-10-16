#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble Army4 vos_translations.json from clean ASR + raw TSV translations.

Outputs a dict keyed by wav filename -> {speaker, value_ch, value_en, note}.
Only the 250 "voice" candidates from vos_en_raw_clean.json are written with
translations; sfx (48) are intentionally omitted so the dub loop copies originals.
"""
import json
import os
import sys

BASE = r"G:\Projects\ArmyMenCHS\Army4_Voice_CHS\source"
CLEAN = os.path.join(BASE, "vos_en_raw_clean.json")
TSV = os.path.join(BASE, "_parts", "all_translations_raw.tsv")
OUT = os.path.join(BASE, "vos_translations.json")

VALID = {"Sarge", "GreenArmy_Grunt", "TanArmy", "HQ_Command", "SpaceHQ",
         "Tina", "Civilian_Ann", "Civilian_Tanya", "Civilian", "Guard",
         "UnknownVoice", "Multiplayer"}


def load_tsv(path):
    d = {}
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) < 3:
                print(f"[WARN] TSV line {ln} bad: {line!r}")
                continue
            wav, speaker, value_ch = parts[0], parts[1], parts[2]
            note = parts[3] if len(parts) > 3 else ""
            d[wav] = {"speaker": speaker, "value_ch": value_ch, "note": note}
    return d


def main():
    with open(CLEAN, "r", encoding="utf-8") as f:
        clean = json.load(f)

    tsv = load_tsv(TSV)

    voice = [c for c in clean if c.get("candidate") == "voice"]
    sfx = [c for c in clean if c.get("candidate") == "sfx"]
    print(f"clean: {len(voice)} voice + {len(sfx)} sfx = {len(clean)} total")

    out = {}
    missing = []
    bad_role = []
    for c in voice:
        wav = c["wav"]
        rec = tsv.get(wav)
        if rec is None:
            missing.append(wav)
            continue
        if rec["speaker"] not in VALID:
            bad_role.append((wav, rec["speaker"]))
        entry = {
            "speaker": rec["speaker"],
            "value_ch": rec["value_ch"],
            "value_en": c.get("asr_en", ""),
        }
        if rec["note"]:
            entry["note"] = rec["note"]
        out[wav] = entry

    if missing:
        print(f"[ERROR] {len(missing)} voice wavs missing from TSV:")
        for m in missing:
            print("   ", m)
        sys.exit(1)
    if bad_role:
        print(f"[ERROR] {len(bad_role)} invalid speaker keys:")
        for w, s in bad_role:
            print("   ", w, "->", s)
        sys.exit(1)

    # sanity: confirm no duplicate keys collapsed (dict preserves uniqueness)
    print(f"assembled {len(out)} voice entries (sfx omitted: {len(sfx)})")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
