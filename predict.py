#!/usr/bin/env python3
"""Ask Claude who reaches Emerald first, from the data update.py collected. Writes data["prediction"]."""
import datetime, json, os, sys

import anthropic

from update import DATA_RE, PAGE

MIN_HOURS = 12          # at most two predictions a day, even if LP moves every game


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping prediction")
        return
    text = PAGE.read_text()
    m = DATA_RE.search(text)
    data = json.loads(m.group(2))
    now = datetime.datetime.now(datetime.timezone.utc)
    prev = data.get("prediction")
    if prev and "--force" not in sys.argv:
        if os.environ.get("LP_CHANGED") == "false":
            print("no LP change; keeping previous prediction")
            return
        age = now - datetime.datetime.fromisoformat(prev["t"])
        if age < datetime.timedelta(hours=MIN_HOURS):
            print(f"last prediction is {age} old; skipping")
            return

    names = [p["name"] for p in data["players"]]
    facts = {
        "goal": "First to reach Emerald IV in OCE Ranked Solo/Duo",
        "score_scale": "score = LP above Iron IV 0 LP; each division is 100, each tier 400. Emerald IV = 2000.",
        "now_utc": now.isoformat(timespec="minutes"),
        "players": [{
            "name": p["name"], "rank": f'{p["tier"]} {p["div"] or ""} {p["lp"]} LP'.replace("  ", " "),
            "score": p["score"], "lp_to_emerald": max(0, data["goal"] - p["score"]),
            "season_record": f'{p["wins"]}W {p["losses"]}L',
            "top_champions_this_season": p.get("champs", []),
            "score_history_utc": [[h["t"][:16], h["s"]] for h in p.get("hist", [])][-40:],
        } for p in data["players"]],
    }
    schema = {
        "type": "object",
        "properties": {
            "winner": {"type": "string", "enum": names},
            "confidence": {"type": "integer", "description": "Percent chance the winner gets there first, 50-95"},
            "headline": {"type": "string", "description": "One punchy line, under 12 words, like a League caster"},
            "reasoning": {"type": "string", "description": "2-3 sentences citing the actual numbers"},
            "eta": {"type": "object", "properties": {n: {"type": "string"} for n in names},
                    "required": names, "additionalProperties": False,
                    "description": "Rough estimate per player of when they hit Emerald, e.g. '~4 days'"},
        },
        "required": ["winner", "confidence", "headline", "reasoning", "eta"],
        "additionalProperties": False,
    }
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        system=("You are the analyst for a friendly race between two League of Legends friends. "
                "Predict who reaches Emerald first using only the stats given: distance to go, LP trend and "
                "pace from the history, games played (activity), win rates, and champion pool. "
                "Be playful but grounded; trash talk is welcome, nothing mean-spirited."),
        messages=[{"role": "user", "content": json.dumps(facts)}],
    )
    if resp.stop_reason == "refusal":
        print("model declined; keeping previous prediction")
        return
    pred = json.loads(next(b.text for b in resp.content if b.type == "text"))
    pred["confidence"] = max(50, min(95, int(pred["confidence"])))
    pred["t"] = now.isoformat(timespec="seconds")
    data["prediction"] = pred
    blob = json.dumps(data, separators=(",", ":"))
    PAGE.write_text(text[:m.start(2)] + blob + text[m.end(2):])
    print(json.dumps(pred, indent=2))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("predicted=true\n")


if __name__ == "__main__":
    main()
