"""Differential test against croner (JavaScript).

Generates random patterns, options and reference times (around DST transitions), and
compares next_runs, previous_runs and match with croner (JS), run from source with Node.js.

    python tools/compare_with_js.py [seed] [count]

Needs Node.js >= 22.6 and a checkout of https://github.com/Hexagon/croner, by default next
to this repository, or set CRONER_JS to the path of its src/croner.ts.

croner (JS) <= 10.x skips a match after February 29 for some day-of-month patterns, where it
overflows into March. Those differences are reported separately, after checking that the
Python answer is the earlier, valid one.
"""
import json, os, random, subprocess, sys
from datetime import datetime, timedelta, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from croner import Cron, CronError
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
TZS = ["Europe/Stockholm", "America/New_York", "Australia/Lord_Howe", "Pacific/Chatham", "Asia/Tokyo", "UTC", "America/Sao_Paulo", "Europe/London", None]
TRANSITIONS = ["2024-03-31T01:00:00Z", "2024-10-27T01:00:00Z", "2025-03-09T07:00:00Z", "2025-11-02T06:00:00Z", "2024-04-06T15:00:00Z", "2024-04-06T14:00:00Z", "2024-02-29T12:00:00Z", "2023-12-31T23:59:59Z"]
def field(lo, hi, extra=()):
    r = random.random()
    if r < 0.3: return "*"
    if r < 0.45: return f"*/{random.randint(1, max(1,(hi-lo)//2))}"
    if r < 0.6:
        a = random.randint(lo, hi); b = random.randint(a, hi); return f"{a}-{b}"
    if r < 0.7:
        a = random.randint(lo, hi); b = random.randint(a, hi); return f"{a}-{b}/{random.randint(1,5)}"
    if r < 0.85: return ",".join(str(random.randint(lo, hi)) for _ in range(random.randint(1,3)))
    if extra and r < 0.97: return random.choice(extra)
    return str(random.randint(lo, hi))
def pattern():
    sec = field(0, 59) if random.random() < 0.5 else None
    parts = [field(0,59), field(0,23), field(1,31,("L","15W","1W","LW","L","31W")), field(1,12,("JAN","FEB-MAR","DEC")), field(0,7,("MON-FRI","5#L","FRI#2","1#1","SUN","5L","+MON","+1-5","FRI-SUN","6#5"))]
    if sec is not None: parts.insert(0, sec)
    if sec is not None and random.random() < 0.15: parts.append(random.choice(["2025","2024-2030","*/4","2026,2031"]))
    return " ".join(parts)
cases = []
for _ in range(N):
    tz = random.choice(TZS)
    base = datetime.fromisoformat(random.choice(TRANSITIONS).replace("Z","+00:00"))
    ref = base + timedelta(seconds=random.randint(-7200, 7200), milliseconds=random.choice([0,0,500]))
    opts = {}
    if tz: opts["timezone"] = tz
    if random.random() < 0.1: opts["domAndDow"] = True
    if random.random() < 0.05: opts["interval"] = random.randint(2, 100)
    if random.random() < 0.1: opts["dayOffset"] = random.randint(-2, 2)
    cases.append({"pattern": pattern(), "options": opts, "ref": ref.isoformat().replace("+00:00","Z"), "n": 5})
js = json.loads(subprocess.run(["node", "--experimental-strip-types", "--no-warnings", os.path.join(HERE, "compare_js.mts")], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond//1000:03d}Z"
bad = 0
FEB29 = [0]
for c, j in zip(cases, js):
    o = c["options"]
    kw = {}
    if "timezone" in o: kw["timezone"] = o["timezone"]
    if "domAndDow" in o: kw["dom_and_dow"] = True
    if "interval" in o: kw["interval"] = o["interval"]
    if "dayOffset" in o: kw["day_offset"] = o["dayOffset"]
    try:
        job = Cron(c["pattern"], **kw)
        p = {"next": [iso(d) for d in job.next_runs(c["n"], c["ref"])], "prev": [iso(d) for d in job.previous_runs(c["n"], c["ref"])], "match": job.match(c["ref"])}
    except CronError:
        p = {"error": True}
    if p != j:
        ok = "error" not in p and "error" not in j and p["prev"] == j["prev"] and p["match"] == j["match"] and len(p["next"]) and len(j["next"]) and p["next"][0] < j["next"][0] and job.match(p["next"][0]) and c["ref"].startswith("2024-02-29")
        if ok:
            FEB29[0] += 1
            continue
        bad += 1
        if bad <= 8: print("MISMATCH", c, "\n  js:", j, "\n  py:", p)
print(f"{len(cases) - bad}/{len(cases)} agree, {FEB29[0]} of them differ only by the croner (JS) February 29 overflow")
