"""Check the actual exported files against one frozen disclosed cutting job."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon

EPS = 1e-6  # SVG units, declared before either producer's first output.


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rotated(vertices, angle):
    angle = angle % 360
    if angle == 0:
        out = vertices
    elif angle == 90:
        out = [[-y, x] for x, y in vertices]
    elif angle == 180:
        out = [[-x, -y] for x, y in vertices]
    elif angle == 270:
        out = [[y, -x] for x, y in vertices]
    else:
        raise ValueError("Unsupported angle in this frozen job")
    xmin = min(x for x, y in out)
    ymin = min(y for x, y in out)
    return [[x - xmin, y - ymin] for x, y in out]


def verify(job_path, output_dir):
    job = json.loads(job_path.read_text())
    placement_path = output_dir / "placements.json"
    svg_path = output_dir / "layout.svg"
    export = json.loads(placement_path.read_text())
    failures = []
    if export.get("caseId") != job["caseId"]:
        failures.append("Case ID mismatch")
    if export.get("inputSha256") != sha(job_path):
        failures.append("Original frozen input digest mismatch")
    stock = {s["id"]: s for s in job["stock"]}
    parts = {p["id"]: p for p in job["parts"]}
    sheet_list = export["sheets"]
    sheets = {s["sheetId"]: s for s in sheet_list}
    if len(sheets) != len(sheet_list):
        failures.append("Duplicate sheet IDs")
    stock_counts = Counter(s["stockId"] for s in sheet_list)
    stock_instances = set()
    for sheet in sheet_list:
        original = stock.get(sheet["stockId"])
        if original is None:
            failures.append("Unknown stock ID")
            continue
        key = (sheet["stockId"], sheet["stockInstance"])
        if key in stock_instances:
            failures.append("Duplicate physical stock instance")
        stock_instances.add(key)
        if abs(sheet["width"] - original["width"]) > EPS or abs(sheet["height"] - original["height"]) > EPS:
            failures.append("Changed stock dimensions")
    for sid, count in stock_counts.items():
        if sid not in stock or count > stock[sid]["quantity"]:
            failures.append("Stock availability exceeded")
    expected = Counter((p["id"], c) for p in job["parts"] for c in range(p["quantity"]))
    actual = Counter((p["partId"], p["copyIndex"]) for p in export["placements"])
    if actual != expected:
        failures.append("Missing, duplicate or unexpected source-piece copies")
    polygons = {}
    by_sheet = defaultdict(list)
    for p in export["placements"]:
        key = (p["partId"], p["copyIndex"])
        part = parts.get(p["partId"])
        sheet = sheets.get(p["sheetId"])
        if part is None or sheet is None:
            failures.append("Placement references unknown source or sheet")
            continue
        if p["rotation"] not in part["allowedRotations"]:
            failures.append("Disallowed source rotation")
            continue
        if not all(math.isfinite(p[k]) for k in ["x", "y", "rotation"]):
            failures.append("Non-finite placement coordinate")
            continue
        vertices = rotated(part["vertices"], p["rotation"])
        poly = Polygon([[x + p["x"], y + p["y"]] for x, y in vertices])
        if not poly.is_valid or poly.is_empty:
            failures.append("Invalid original/placed polygon")
        xmin, ymin, xmax, ymax = poly.bounds
        margin = job["margin"]
        if xmin < margin - EPS or ymin < margin - EPS or xmax > sheet["width"] - margin + EPS or ymax > sheet["height"] - margin + EPS:
            failures.append("Part violates original sheet boundary/margin")
        polygons[key] = (p["sheetId"], poly)
        by_sheet[p["sheetId"]].append((key, poly))
    minimum_gap = math.inf
    for sheet_id, placed in by_sheet.items():
        for i, (key, poly) in enumerate(placed):
            for other_key, other in placed[:i]:
                distance = poly.distance(other)
                minimum_gap = min(minimum_gap, distance)
                if distance < job["spacing"] - EPS:
                    failures.append("Source polygons overlap or violate required gap")
    tree = ET.fromstring(svg_path.read_bytes())
    svg_seen = Counter()
    for group in tree:
        if group.tag.rsplit("}", 1)[-1] != "g":
            continue
        sheet_id = group.get("data-sheet-id")
        if sheet_id not in sheets:
            failures.append("SVG contains unknown sheet group")
            continue
        transform = group.get("transform", "")
        if transform and not re.fullmatch(r"translate\([^()]+\)", transform):
            failures.append("SVG display group deforms sheet coordinates")
        for el in group.iter():
            if el.tag.rsplit("}", 1)[-1] != "polygon":
                continue
            part_id = el.get("data-part-id")
            if part_id is None:
                failures.append("SVG contains unidentified cutting polygon")
                continue
            key = (part_id, int(el.get("data-copy-index", "-1")))
            svg_seen[key] += 1
            original = polygons.get(key)
            if original is None or original[0] != sheet_id:
                failures.append("SVG piece or sheet disagrees with placement record")
                continue
            if el.get("transform") or "transform" in el.get("style", ""):
                failures.append("SVG applies unrecorded transform to a cutting piece")
            numbers = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", el.get("points", ""))]
            if len(numbers) % 2 or len(numbers) < 6 or not all(math.isfinite(n) for n in numbers):
                failures.append("Invalid SVG polygon coordinate sequence")
                continue
            poly = Polygon(list(zip(numbers[::2], numbers[1::2])))
            expected_poly = original[1]
            if not poly.is_valid or poly.hausdorff_distance(expected_poly) > EPS or abs(poly.area - expected_poly.area) > EPS * max(expected_poly.length, 1):
                failures.append("Actual SVG changes source shape, scale or placement")
    if svg_seen != expected:
        failures.append("Actual SVG omits/duplicates original source-piece copies")
    used = set(by_sheet)
    purchased_area = sum(stock[sheets[s]["stockId"]]["width"] * stock[sheets[s]["stockId"]]["height"] for s in used if stock[sheets[s]["stockId"]]["kind"] == "purchase")
    total_area = sum(sheets[s]["width"] * sheets[s]["height"] for s in used)
    return {
        "caseId": job["caseId"], "valid": not failures,
        "failures": sorted(set(failures)), "toleranceSVGUnits": EPS,
        "inputSha256": sha(job_path), "placementsSha256": sha(placement_path), "svgSha256": sha(svg_path),
        "requiredPieceCopies": sum(expected.values()), "actualPlacementCopies": sum(actual.values()),
        "actualSVGCopies": sum(svg_seen.values()), "usedSheets": len(used),
        "purchasedArea": purchased_area, "totalUsedSheetArea": total_area,
        "minimumPairGap": minimum_gap if math.isfinite(minimum_gap) else None,
        "optimality": "NOT_PROVED", "physicalCutOrHumanBenefit": "NOT_TESTED",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.job, args.output_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
