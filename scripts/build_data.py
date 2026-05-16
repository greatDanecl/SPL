"""
build_data.py  –  SPL Dashboard static data builder
Reads all Excel files from data/, computes KPIs + differences (Ejecutado vs Publicado),
and writes docs/data.json for the static HTML dashboard.
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
    if val is None: return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return None
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (np.floating,)): return None if math.isnan(float(val)) else round(float(val), 2)
    if isinstance(val, (np.bool_,)): return bool(val)
    if isinstance(val, pd.Timestamp): return str(val)
    return val

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

# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading data...")
raw  = load_all_data()
kpis = compute_monthly_kpis(raw)
adh  = compute_adherence(kpis)

adh  = adh[adh["rank"].isin(["CP","FO"])].copy()
kpis = kpis[kpis["rank"].isin(["CP","FO"])].copy()

periods_exe = sorted(
    kpis[kpis["rol_type"] == "Ejecutado"]["periodo"].dropna().unique(), reverse=True
)
all_periods_chron = sorted(periods_exe)

adh["diff_hrs"] = (adh["exe_flight_hours"].fillna(0) - adh["pub_flight_hours"].fillna(0)).round(2)
adh["more_is"] = np.where(
    adh["diff_hrs"] > 0.5, "Ejecutado",
    np.where(adh["diff_hrs"] < -0.5, "Publicado", "Igual")
)

print(f"  periods_exe={periods_exe}")

# ── Overview per rank+period ──────────────────────────────────────────────────
overview = {}
for rank in ("CP","FO"):
    overview[rank] = {}
    for period in periods_exe:
        exe = kpis[(kpis["rol_type"]=="Ejecutado") & (kpis["periodo"]==period) & (kpis["rank"]==rank)]
        adh_p = adh[(adh["rank"]==rank) & (adh["periodo"]==period)]
        exe_active = exe[~exe["prolonged_absence"]]
        diff_valid = adh_p[
            adh_p["exe_flight_hours"].notna() & adh_p["pub_flight_hours"].notna() &
            ~(adh_p["exe_prolonged"].fillna(False) | adh_p["pub_prolonged"].fillna(False))
        ].copy()

        def safe(v):
            if v is None: return None
            try:
                f = float(v)
                return None if math.isnan(f) else round(f, 2)
            except: return None

        hrs = exe_active["flight_block_hours"].dropna().tolist()
        if hrs:
            counts, edges = np.histogram(hrs, bins=28)
            hist_hrs = {"counts": counts.tolist(), "edges": [round(float(e),2) for e in edges]}
        else:
            hist_hrs = {"counts": [], "edges": []}

        diffs = diff_valid["diff_hrs"].dropna().tolist()
        if diffs:
            counts_d, edges_d = np.histogram(diffs, bins=28)
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

        top20 = exe_active.nlargest(20,"flight_block_hours")[["full_name","flight_block_hours","flight_sectors"]].copy()
        top20["short"] = top20["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")

        scat = diff_valid[diff_valid["exe_flight_hours"].notna()].copy()
        scat["short"] = scat["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")

        overview[rank][period] = {
            "n_total":     int(exe["staff_num"].nunique()),
            "n_active":    int(exe_active["staff_num"].nunique()),
            "avg_exe_hrs": safe(exe_active["flight_block_hours"].mean()),
            "avg_pub_hrs": safe(adh_p["pub_flight_hours"].mean()),
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

# ── Trends per rank ───────────────────────────────────────────────────────────
trends = {}
for rank in ("CP","FO"):
    trend_hrs = kpis[
        (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) & (~kpis["prolonged_absence"])
    ].groupby("periodo").agg(avg_exe=("flight_block_hours","mean"), n_pilots=("staff_num","nunique")).reset_index().sort_values("periodo")

    trend_diff = adh[
        (adh["rank"]==rank) &
        adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
        ~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))
    ].groupby("periodo").agg(
        avg_exe=("exe_flight_hours","mean"),
        avg_pub=("pub_flight_hours","mean"),
        avg_diff=("diff_hrs","mean"),
    ).reset_index().sort_values("periodo")
    # Limit to periods with exec data
    trend_diff = trend_diff[trend_diff["periodo"].isin(periods_exe)]

    trends[rank] = {
        "periods":      [p for p in trend_hrs["periodo"].tolist() if p in periods_exe],
        "avg_exe":      [round(float(v),2) for v in trend_hrs[trend_hrs["periodo"].isin(periods_exe)]["avg_exe"].fillna(0)],
        "n_pilots":     trend_hrs[trend_hrs["periodo"].isin(periods_exe)]["n_pilots"].tolist(),
        "diff_periods": trend_diff["periodo"].tolist(),
        "avg_exe_trend":[round(float(v),2) for v in trend_diff["avg_exe"].fillna(0)],
        "avg_pub_trend":[round(float(v),2) for v in trend_diff["avg_pub"].fillna(0)],
        "avg_diff":     [round(float(v),2) for v in trend_diff["avg_diff"].fillna(0)],
    }

# ── Pilot list & peer stats ───────────────────────────────────────────────────
pilots = {}
for rank in ("CP","FO"):
    sub = adh[adh["rank"]==rank].dropna(subset=["full_name"])
    names = sub.drop_duplicates("staff_num")[["staff_num","full_name"]].sort_values("full_name")
    pilots[rank] = [{"id": str(r["staff_num"]), "name": str(r["full_name"]).strip().title()} for _, r in names.iterrows()]

peer_stats = {}
for rank in ("CP","FO"):
    peer_stats[rank] = {}
    for period in periods_exe:
        pe = kpis[(kpis["rol_type"]=="Ejecutado")&(kpis["rank"]==rank)&(kpis["periodo"]==period)&(~kpis["prolonged_absence"])]
        pa = adh[(adh["rank"]==rank)&(adh["periodo"]==period)&
                 adh["exe_flight_hours"].notna()&adh["pub_flight_hours"].notna()&
                 ~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))]
        def sm(s): return round(float(s.mean()),2) if len(s)>0 else 0.0
        peer_stats[rank][period] = {
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

peer_trends = {}
for rank in ("CP","FO"):
    pt = adh[
        (adh["rank"]==rank) &
        adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
        ~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))
    ].groupby("periodo").agg(
        avg_exe=("exe_flight_hours","mean"),
        avg_pub=("pub_flight_hours","mean"),
        avg_diff=("diff_hrs","mean"),
    ).reset_index().sort_values("periodo")
    pt = pt[pt["periodo"].isin(periods_exe)]
    peer_trends[rank] = {
        "periods":  pt["periodo"].tolist(),
        "avg_exe":  [round(float(v),2) for v in pt["avg_exe"].fillna(0)],
        "avg_pub":  [round(float(v),2) for v in pt["avg_pub"].fillna(0)],
        "avg_diff": [round(float(v),2) for v in pt["avg_diff"].fillna(0)],
    }

# ── Per-pilot history ─────────────────────────────────────────────────────────
print(f"Computing pilot data for {sum(len(v) for v in pilots.values())} pilots...")
pilot_data = {}
for rank in ("CP","FO"):
    for p in pilots[rank]:
        pid = p["id"]
        pilot_adh = adh[adh["staff_num"]==pid]
        pilot_kpi = kpis[(kpis["staff_num"]==pid)&(kpis["rol_type"]=="Ejecutado")]

        history = {}
        for period in all_periods_chron:
            row  = pilot_adh[pilot_adh["periodo"]==period]
            ekpi = pilot_kpi[pilot_kpi["periodo"]==period]
            r    = row.iloc[0] if len(row) else None
            exe_h = clean(r["exe_flight_hours"]) if r is not None else None
            pub_h = clean(r["pub_flight_hours"]) if r is not None else None

            diff_h  = None
            more_is = None
            if exe_h is not None and pub_h is not None:
                diff_h = round(exe_h - pub_h, 2)
                more_is = "Ejecutado" if diff_h > 0.5 else ("Publicado" if diff_h < -0.5 else "Igual")
            elif pub_h is not None:
                diff_h = round(-pub_h, 2)
                more_is = "Publicado"

            history[period] = {
                "exe_hrs":  exe_h,
                "pub_hrs":  pub_h,
                "diff_hrs": diff_h,
                "more_is":  more_is,
                "sectors":  int(ekpi["flight_sectors"].sum()) if len(ekpi) else 0,
                "days_fly": int(ekpi["days_with_flights"].sum()) if len(ekpi) else 0,
                "day_off":  int(ekpi["day_off"].sum()) if len(ekpi) else 0,
                "sick":     int(ekpi["sick_days"].sum()) if len(ekpi) else 0,
                "vac":      int(ekpi["vac_days"].sum()) if len(ekpi) else 0,
                "sim":      int(ekpi["sim_days"].sum()) if len(ekpi) else 0,
                "asb":      int(ekpi["asb_days"].sum()) if len(ekpi) else 0,
                "hsb":      int(ekpi["hsb_days"].sum()) if len(ekpi) else 0,
                "ground":   int(ekpi["ground_days"].sum()) if len(ekpi) else 0,
                "oof":      int(ekpi["oof_days"].sum()) if len(ekpi) else 0,
            }
        pilot_data[pid] = {"name": p["name"], "rank": rank, "history": history}

# ── Write JSON ────────────────────────────────────────────────────────────────
all_fmt_periods = set(periods_exe)
for rank in ("CP","FO"):
    all_fmt_periods |= set(peer_trends.get(rank,{}).get("periods",[]))
    all_fmt_periods |= set(trends.get(rank,{}).get("periods",[]))
all_fmt_periods |= set(all_periods_chron)

payload = {
    "generated_at":  pd.Timestamp.now().strftime("%d/%m/%Y %H:%M UTC"),
    "periods_exe":   periods_exe,
    "periods_chron": all_periods_chron,
    "periods_fmt":   {p: fmt_period(p) for p in all_fmt_periods},
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

size_kb = out_path.stat().st_size / 1024
print(f"✓  {out_path}  ({size_kb:.0f} KB)")
print(f"   CP={len(pilots.get('CP',[]))}  FO={len(pilots.get('FO',[]))}")
