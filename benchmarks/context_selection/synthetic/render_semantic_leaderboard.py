"""Offline publication figure: vector SVG and 2x PNG from one drawing scene.

Run: python -m benchmarks.context_selection.synthetic.render_semantic_leaderboard
Pillow is the only rendering dependency. Arial font files are required; pass
--font-dir on systems without the macOS Arial installation. No provider imports.
"""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from .build_dashboard_summary import BASE, ROOT, OUTPUT, SCHEMA, build_summary

WIDTH, HEIGHT, SCALE = 1740, 940, 2
COLORS = {"omneum": "#1779B7", "bge": "#EF702B", "cohere": "#9655E8",
          "gemini": "#E3A51D", "astra": "#26AD89", "claude": "#EF702B"}
PAIRS = (("bge-omneum-tied-maxima-20261007", "bge", "bge_omneum"),
         ("20261008T014713Z", "cohere", "cohere_omneum"))
FONT_DIR = Path("/System/Library/Fonts/Supplemental")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verified_scope():
    """Count explicit fixture domains and matrix environments; verify all arms."""
    cases = [json.loads(p.read_text()) for p in sorted((BASE / 'cases').glob('*/case.json'))]
    ids = {c['id'] for c in cases}
    require(len(ids) == len(cases) == 24, 'Unexpected held-out case set')
    domains = {c['domain'] for c in cases}
    matrix = json.loads((BASE / 'case_matrix.json').read_text())['cases']
    require({c['case_id'] for c in matrix} == ids and len(matrix) == len(cases), 'Case matrix differs from fixtures')
    environments = {c['environment'] for c in matrix}
    for run, a, b in PAIRS:
        records = [json.loads(line) for line in (BASE / 'results' / run / 'results.jsonl').read_text().splitlines()]
        for method in (a, b):
            arm = [r for r in records if r['method'] == method]
            require(len(arm) == 24 and {r['case_id'] for r in arm} == ids,
                    f'{run}:{method} does not use the complete held-out case set')
            require({r['domain'] for r in arm} == domains, 'Recorded domains differ from fixtures')
    return {'cases': len(ids), 'domains': sorted(domains), 'environments': sorted(environments)}


def publication_rows(data):
    """Use corrected publication latencies and measured generator-only usage."""
    require(data["units"] == {"rates": "fraction", "latency": "seconds",
                             "api_tokens": "provider_tokens", "cost": "USD"}, "Unexpected metric units")
    configs = {c["id"]: c for c in data["configurations"]}
    tables = data["publication"]["tables"]["semantic_rerankers"]
    expected = [f"{run}:{method}" for run, a, b in PAIRS for method in (a, b)]
    require([r["configuration_id"] for r in tables] == expected, "Publication pairing changed; review figure")
    output = []
    for row in tables:
        c = configs[row["configuration_id"]]
        require(c["publication_status"] == "authoritative" and row["source_run"] == c["run_id"], "Nonpublication source")
        require(c["case_count"] == c["attempts"] == row["attempts"] == 24 and c["trials_per_case"] == 1, "Unexpected denominator")
        require(row["accuracy_basis"].startswith("recorded substring accuracy"), "Accuracy basis changed")
        if c["configuration_kind"] == "omneum_augmented":
            require(c["baseline_configuration_id"] == f"{c['run_id']}:{c['augmentation_target']}", "Unmatched baseline")
        g = c["api_tokens"]["generation"]
        values = {k: row[k] for k in ("accuracy", "precision", "recall", "selection_p50_seconds", "end_to_end_p50_seconds")}
        values.update(tokens=g["total"], cost=c["cost_usd"]["generation"])
        require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
                    for v in values.values()), "Required measurement missing or invalid")
        require(all(0 <= values[k] <= 1 for k in ("accuracy", "precision", "recall")), "Invalid percentage")
        require(g["input"] is not None and g["output"] is not None and g["total"] == g["input"] + g["output"], "Generator tokens do not reconcile")
        rates = data["pricing"]["usd_per_million"]
        require(math.isclose(values["cost"], (g["input"] * rates["sonnet_input"] + g["output"] * rates["sonnet_output"]) / 1e6), "Generator cost does not reconcile")
        scored = 23 if c["method_id"] == "bge_omneum" else 24
        require(row["selection_scored_attempts"] == scored, "Selection coverage changed")
        for k in ("precision", "recall"):
            require(row[k] == c["selection"]["macro"][k], "Not macro selection metrics")
        require(row["accuracy"] == c["recorded_answer_scores"]["accuracy"], "Not recorded substring accuracy")
        output.append({**values, "id": c["id"], "label": "Cohere Rerank" if c["method_id"] == "cohere" else c["label"],
                       "color": COLORS["omneum" if "omneum" in c["method_id"] else c["method_id"]]})
    return output


