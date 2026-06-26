"""overall_state axis (FROZEN): concatenate the four readings -> situation + exertion + heart note.

classify(act, reg, pos, loco) -> reading dict. (Combiner, not a per-window classifier, so it takes
the four axis readings instead of a window.) Logic identical to the original live_hsi.py.
"""
from core.config import LOAD


def classify(act, reg, pos, loco):
    a = act.get("label"); p = pos.get("label"); l = loco.get("label")
    # regularity bucket for the "restless" cue
    if reg.get("reason") == "low_movement" or reg.get("score") is None:
        r = "calm"
    else:
        r = "rhythmic" if reg["score"] >= 0.5 else "erratic"

    if p == "lying":               situation = "resting (lying)"
    elif l == "on_foot":           situation = "running" if a == "running" else "walking"
    elif l == "in_vehicle":        situation = "in vehicle"
    elif a == "cycling":           situation = "cycling"
    elif r == "erratic":           situation = "restless"
    else:                          situation = "still"

    exertion = 0 if l == "in_vehicle" else LOAD.get(a, 0)
    if exertion >= 2:    note = "HR rise = physical exertion (expected)"
    elif r == "erratic": note = "still but restless -> HR rise may be stress"
    else:                note = "calm baseline"
    return {"situation": situation, "exertion": exertion, "note": note}
