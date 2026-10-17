"""Правила над временной шкалой ответов модели.

Шкала: список кадров {"t": сек, "a": {probe_id: "yes"|"no"|"unclear"}}. Вопрос, который
на кадре не задавали, в "a" отсутствует и ни одному условию не удовлетворяет.

Виды правил (rules.json, поле kind):
  state          — условие `all` держится не меньше `min_sec` подряд; событие в начале серии.
  missing_before — в «сессии» (серия кадров с условием `session`) случилось `trigger`,
                   а до него (и в момент него) ни разу не было `missing`; событие в момент trigger.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SESSION_GAP_SEC = 3.0   # разрыв, после которого сессия посетителя считается новой
MISSING_GRACE_SEC = 1.0  # документ, показанный сразу после передачи, ещё засчитывается


@dataclass
class Event:
    rule: dict
    t: float
    evidence_times: list[float] = field(default_factory=list)


def matches(answers: dict, cond: dict) -> bool:
    return all(answers.get(k) == v for k, v in cond.items())


def _step(frames: list[dict]) -> float:
    if len(frames) < 2:
        return 1.0
    return (frames[-1]["t"] - frames[0]["t"]) / (len(frames) - 1)


def _runs(frames: list[dict], cond: dict) -> list[list[dict]]:
    runs, cur = [], []
    for fr in frames:
        if matches(fr["a"], cond):
            cur.append(fr)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _merge(runs: list[list[dict]], gap: float) -> list[list[dict]]:
    out: list[list[dict]] = []
    for r in runs:
        if out and r[0]["t"] - out[-1][-1]["t"] <= gap:
            out[-1] = out[-1] + r
        else:
            out.append(r)
    return out


def eval_state(frames: list[dict], rule: dict, merge_gap: float) -> list[Event]:
    step = _step(frames)
    events = []
    for run in _merge(_runs(frames, rule["all"]), merge_gap):
        span = run[-1]["t"] - run[0]["t"] + step
        if span + 1e-6 < float(rule.get("min_sec", 0)):
            continue
        times = sorted({round(run[0]["t"], 2), round(run[len(run) // 2]["t"], 2), round(run[-1]["t"], 2)})
        events.append(Event(rule, run[0]["t"], times))
    return events


def eval_missing_before(frames: list[dict], rule: dict) -> list[Event]:
    sessions = _merge(_runs(frames, rule["session"]), SESSION_GAP_SEC)
    events = []
    for sess in sessions:
        trig = next((fr for fr in sess if matches(fr["a"], rule["trigger"])), None)
        if trig is None:
            continue
        start = sess[0]["t"]
        seen = any(matches(fr["a"], rule["missing"]) for fr in frames
                   if start <= fr["t"] <= trig["t"] + MISSING_GRACE_SEC)
        if not seen:
            idx = sess.index(trig)
            times = [round(fr["t"], 2) for fr in sess[max(0, idx - 1): idx + 2]]
            events.append(Event(rule, trig["t"], times))
    return events


def evaluate(frames: list[dict], rules: list[dict], merge_gap: float = 3.0,
             max_per_rule: int = 3) -> list[Event]:
    events: list[Event] = []
    for rule in rules:
        kind = rule.get("kind", "state")
        if kind == "state":
            found = eval_state(frames, rule, merge_gap)
        elif kind == "missing_before":
            found = eval_missing_before(frames, rule)
        else:
            raise ValueError(f"Неизвестный вид правила {kind!r} в {rule.get('id')}")
        events.extend(found[:max_per_rule])
    return dedupe_by_type(events, merge_gap)


def dedupe_by_type(events: list[Event], gap: float) -> list[Event]:
    """Два правила одного типа (например, два варианта «сейф открыт») не дают двойного события."""
    out: list[Event] = []
    for ev in sorted(events, key=lambda e: e.t):
        if any(o.rule["type"] == ev.rule["type"] and abs(o.t - ev.t) <= gap for o in out):
            continue
        out.append(ev)
    return out