class Scene:
    """Shared primitives keep text, geometry and colors identical in both formats."""
    def __init__(self):
        self.items = []

    def rect(self, x, y, w, h, fill, radius=0):
        self.items.append(("rect", x, y, w, h, fill, radius))

    def text(self, x, y, value, size=26, fill="#18242B", bold=False, anchor="start"):
        self.items.append(("text", x, y, str(value), size, fill, bold, anchor))


def make_scene(rows):
    s = Scene()
    s.rect(0, 0, WIDTH, HEIGHT, "#FFFFFF")
    scope = verified_scope()
    s.rect(64, 30, 244, 42, '#F0F3F5', 8)
    s.text(82, 58, f"{scope['cases']} Held-out Cases", 22, '#53636D')
    s.text(323, 58, '·', 22, '#53636D')
    s.rect(344, 30, 148, 42, '#F0F3F5', 8)
    s.text(362, 58, f"{len(scope['domains'])} Domains", 22, '#53636D')
    s.text(1676, 58, "OMNEUM  /  BENCHMARKS", 22, COLORS["omneum"], True, 'end')
    s.text(64, 127, "Semantic Reranker Benchmarks", 52, bold=True)
    s.text(64, 175, "BGE and Cohere Rerank vs. Omneum-Augmented Selection", 28, "#53636D")
    s.text(64, 223, "24 held-out cases  ·  1 trial per method  ·  October 8, 2026", 22, "#53636D")
    s.text(1668, 223, "Precision bars: 0–100%", 22, "#53636D", anchor="end")
    s.rect(64, 247, 1612, 73, "#F4F7F9", 8)
    headers = [(88, "Configuration", "", "start"), (480, "Substring answer", "accuracy (%)", "end"),
               (815, "Selection precision", "macro (%)", "end"), (950, "Selection", "recall (%)", "end"),
               (1100, "Selection", "p50 (ms)", "end"), (1255, "End-to-end", "p50 (s)", "end"),
               (1450, "Total generator", "tokens", "end"), (1650, "Est. generator", "cost (USD)", "end")]
    for x, first, second, anchor in headers:
        s.text(x, 276, first, 21, "#53636D", True, anchor)
        s.text(x, 303, second, 21, "#53636D", anchor=anchor)
    for idx, (group, y) in enumerate((("BGE COMPARISON", 347), ("COHERE COMPARISON", 523))):
        s.text(88, y, group, 20, "#53636D", True)
        for j in range(2):
            r = rows[idx * 2 + j]
            baseline = y + 44 + j * 68
            s.rect(88, baseline - 19, 8, 23, r["color"], 3)
            s.text(112, baseline, r["label"], 27, bold=True)
            s.text(480, baseline, f"{r['accuracy'] * 100:.2f}%", 28, bold=True, anchor="end")
            s.rect(515, baseline - 16, 204, 13, "#EAF0F4", 6)
            s.rect(515, baseline - 16, 204 * r["precision"], 13, r["color"], 6)
            s.text(815, baseline, f"{r['precision'] * 100:.2f}%", 27, bold=True, anchor="end")
            for x, value in ((950, f"{r['recall'] * 100:.2f}%"), (1100, f"{r['selection_p50_seconds'] * 1000:.0f}"),
                             (1255, f"{r['end_to_end_p50_seconds']:.3f}"), (1450, f"{r['tokens']:,}"),
                             (1650, f"${r['cost']:.6f}")):
                s.text(x, baseline, value, 27, anchor="end")
            s.rect(88, baseline + 24, 1562, 1, "#E2E8ED")
    s.rect(64, 684, 1612, 192, "#F4F7F9", 8)
    notes = ["Recorded substring correctness / all attempts; not semantic adjudication. Precision and recall are macro averages.",
             "BGE + Omneum: 23 scored selections; BGE: 24. Both Cohere arms: 24. Missing scores are not imputed.",
             "Cohere latency restores the shared rerank duration using saved responses; values are reconstructed stage sums.",
             "Tokens and costs cover downstream Claude generation only. Costs use $2/M input + $10/M output; not invoices.",
             "Excludes local compute and Cohere reranking charges (billing unavailable). Synthetic cases; single-trial results."]
    for i, note in enumerate(notes):
        s.text(88, 718 + i * 32, note, 22, "#42545F")
    s.text(64, 909, "Sources: bge-omneum-tied-maxima-20261007  /  20261008T014713Z", 21, "#53636D")
    s.text(1676, 909, "Matched experiments · Original selector", 21, "#53636D", anchor="end")
    return s


