"""
build_data.py – SPL Dashboard static data builder
Segments by rank (CP/FO) AND fleet_type (Wide Body / Narrow Body).
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

FLEET_TYPES = ["Wide Body (787)", "Narrow Body (32X)"]
RANKS       = ["CP", "FO"]

MESES_ES = {
    "January":"Enero","February":"Febrero","March":"Marzo","April":"Abril",
    "May":"Mayo","June":"Junio","July":"Julio","August":"Agosto",
    "September":"Septiembre","October":"Octubre","November":"Noviembre","December":"Diciembre"
}

def fmt_period(p):
    try:
        s = pd.Period(p, freq="M").strftime("%B %Y")
        for en, es in MESES_ES.items():
            s = s.replace(en, es)
        return s
    except Exception:
        return p

def clean(val):
    if val is None: return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return None
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return None if math.isnan(float(val)) else round(float(val), 2)
    if isinstance(val, (np.bool_,)): return bool(val)
    return val

def safe(v):
    if v is None: return None
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 2)
    except: return None

def sm(s):
    return round(float(s.mean()), 2) if len(s) > 0 and s.notna().any() else 0.0

# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading data...")
raw  = load_all_data()
kpis = compute_monthly_kpis(raw)
adh  = compute_adherence(kpis)

# Filter valid ranks; keep fleet_type (may be None for 1 pilot)
adh  = adh[adh["rank"].isin(RANKS)].copy()
kpis = kpis[kpis["rank"].isin(RANKS)].copy()

# Propagate fleet_type from kpis to adh (adh comes from merge, may lose it)
fleet_map = kpis.drop_duplicates("staff_num").set_index("staff_num")["fleet_type"].to_dict()
adh["fleet_type"] = adh["staff_num"].map(fleet_map)

# Diff hours: executed minus published
adh["diff_hrs"] = (adh["exe_flight_hours"].fillna(0) - adh["pub_flight_hours"].fillna(0)).round(2)
adh["more_is"] = np.where(
    adh["diff_hrs"] >  0.5, "Ejecutado",
    np.where(adh["diff_hrs"] < -0.5, "Publicado", "Igual")
)

periods_exe   = sorted(kpis[kpis["rol_type"]=="Ejecutado"]["periodo"].dropna().unique(), reverse=True)
all_periods_chron = sorted(periods_exe)
print(f"  periods_exe = {periods_exe}")

# ── Helper: build overview block for a filtered subset ───────────────────────
def build_overview_block(exe_sub, adh_sub, period, label):
    exe_active  = exe_sub[~exe_sub["prolonged_absence"]]
    diff_valid  = adh_sub[
        adh_sub["exe_flight_hours"].notna() & adh_sub["pub_flight_hours"].notna() &
        ~(adh_sub["exe_prolonged"].fillna(False) | adh_sub["pub_prolonged"].fillna(False))
    ].copy()

    # Histograms
    hrs = exe_active["flight_block_hours"].dropna().tolist()
    if hrs:
        counts, edges = np.histogram(hrs, bins=min(28, max(5, len(hrs)//3)))
        hist_hrs = {"counts": counts.tolist(), "edges": [round(float(e),2) for e in edges]}
    else:
        hist_hrs = {"counts": [], "edges": []}

    diffs = diff_valid["diff_hrs"].dropna().tolist()
    if diffs:
        counts_d, edges_d = np.histogram(diffs, bins=min(28, max(5, len(diffs)//3)))
        hist_diff = {"counts": counts_d.tolist(), "edges": [round(float(e),2) for e in edges_d]}
    else:
        hist_diff = {"counts": [], "edges": []}

    acts = {
        "Vuelos":        int(exe_active["flight_sectors"].sum()),
        "Días Libre":    int(exe_active["day_off"].sum()),
        "Vacaciones":    int(exe_active["vac_days"].sum()),
        "L. Médica":     int(exe_active["sick_days"].sum()),
        "Simulador":     int(exe_active["sim_days"].sum()),
        "Turno Apto.":   int(exe_active["asb_days"].sum()),
        "Turno Dom.":    int(exe_active["hsb_days"].sum()),
        "Entrenamiento": int(exe_active["ground_days"].sum()),
        "OOF":           int(exe_active["oof_days"].sum()),
    }

    top20 = exe_active.nlargest(20, "flight_block_hours")[
        ["full_name","flight_block_hours","flight_sectors"]
    ].copy()
    top20["short"] = top20["full_name"].apply(
        lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else ""
    )

    scat = diff_valid[diff_valid["exe_flight_hours"].notna()].copy()
    scat["short"] = scat["full_name"].apply(
        lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else ""
    )

    return {
        "n_total":     int(exe_sub["staff_num"].nunique()),
        "n_active":    int(exe_active["staff_num"].nunique()),
        "avg_exe_hrs": safe(exe_active["flight_block_hours"].mean()),
        "avg_pub_hrs": safe(adh_sub["pub_flight_hours"].mean()),
        "avg_diff":    safe(diff_valid["diff_hrs"].mean()),
        "avg_sectors": safe(exe_active["flight_sectors"].mean()),
        "n_more_exe":  int((diff_valid["more_is"]=="Ejecutado").sum()),
        "n_more_pub":  int((diff_valid["more_is"]=="Publicado").sum()),
        "n_equal":     int((diff_valid["more_is"]=="Igual").sum()),
        "hist_hrs":    hist_hrs,
        "hist_diff":   hist_diff,
        "activities":  acts,
        "top20": {
            "names":   top20["short"].tolist(),
            "hours":   [safe(h) for h in top20["flight_block_hours"].tolist()],
            "sectors": top20["flight_sectors"].tolist(),
        },
        "scatter": {
            "exe_hrs":  [safe(v) for v in scat["exe_flight_hours"].tolist()],
            "diff_hrs": [safe(v) for v in scat["diff_hrs"].tolist()],
            "names":    scat["short"].tolist(),
        },
    }

# ── Overview: keyed by rank → fleet_type → period ────────────────────────────
overview = {}
for rank in RANKS:
    overview[rank] = {}
    for ft in FLEET_TYPES:
        overview[rank][ft] = {}
        for period in periods_exe:
            exe_s = kpis[
                (kpis["rol_type"]=="Ejecutado") & (kpis["periodo"]==period) &
                (kpis["rank"]==rank) & (kpis["fleet_type"]==ft)
            ]
            adh_s = adh[
                (adh["rank"]==rank) & (adh["fleet_type"]==ft) & (adh["periodo"]==period)
            ]
            overview[rank][ft][period] = build_overview_block(exe_s, adh_s, period, f"{rank}/{ft}")

# ── Trends: rank → fleet_type ────────────────────────────────────────────────
trends = {}
for rank in RANKS:
    trends[rank] = {}
    for ft in FLEET_TYPES:
        t_hrs = kpis[
            (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) &
            (kpis["fleet_type"]==ft) & (~kpis["prolonged_absence"])
        ].groupby("periodo").agg(
            avg_exe=("flight_block_hours","mean"),
            n_pilots=("staff_num","nunique"),
        ).reset_index()
        t_hrs = t_hrs[t_hrs["periodo"].isin(periods_exe)].sort_values("periodo")

        t_diff = adh[
            (adh["rank"]==rank) & (adh["fleet_type"]==ft) &
            adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
            ~(adh["exe_prolonged"].fillna(False) | adh["pub_prolonged"].fillna(False))
        ].groupby("periodo").agg(
            avg_exe=("exe_flight_hours","mean"),
            avg_pub=("pub_flight_hours","mean"),
            avg_diff=("diff_hrs","mean"),
        ).reset_index()
        t_diff = t_diff[t_diff["periodo"].isin(periods_exe)].sort_values("periodo")

        trends[rank][ft] = {
            "periods":      t_hrs["periodo"].tolist(),
            "avg_exe":      [round(float(v),2) for v in t_hrs["avg_exe"].fillna(0)],
            "n_pilots":     t_hrs["n_pilots"].tolist(),
            "diff_periods": t_diff["periodo"].tolist(),
            "avg_exe_trend":[round(float(v),2) for v in t_diff["avg_exe"].fillna(0)],
            "avg_pub_trend":[round(float(v),2) for v in t_diff["avg_pub"].fillna(0)],
            "avg_diff":     [round(float(v),2) for v in t_diff["avg_diff"].fillna(0)],
        }

# ── Pilots list: rank → fleet_type ───────────────────────────────────────────
pilots = {}
for rank in RANKS:
    pilots[rank] = {}
    for ft in FLEET_TYPES:
        sub = adh[(adh["rank"]==rank) & (adh["fleet_type"]==ft)].dropna(subset=["full_name"])
        names = sub.drop_duplicates("staff_num")[["staff_num","full_name"]].sort_values("full_name")
        pilots[rank][ft] = [
            {"id": str(r["staff_num"]), "name": str(r["full_name"]).strip().title()}
            for _, r in names.iterrows()
        ]

# ── Peer stats: rank → fleet_type → period ───────────────────────────────────
peer_stats = {}
for rank in RANKS:
    peer_stats[rank] = {}
    for ft in FLEET_TYPES:
        peer_stats[rank][ft] = {}
        for period in periods_exe:
            pe = kpis[
                (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) &
                (kpis["fleet_type"]==ft) & (kpis["periodo"]==period) &
                (~kpis["prolonged_absence"])
            ]
            pa = adh[
                (adh["rank"]==rank) & (adh["fleet_type"]==ft) & (adh["periodo"]==period) &
                adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
                ~(adh["exe_prolonged"].fillna(False) | adh["pub_prolonged"].fillna(False))
            ]
            peer_stats[rank][ft][period] = {
                "avg_exe_hrs":  sm(pe["flight_block_hours"]),
                "avg_pub_hrs":  sm(pa["pub_flight_hours"]),
                "avg_sectors":  sm(pe["flight_sectors"]),
                "avg_days_fly": sm(pe["days_with_flights"]),
                "avg_diff":     sm(pa["diff_hrs"]),
                "avg_day_off":  sm(pe["day_off"]),
                "avg_vac":      sm(pe["vac_days"]),
                "avg_sick":     sm(pe["sick_days"]),
                "avg_sim":      sm(pe["sim_days"]),
                "avg_asb":      sm(pe["asb_days"]),
                "avg_hsb":      sm(pe["hsb_days"]),
                "avg_ground":   sm(pe["ground_days"]),
                "avg_oof":      sm(pe["oof_days"]),
                "hrs_dist":     [round(float(v),2) for v in pe["flight_block_hours"].dropna()],
                "diff_dist":    [round(float(v),2) for v in pa["diff_hrs"].dropna()],
            }

# ── Peer trends for pilot comparison lines ────────────────────────────────────
peer_trends = {}
for rank in RANKS:
    peer_trends[rank] = {}
    for ft in FLEET_TYPES:
        pt = adh[
            (adh["rank"]==rank) & (adh["fleet_type"]==ft) &
            adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
            ~(adh["exe_prolonged"].fillna(False) | adh["pub_prolonged"].fillna(False))
        ].groupby("periodo").agg(
            avg_exe=("exe_flight_hours","mean"),
            avg_pub=("pub_flight_hours","mean"),
            avg_diff=("diff_hrs","mean"),
        ).reset_index().sort_values("periodo")
        pt = pt[pt["periodo"].isin(periods_exe)]
        peer_trends[rank][ft] = {
            "periods":  pt["periodo"].tolist(),
            "avg_exe":  [round(float(v),2) for v in pt["avg_exe"].fillna(0)],
            "avg_pub":  [round(float(v),2) for v in pt["avg_pub"].fillna(0)],
            "avg_diff": [round(float(v),2) for v in pt["avg_diff"].fillna(0)],
        }

# ── Per-pilot history ─────────────────────────────────────────────────────────
print(f"Computing pilot data for {sum(len(v) for ft_d in pilots.values() for v in ft_d.values())} pilots...")
pilot_data = {}
for rank in RANKS:
    for ft in FLEET_TYPES:
        for p in pilots[rank][ft]:
            pid = p["id"]
            if pid in pilot_data: continue   # already processed
            p_adh = adh[adh["staff_num"]==pid]
            p_kpi = kpis[(kpis["staff_num"]==pid) & (kpis["rol_type"]=="Ejecutado")]

            history = {}
            for period in all_periods_chron:
                row  = p_adh[p_adh["periodo"]==period]
                ekpi = p_kpi[p_kpi["periodo"]==period]
                r    = row.iloc[0] if len(row) else None
                exe_h = clean(r["exe_flight_hours"]) if r is not None else None
                pub_h = clean(r["pub_flight_hours"]) if r is not None else None

                diff_h = None; more_is = None
                if exe_h is not None and pub_h is not None:
                    diff_h = round(exe_h - pub_h, 2)
                    more_is = "Ejecutado" if diff_h > 0.5 else ("Publicado" if diff_h < -0.5 else "Igual")
                elif pub_h is not None:
                    diff_h = round(-pub_h, 2); more_is = "Publicado"

                history[period] = {
                    "exe_hrs":  exe_h, "pub_hrs": pub_h,
                    "diff_hrs": diff_h, "more_is": more_is,
                    "sectors":  int(ekpi["flight_sectors"].sum())   if len(ekpi) else 0,
                    "days_fly": int(ekpi["days_with_flights"].sum()) if len(ekpi) else 0,
                    "day_off":  int(ekpi["day_off"].sum())  if len(ekpi) else 0,
                    "sick":     int(ekpi["sick_days"].sum()) if len(ekpi) else 0,
                    "vac":      int(ekpi["vac_days"].sum())  if len(ekpi) else 0,
                    "sim":      int(ekpi["sim_days"].sum())  if len(ekpi) else 0,
                    "asb":      int(ekpi["asb_days"].sum())  if len(ekpi) else 0,
                    "hsb":      int(ekpi["hsb_days"].sum())  if len(ekpi) else 0,
                    "ground":   int(ekpi["ground_days"].sum()) if len(ekpi) else 0,
                    "oof":      int(ekpi["oof_days"].sum())  if len(ekpi) else 0,
                }
            pilot_data[pid] = {"name": p["name"], "rank": rank, "fleet_type": ft, "history": history}

# ── Assemble & write ──────────────────────────────────────────────────────────
all_fmt_p = set(all_periods_chron)
payload = {
    "generated_at":  pd.Timestamp.now().strftime("%d/%m/%Y %H:%M UTC"),
    "periods_exe":   periods_exe,
    "periods_chron": all_periods_chron,
    "periods_fmt":   {p: fmt_period(p) for p in all_fmt_p},
    "fleet_types":   FLEET_TYPES,
    "ranks":         RANKS,
    "overview":      overview,
    "trends":        trends,
    "peer_stats":    peer_stats,
    "peer_trends":   peer_trends,
    "pilots":        pilots,
    "pilot_data":    pilot_data,
}

out_path = OUT_DIR / "data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",",":"))

kb = out_path.stat().st_size / 1024
print(f"✓  {out_path}  ({kb:.0f} KB)")
for rank in RANKS:
    for ft in FLEET_TYPES:
        n = len(pilots[rank][ft])
        print(f"   {rank} / {ft}: {n} pilotos")
