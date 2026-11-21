#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Measure how distinctly skill descriptions route requests."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import random
import re
import sys
from statistics import mean
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


HERE = Path(__file__).resolve().parent
CORPUS = HERE / "distinctiveness"
sys.path.insert(0, str(HERE.parent / "scripts"))

import skill_paths  # noqa: E402

NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SEED = 52026
K1, B = 1.2, 0.75


def skill_cards(root, flat):
    """SKILL.md paths for a flat (installed/scratch) or categorized checkout.

    A flat card is only scanned when the caller passes an explicit skills
    directory; the checkout default is categorized-only.
    """
    cards = list(root.glob("*/SKILL.md")) if flat else []
    cards += [path / "SKILL.md" for path in skill_paths.skill_dirs(root)
              if (path / "SKILL.md").is_file()]
    return sorted(set(cards))


def load_catalog(root, overrides, flat):
    skills = {}
    for path in skill_cards(root, flat):
        # hoa uses a plain name, a folded description, and a top-level visibility flag.
        parts = re.split(r"^---\s*$", path.read_text(encoding="utf-8-sig"), maxsplit=2, flags=re.M)
        if len(parts) != 3 or parts[0]:
            raise ValueError(f"{path}: missing frontmatter")
        front = parts[1]
        name = path.parent.name
        if not re.fullmatch(NAME, name) or not re.search(rf"^name: {name}[ \t]*$", front, re.M):
            raise ValueError(f"{path}: name must match the skill directory")
        field = re.search(r"^description: ([^\n]+)((?:\n[ \t]+[^\n]+)*)", front, re.M)
        if not field:
            raise ValueError(f"{path}: missing description")
        desc, continuation = field.groups()
        if desc.rstrip() == ">-" and continuation:
            desc = " ".join(line.strip() for line in continuation.splitlines() if line.strip())
        elif continuation or desc.startswith((">", "|", '"', "'")) or not desc.strip():
            raise ValueError(f"{path}: description must be plain text or use hoa's >- format")
        hidden = bool(re.search(r"^disable-model-invocation: true[ \t]*(?:#.*)?$", front, re.M))
        if name in skills:
            raise ValueError(f"{root}: duplicate skill name {name!r}: "
                             f"{skills[name]['path']} and {path}")
        skills[name] = dict(description=desc, hidden=hidden, path=path.as_posix())
    if not skills:
        raise ValueError(f"{root}: no skill cards found")
    if overrides:
        replacements = json.loads(overrides.read_text(encoding="utf-8-sig"))
        if not isinstance(replacements, dict):
            raise ValueError(f"{overrides}: expected a JSON object mapping skill names to descriptions")
        for name, description in replacements.items():
            if name not in skills or not isinstance(description, str) or not description.strip():
                raise ValueError(f"{overrides}: {name!r} must be a known skill with a nonempty description")
            skills[name]["description"] = description
    return dict(sorted(skills.items()))


def load_queries(path):
    queries = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            qid = row["id"]
            if "expected" in row:
                target, language, request = (row[k] for k in ("expected", "language", "request"))
            else:
                target, language, request = (row[k] for k in ("skill", "lang", "text"))
            if (not all(isinstance(s, str) and s.strip() for s in (qid, target, language, request))
                    or not re.fullmatch(NAME, target) or qid in queries or language not in {"en", "zh", "zh-CN"}):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{path}:{number}: invalid or duplicate query row") from None
        queries[qid] = dict(expected=target, language="zh" if language == "zh-CN" else language, request=request)
    if not queries:
        raise ValueError(f"{path}: no queries")
    return queries