def render(scene, font_dir=FONT_DIR):
    normal, bold = font_dir / "Arial.ttf", font_dir / "Arial Bold.ttf"
    require(normal.is_file() and bold.is_file(), "Arial fonts missing; supply --font-dir with Arial.ttf and Arial Bold.ttf")
    im = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "white")
    draw = ImageDraw.Draw(im)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
           '<title id="title">Semantic Reranker Benchmarks</title>',
           '<desc id="desc">Two matched comparisons. Omneum improves selection precision and recall, with lower substring accuracy and higher median latency. Generator-only tokens and estimated costs are shown.</desc>',
           '<metadata>' + html.escape(json.dumps({"font_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (normal, bold)}}, sort_keys=True)) + '</metadata>']
    for item in scene.items:
        kind, *a = item
        if kind == "rect":
            x, y, w, h, color, radius = a
            svg.append(f'<rect x="{x}" y="{y}" width="{w:.6f}" height="{h}" rx="{radius}" fill="{color}"/>')
            draw.rounded_rectangle((x*SCALE, y*SCALE, (x+w)*SCALE, (y+h)*SCALE), radius=radius*SCALE, fill=color)
        else:
            x, y, value, size, color, weight, anchor = a
            font = ImageFont.truetype(str(bold if weight else normal), size*SCALE)
            length = draw.textlength(value, font=font) / SCALE
            left = x - length if anchor == "end" else x
            require(0 <= left and left + length <= WIDTH and y - size >= 0 and y < HEIGHT, f"Text clipped: {value}")
            svg.append(f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if weight else 400}" text-anchor="{anchor}" fill="{color}">{html.escape(value)}</text>')
            draw.text((x*SCALE, y*SCALE), value, font=font, fill=color, anchor="rs" if anchor == "end" else "ls")
    svg.append('</svg>')
    result = "\n".join(svg) + "\n"
    ET.fromstring(result)
    return result, im


def generate(output_dir=None, font_dir=FONT_DIR):
    from jsonschema import Draft202012Validator
    data = json.loads(OUTPUT.read_text())
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(data)
    require(data == build_summary(), "Summary inconsistent with preserved sources; rebuild using existing generator")
    logo = (ROOT / "assets/omneum-logotype.svg").read_text()
    require(f'stop-color="{COLORS["omneum"]}"' in logo, "Official logo blue changed; review palette")
    rows = publication_rows(data)
    svg, im = render(make_scene(rows), font_dir)
    out = Path(output_dir) if output_dir is not None else ROOT / "assets/benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    (out / "semantic-rerankers.svg").write_text(svg)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("SVG SHA256", hashlib.sha256(svg.encode()).hexdigest())
    im.save(out / "semantic-rerankers.png", pnginfo=meta)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=FONT_DIR)
    args = parser.parse_args()
    for row in generate(font_dir=args.font_dir):
        print(json.dumps(row, sort_keys=True))
