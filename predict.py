#!/usr/bin/env python3
"""Ask Claude who reaches Emerald first, from the data update.py collected. Writes data["prediction"]."""
import datetime, json, os, sys

import anthropic

from update import DATA_RE, PAGE

MIN_HOURS = 6           # at most four predictions a day, and only when LP moved since the last one


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping prediction")
        return
    text = PAGE.read_text()
    m = DATA_RE.search(text)
    data = json.loads(m.group(2))
    if data.get("champion"):
        print(f'{data["champion"]} already reached Emerald; the Oracle rests')
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    prev = data.get("prediction")
    force = "--force" in sys.argv or os.environ.get("FORCE_PREDICTION") == "true"
    if prev and not force:
        scores = [p["score"] for p in data["players"]]
        if prev.get("scores") == scores:
            print("no LP change since the last prediction; keeping it")
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
            "last_ranked_games": [{"win": g["win"], "champ": g["champ"], "kda": f'{g["k"]}/{g["d"]}/{g["a"]}'}
                                  for g in p.get("recent", [])],
        } for p in data["players"]],
    }
    schema = {
        "type": "object",
        "properties": {
            "winner": {"type": "string", "enum": names},
            "confidence": {"type": "integer", "description": "Percent chance the winner gets there first, 50-95"},
            "headline": {"type": "string", "description": "The prophecy: one dramatic line, under 14 words"},
            "reasoning": {"type": "string", "description": "The vision: 2-3 short, mystical sentences in the Oracle's voice, with no more than three numbers woven in. Not a stat list."},
            "eta": {"type": "object", "properties": {n: {"type": "string"} for n in names},
                    "required": names, "additionalProperties": False,
                    "description": "When each player reaches Emerald, as a short omen with a rough time, e.g. 'within five moons... days', '~4 days'"},
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
        system=("You are The Oracle of the Rift, an ancient hextech seer who has watched a thousand seasons. You watch over "
                "a ranked race between two League of Legends friends to see who reaches Emerald first. Study the stats given "
                "(distance to go, LP trend and pace, recent games, win rates, champion pool), then speak as the Oracle: "
                "cryptic, grand, theatrical, in omens and visions, with a wicked sense of humour. Never sound like an analyst "
                "or list stats. Weave in at most two or three real numbers as if they were signs you saw in the mists "
                "(\"one hundred and fifty steps stand between the ice witch and the emerald gate\"). Trash talk is welcome, "
                "nothing mean-spirited."),
        messages=[{"role": "user", "content": json.dumps(facts)}],
    )
    if resp.stop_reason == "refusal":
        print("model declined; keeping previous prediction")
        return
    pred = json.loads(next(b.text for b in resp.content if b.type == "text"))
    pred["confidence"] = max(50, min(95, int(pred["confidence"])))
    pred["t"] = now.isoformat(timespec="seconds")
    pred["scores"] = [p["score"] for p in data["players"]]
    if prev:
        data["prev_prediction"] = prev     # keep exactly one earlier call
    data["prediction"] = pred
    blob = json.dumps(data, separators=(",", ":"))
    PAGE.write_text(text[:m.start(2)] + blob + text[m.end(2):])
    print(json.dumps(pred, indent=2))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("predicted=true\n")


if __name__ == "__main__":
    main()