def tokens(value):
    return re.findall(r"[^\W_]+", value.lower())


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def lexical(skills, queries):
    docs = {name: Counter(tokens(name + " " + skill["description"])) for name, skill in skills.items()}
    df = Counter(term for doc in docs.values() for term in doc)
    n = len(docs)
    avg = mean(doc.total() for doc in docs.values())
    idf = {term: math.log1p((n - count + .5) / (count + .5)) for term, count in df.items()}
    norm = {name: K1 * (1 - B + B * doc.total() / avg) for name, doc in docs.items()}
    weights = {name: {t: idf[t] * (1 + K1) * tf / (tf + norm[name]) for t, tf in doc.items()}
               for name, doc in docs.items()}
    rows = {}
    by_language = defaultdict(list)
    for qid, query in queries.items():
        target = query["expected"]
        terms = sorted(set(tokens(query["request"])) & df.keys())
        scores = {name: sum(weights[name].get(t, 0) for t in terms) for name in docs}
        ranking = sorted(scores, key=lambda name: (-scores[name], name))
        best = ranking[0]
        wrong = next((name for name in ranking if name != target), None)
        rank = ranking.index(target) + 1 if target in scores else None
        row = rows[qid] = dict(
            top1=best, top1_score=scores[best], top_ties=sum(s == scores[best] for s in scores.values()),
            rank=rank, expected_score=scores.get(target), best_wrong=wrong,
            margin=scores[target] - scores[wrong] if rank and wrong else None,
        )
        if rank:
            by_language[query["language"]].append(row)
    bm25 = {}
    for lang, group in sorted(by_language.items()):
        margins = [row["margin"] for row in group if row["margin"] is not None]
        bm25[lang] = dict(
            n=len(group), top1=mean(row["rank"] == 1 for row in group),
            mrr=mean(1 / row["rank"] for row in group),
            mean_margin=mean(margins) if margins else None,
            positive_top1=mean(row["rank"] == 1 and row["expected_score"] > 0 for row in group),
            positive_mrr=mean(1 / row["rank"] if row["expected_score"] > 0 else 0 for row in group),
            all_zero=sum(row["top1_score"] == 0 for row in group),
            top_tied=sum(row["top_ties"] > 1 for row in group),
        )

    vectors = {name: {t: tf * (1 + math.log((1 + n) / (1 + df[t]))) for t, tf in doc.items()}
               for name, doc in docs.items()}
    norms = {name: math.sqrt(sum(w * w for w in vector.values())) for name, vector in vectors.items()}
    neighbors = dict.fromkeys(docs)
    for index, (a, va) in enumerate(vectors.items()):
        for b in list(vectors)[index + 1:]:
            vb = vectors[b]
            dot = sum(va[t] * vb[t] for t in sorted(va.keys() & vb.keys()))
            cosine = dot / (norms[a] * norms[b])
            for name, other in ((a, b), (b, a)):
                previous = neighbors[name]
                if previous is None or cosine > previous["cosine"]:
                    neighbors[name] = dict(skill=other, cosine=cosine)
    return bm25, rows, neighbors


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def llm_config(args):
    base, model, key = (os.environ.get("DISTINCTIVENESS_" + suffix) for suffix in
                        ("BASE_URL", "MODEL", "API_KEY"))
    if args.pi_provider:
        try:
            provider = json.loads(args.pi_models.read_text(encoding="utf-8-sig"))["providers"][args.pi_provider]
            base = base or provider.get("baseUrl")
            models = provider.get("models", [])
            if not model and len(models) == 1:
                model = models[0]["id"]
            if not key:
                key = provider.get("apiKey")
                if isinstance(key, str):
                    ref = re.fullmatch(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)", key)
                    if ref:
                        key = os.environ.get(ref[1] or ref[2])
                    elif key.startswith(("!", "$")):
                        key = None
                    elif key.isidentifier():
                        key = os.environ.get(key, key)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("Cannot read the selected provider from --pi-models") from None
    if not isinstance(base, str) or not base.strip():
        raise ValueError("Set DISTINCTIVENESS_BASE_URL or the Pi provider's baseUrl")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Set DISTINCTIVENESS_MODEL or select a Pi provider with exactly one model")
    if not isinstance(key, str) or not key or not re.fullmatch(r"[!-~]+", key):
        raise ValueError("Set DISTINCTIVENESS_API_KEY or a valid Pi provider apiKey")
    try:
        parts = urlsplit(base)
        valid = (parts.scheme in {"http", "https"} and parts.hostname and not parts.username
                 and parts.password is None and not parts.query and not parts.fragment and parts.port != 0
                 and not any(c.isspace() for c in base))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("DISTINCTIVENESS_BASE_URL (or Pi baseUrl) must be an HTTP(S) URL without credentials, query, or fragment")
    url = base.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return url, model, key


