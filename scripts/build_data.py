"""
build_data.py  –  SPL Dashboard static data builder
Reads all Excel files from data/, computes KPIs + adherence,
and writes docs/data.json for the static HTML dashboard.
Run locally or via GitHub Actions.
"""

import sys, json, math
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from data_parser import load_all_data, compute_monthly_kpis, compute_adherence

OUT_DIR = ROOT / "docs"
OUT_DIR.mkdir(exist_ok=True)

def clean(val):
    """Make a value JSON-safe."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return None if math.isnan(float(val)) else round(float(val), 4)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return str(val)
    return val

def df_to_records(df):
    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]

def fmt_period(p):
    try:
        return pd.Period(p, freq="M").strftime("%B %Y").capitalize()
    except Exception:
        return p

# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading data...")
raw  = load_all_data()
kpis = compute_monthly_kpis(raw)
adh  = compute_adherence(kpis)

# Filter to CP/FO only
adh  = adh[adh["rank"].isin(["CP","FO"])].copy()
kpis = kpis[kpis["rank"].isin(["CP","FO"])].copy()

periods_exe = sorted(
    kpis[kpis["rol_type"] == "Ejecutado"]["periodo"].dropna().unique(), reverse=True
)

# ── Overview per rank+period ──────────────────────────────────────────────────
overview = {}
for rank in ("CP", "FO"):
    overview[rank] = {}
    for period in periods_exe:
        exe = kpis[(kpis["rol_type"]=="Ejecutado") & (kpis["periodo"]==period) & (kpis["rank"]==rank)]
        adh_p = adh[(adh["rank"]==rank) & (adh["periodo"]==period)]
        exe_active = exe[~exe["prolonged_absence"]]
        adh_valid  = adh_p[
            ~(adh_p["exe_prolonged"].fillna(False) | adh_p["pub_prolonged"].fillna(False)) &
            adh_p["adherence_total"].notna()
        ]

        def safe(v):
            return round(float(v), 3) if (v is not None and not (isinstance(v, float) and math.isnan(v))) else None

        # Histogram bins for flight hours
        hrs = exe_active["flight_block_hours"].dropna().tolist()
        if hrs:
            import numpy as _np
            counts, edges = _np.histogram(hrs, bins=30)
            hist_hrs = {"counts": counts.tolist(), "edges": [round(e,2) for e in edges.tolist()]}
        else:
            hist_hrs = {"counts": [], "edges": []}

        # Histogram bins for adherence
        adh_vals = adh_valid["adherence_total"].clip(0,1.5).dropna().tolist()
        if adh_vals:
            counts2, edges2 = _np.histogram(adh_vals, bins=30)
            hist_adh = {"counts": counts2.tolist(), "edges": [round(e,4) for e in edges2.tolist()]}
        else:
            hist_adh = {"counts": [], "edges": []}

        # Activity pie
        acts = {
            "Vuelos":       int(exe_active["flight_sectors"].sum()),
            "Días Libre":   int(exe_active["day_off"].sum()),
            "Vacaciones":   int(exe_active["vac_days"].sum()),
            "L. Médica":    int(exe_active["sick_days"].sum()),
            "Simulador":    int(exe_active["sim_days"].sum()),
            "Turno Apto.":  int(exe_active["asb_days"].sum()),
            "Turno Dom.":   int(exe_active["hsb_days"].sum()),
            "Entrenamiento":int(exe_active["ground_days"].sum()),
            "OOF":          int(exe_active["oof_days"].sum()),
        }

        # Top 20
        top20 = exe_active.nlargest(20,"flight_block_hours")[
            ["full_name","flight_block_hours","flight_sectors"]
        ].copy()
        top20["short"] = top20["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")

        # Scatter adherence vs hours
        scat = adh_valid[adh_valid["exe_flight_hours"].notna()].copy()
        scat["short"] = scat["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")

        overview[rank][period] = {
            "n_total":       int(exe["staff_num"].nunique()),
            "n_active":      int(exe_active["staff_num"].nunique()),
            "avg_flight_hrs": safe(exe_active["flight_block_hours"].mean()),
            "avg_sectors":   safe(exe_active["flight_sectors"].mean()),
            "avg_adh":       safe(adh_valid["adherence_total"].mean()),
            "avg_pub_hrs":   safe(adh_valid["pub_flight_hours"].mean()),
            "hist_hrs":      hist_hrs,
            "hist_adh":      hist_adh,
            "activities":    acts,
            "top20": {
                "names":  top20["short"].tolist(),
                "hours":  [round(h,2) for h in top20["flight_block_hours"].tolist()],
                "sectors":top20["flight_sectors"].tolist(),
            },
            "scatter": {
                "exe_hrs":   [safe(v) for v in scat["exe_flight_hours"].tolist()],
                "adherence": [safe(v) for v in scat["adherence_total"].clip(0,1.5).tolist()],
                "names":     scat["short"].tolist(),
            },
        }

# ── Trends per rank ───────────────────────────────────────────────────────────
trends = {}
for rank in ("CP","FO"):
    trend_hrs = kpis[
        (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) & (~kpis["prolonged_absence"])
    ].groupby("periodo").agg(
        avg_flight=("flight_block_hours","mean"),
        n_pilots=("staff_num","nunique"),
    ).reset_index().sort_values("periodo")

    trend_adh = adh[
        (adh["rank"]==rank) &
        (~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))) &
        adh["adherence_total"].notna()
    ].groupby("periodo").agg(
        avg_adh=("adherence_total","mean"),
        med_adh=("adherence_total","median"),
    ).reset_index().sort_values("periodo")

    trends[rank] = {
        "periods":    trend_hrs["periodo"].tolist(),
        "avg_flight": [round(float(v),2) for v in trend_hrs["avg_flight"].fillna(0).tolist()],
        "n_pilots":   trend_hrs["n_pilots"].tolist(),
        "adh_periods":trend_adh["periodo"].tolist(),
        "avg_adh":    [round(float(v),4) for v in trend_adh["avg_adh"].fillna(0).tolist()],
        "med_adh":    [round(float(v),4) for v in trend_adh["med_adh"].fillna(0).tolist()],
    }

# ── Pilot list per rank ───────────────────────────────────────────────────────
pilots = {}
for rank in ("CP","FO"):
    sub = adh[adh["rank"]==rank].dropna(subset=["full_name"])
    names = sub.drop_duplicates("staff_num")[["staff_num","full_name"]].sort_values("full_name")
    pilots[rank] = [
        {"id": str(r["staff_num"]), "name": str(r["full_name"]).strip().title()}
        for _, r in names.iterrows()
    ]

# ── Per-pilot data ────────────────────────────────────────────────────────────
pilot_data = {}

# peer stats per rank+period (for comparison)
peer_stats = {}
for rank in ("CP","FO"):
    peer_stats[rank] = {}
    for period in periods_exe:
        peers_exe = kpis[
            (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) &
            (kpis["periodo"]==period) & (~kpis["prolonged_absence"])
        ]
        peers_adh = adh[
            (adh["rank"]==rank) & (adh["periodo"]==period) &
            (~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))) &
            adh["adherence_total"].notna()
        ]
        peer_stats[rank][period] = {
            "avg_hrs":      round(float(peers_exe["flight_block_hours"].mean()),2) if len(peers_exe) else 0,
            "avg_sectors":  round(float(peers_exe["flight_sectors"].mean()),2) if len(peers_exe) else 0,
            "avg_days_fly": round(float(peers_exe["days_with_flights"].mean()),2) if len(peers_exe) else 0,
            "avg_adh":      round(float(peers_adh["adherence_total"].mean()),4) if len(peers_adh) else 0,
            "avg_day_off":  round(float(peers_exe["day_off"].mean()),2) if len(peers_exe) else 0,
            "avg_vac":      round(float(peers_exe["vac_days"].mean()),2) if len(peers_exe) else 0,
            "avg_sick":     round(float(peers_exe["sick_days"].mean()),2) if len(peers_exe) else 0,
            "avg_sim":      round(float(peers_exe["sim_days"].mean()),2) if len(peers_exe) else 0,
            "avg_asb":      round(float(peers_exe["asb_days"].mean()),2) if len(peers_exe) else 0,
            "avg_hsb":      round(float(peers_exe["hsb_days"].mean()),2) if len(peers_exe) else 0,
            "avg_ground":   round(float(peers_exe["ground_days"].mean()),2) if len(peers_exe) else 0,
            "avg_oof":      round(float(peers_exe["oof_days"].mean()),2) if len(peers_exe) else 0,
            # distribution for box/percentile
            "adh_dist":     [round(float(v),4) for v in peers_adh["adherence_total"].clip(0,1.5).dropna().tolist()],
            "hrs_dist":     [round(float(v),2) for v in peers_exe["flight_block_hours"].dropna().tolist()],
        }

print(f"Computing per-pilot data for {sum(len(v) for v in pilots.values())} pilots...")
for rank in ("CP","FO"):
    for p in pilots[rank]:
        pid = p["id"]
        pilot_adh = adh[adh["staff_num"]==pid].sort_values("periodo")
        pilot_kpi = kpis[(kpis["staff_num"]==pid) & (kpis["rol_type"]=="Ejecutado")].sort_values("periodo")

        history = {}
        for _, row in pilot_adh.iterrows():
            per = row["periodo"]
            exe_row = pilot_kpi[pilot_kpi["periodo"]==per]
            history[per] = {
                "exe_hrs":    clean(row.get("exe_flight_hours")),
                "pub_hrs":    clean(row.get("pub_flight_hours")),
                "adherence":  clean(row.get("adherence_total")),
                "sectors":    int(exe_row["flight_sectors"].sum()) if len(exe_row) else 0,
                "days_fly":   int(exe_row["days_with_flights"].sum()) if len(exe_row) else 0,
                "day_off":    int(exe_row["day_off"].sum()) if len(exe_row) else 0,
                "sick":       int(exe_row["sick_days"].sum()) if len(exe_row) else 0,
                "vac":        int(exe_row["vac_days"].sum()) if len(exe_row) else 0,
                "sim":        int(exe_row["sim_days"].sum()) if len(exe_row) else 0,
                "asb":        int(exe_row["asb_days"].sum()) if len(exe_row) else 0,
                "hsb":        int(exe_row["hsb_days"].sum()) if len(exe_row) else 0,
                "ground":     int(exe_row["ground_days"].sum()) if len(exe_row) else 0,
                "oof":        int(exe_row["oof_days"].sum()) if len(exe_row) else 0,
            }

        pilot_data[pid] = {
            "name":    p["name"],
            "rank":    rank,
            "history": history,
        }

# ── Trend per rank for pilot comparison ──────────────────────────────────────
peer_trends = {}
for rank in ("CP","FO"):
    pt = adh[
        (adh["rank"]==rank) &
        (~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False)))
    ].groupby("periodo").agg(
        avg_exe_hrs=("exe_flight_hours","mean"),
        avg_adh=("adherence_total","mean"),
    ).reset_index().sort_values("periodo")
    peer_trends[rank] = {
        "periods":  pt["periodo"].tolist(),
        "avg_hrs":  [round(float(v),2) for v in pt["avg_exe_hrs"].fillna(0).tolist()],
        "avg_adh":  [round(float(v),4) for v in pt["avg_adh"].fillna(0).tolist()],
    }

# ── Assemble final JSON ───────────────────────────────────────────────────────
payload = {
    "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M UTC"),
    "periods_exe":  periods_exe,
    "periods_fmt":  {p: fmt_period(p) for p in periods_exe},
    "overview":     overview,
    "trends":       trends,
    "peer_stats":   peer_stats,
    "peer_trends":  peer_trends,
    "pilots":       pilots,
    "pilot_data":   pilot_data,
}

out_path = OUT_DIR / "data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",",":"))

size_kb = out_path.stat().st_size / 1024
print(f"✓ Written {out_path}  ({size_kb:.0f} KB)")
print(f"  Periods: {periods_exe}")
print(f"  Pilots:  CP={len(pilots.get('CP',[]))}  FO={len(pilots.get('FO',[]))}")