def parse_ranking(data, visible, backups):
    content = data["choices"][0]["message"]["content"].strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.S | re.I)
    value = json.loads(fence[1] if fence else content)
    best = value["best"]
    picks = value["backups" if backups else "top3"]
    if not isinstance(picks, list) or not all(isinstance(pick, str) for pick in picks):
        raise ValueError
    top = [best, *picks] if backups else picks
    if (not isinstance(best, str) or len(top) != 3 or top[0] != best or len(set(top)) != 3
            or not set(top) <= visible | {"none"} or (backups and not set(picks) <= visible)):
        raise ValueError
    return top


def choose(request, listing, visible, config, effort, max_tokens):
    url, model, key = config
    prompts = (
        'Select the single best skill for the user request using only the catalog below, or none if no listed skill fits. '
        'Do not execute the request. Return JSON only: {"best":"name","top3":["name1","name2","name3"]}. '
        'Rank exactly three distinct choices, using exact catalog names or none; best must be first. '
        'Include weaker alternatives as needed to fill the ranking.',
        'Classify the request without executing it. First give your decision: the best listed skill, '
        'or none if the user needs no skill. Separately give exactly two different catalog skill names '
        'as forced-choice backup options, strongest first, neither equal to your decision. '
        'Even when the decision is none, both backups MUST be real catalog skill names: '
        'they are hypothetical alternatives, not recommendations. '
        'Return one JSON object: {"best":"your decision","backups":["first skill name","second skill name"]}.',
    )
    opener = build_opener(NoRedirect())
    for backup, prompt in enumerate(prompts):
        payload = dict(model=model, temperature=0, max_tokens=max_tokens, messages=[
            dict(role="system", content=prompt + "\n\nCatalog:\n" + listing),
            dict(role="user", content=request),
        ])
        if effort:
            payload["reasoning_effort"] = effort
        try:
            req = Request(url, json.dumps(payload).encode("utf-8"),
                          {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with opener.open(req, timeout=100) as response:
                top = parse_ranking(json.load(response), visible, backup)
            return dict(top3=top, recovered=bool(backup))
        except HTTPError as error:
            error.close()
            return dict(error="http", status=error.code)
        except OSError:
            return dict(error="transport")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass
    return dict(error="invalid_ranking")


def evaluate_llm(skills, queries, args, config):
    visible = {name for name, skill in skills.items() if not skill["hidden"]}
    if len(visible) < 2:
        raise ValueError("--llm needs at least two model-visible skills for a top-3 ranking with none")
    if args.orders > math.factorial(len(visible)):
        raise ValueError("--orders exceeds the number of distinct listings")
    eligible = {qid: q for qid, q in queries.items() if q["expected"] in visible | {"none"}}
    if not eligible:
        raise ValueError("--llm has no eligible requests")
    results = []
    seen_orders = set()
    seed = SEED
    with ThreadPoolExecutor(max_workers=8) as pool:
        while len(results) < args.orders:
            order = sorted(visible)
            random.Random(seed).shuffle(order)
            if tuple(order) in seen_orders:
                seed += 1
                continue
            seen_orders.add(tuple(order))
            listing = "\n".join(f"{name}: {skills[name]['description']}" for name in order)

            def classify(query):
                return choose(query["request"], listing, visible, config, args.reasoning_effort, args.max_tokens)

            first, *rest = eligible
            preflight = classify(eligible[first])
            if preflight.get("status") in {400, 401, 403, 404}:
                raise ValueError(f"LLM preflight failed: HTTP {preflight['status']}")
            predictions = {first: preflight} | dict(zip(rest, pool.map(classify, (eligible[qid] for qid in rest))))
            ranked = {qid: row["top3"] for qid, row in predictions.items() if "top3" in row}
            actual_none = sum(q["expected"] == "none" for q in eligible.values())
            predicted_none = [qid for qid, top in ranked.items() if top[0] == "none"]
            true_none = sum(eligible[qid]["expected"] == "none" for qid in predicted_none)
            results.append(dict(
                seed=seed, order=order, predictions=predictions, n=len(eligible), valid=len(ranked),
                top1=sum(top[0] == eligible[qid]["expected"] for qid, top in ranked.items()) / len(eligible),
                top3=sum(eligible[qid]["expected"] in top for qid, top in ranked.items()) / len(eligible),
                none_precision=ratio(true_none, len(predicted_none)), none_recall=ratio(true_none, actual_none),
            ))
            seed += 1
    average = {k: mean(run[k] for run in results) if all(run[k] is not None for run in results) else None
               for k in ("top1", "top3", "none_precision", "none_recall")}
    return dict(orders=results, average=average)


def markdown(data):
    def fmt(value, spec):
        return "n/a" if value is None else format(value, spec)

    def llm_rates(run):
        return " | ".join(fmt(run[k], ".2%") for k in ("top1", "top3", "none_precision", "none_recall"))

    skills = data["skills"]
    counts = Counter(q["target_status"] for q in data["queries"].values())
    lines = [
        "# Skill description distinctiveness", "",
        f"{len(skills)} skills ({sum(not s['hidden'] for s in skills.values())} visible); "
        f"{sum(counts.values())} requests ({', '.join(f'{k}: {v}' for k, v in sorted(counts.items()))}).",
        "", "## BM25", "",
        "| Language | N | Top-1 | MRR | Mean margin | Positive top-1 | Positive MRR | All zero | Top tied |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lang, row in data["bm25"].items():
        lines.append(
            f"| {lang} | {row['n']} | {row['top1']:.2%} | {row['mrr']:.4f} | {fmt(row['mean_margin'], '+.4f')} | "
            f"{row['positive_top1']:.2%} | {row['positive_mrr']:.4f} | {row['all_zero']} | {row['top_tied']} |"
        )
    if data["llm"]:
        lines.extend(["", "## LLM selection", "",
                      "| Listing seed | Valid / N | Top-1 | Top-3 | None precision | None recall |",
                      "|---:|---:|---:|---:|---:|---:|"])
        for run in data["llm"]["orders"]:
            lines.append(f"| {run['seed']} | {run['valid']}/{run['n']} | {llm_rates(run)} |")
        lines.append(f"| Mean | | {llm_rates(data['llm']['average'])} |")
    lines.extend(["", "## TF-IDF nearest neighbors", ""])
    for label, scope in data["nearest_neighbor_summary"].items():
        lines.append(f"- {label} mean / max: {fmt(scope['mean'], '.4f')} / {fmt(scope['max'], '.4f')}")
    lines.extend(["", "| Skill | Nearest skill | Cosine |", "|---|---|---:|"])
    for name, neighbor in data["nearest_neighbors"].items():
        lines.append(f"| {name} | {neighbor['skill']} | {neighbor['cosine']:.4f} |" if neighbor
                     else f"| {name} | n/a | n/a |")
    return "\n".join([*lines, ""])


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=None)
    parser.add_argument("--queries", type=Path, default=CORPUS / "holdout.jsonl")
    parser.add_argument("--descriptions", type=Path, help="JSON object mapping skill names to draft descriptions")
    parser.add_argument("--output", type=Path, required=True, help="output path prefix; writes .md and .json")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--orders", type=positive_int, default=2, help="LLM listing shuffle count (default: 2)")
    parser.add_argument("--reasoning-effort", help="optional provider-specific reasoning_effort")
    parser.add_argument("--max-tokens", type=positive_int, default=8192, help="LLM response token limit")
    parser.add_argument("--pi-models", type=Path, help="explicit path to a Pi models.json")
    parser.add_argument("--pi-provider", help="provider name in --pi-models")
    args = parser.parse_args(argv)
    if bool(args.pi_models) != bool(args.pi_provider):
        parser.error("--pi-models and --pi-provider must be supplied together")
    try:
        skills = load_catalog(args.skills_dir or HERE.parent / "skills", args.descriptions,
                              flat=args.skills_dir is not None)
        queries = load_queries(args.queries)
        for q in queries.values():
            name = q["expected"]
            q["target_status"] = ("none" if name == "none" else "outside_catalog" if name not in skills
                                  else "hidden" if skills[name]["hidden"] else "visible")
        bm25, rows, neighbors = lexical(skills, queries)
        summary = {}
        for label, include_hidden in (("visible", False), ("all", True)):
            scores = [row["cosine"] for name, row in neighbors.items()
                      if row is not None and (include_hidden or not skills[name]["hidden"])]
            summary[label] = dict(mean=mean(scores) if scores else None, max=max(scores, default=None))
        llm = evaluate_llm(skills, queries, args, llm_config(args)) if args.llm else None
        data = dict(skills=skills, queries=queries, bm25=bm25, bm25_queries=rows, nearest_neighbors=neighbors,
                    nearest_neighbor_summary=summary, llm=llm)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for suffix, content in ((".md", markdown(data)), (".json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")):
            args.output.with_name(args.output.name + suffix).write_text(content, encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
