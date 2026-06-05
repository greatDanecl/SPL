"""
build_data.py – SPL Dashboard static data builder v2
- Incluye períodos solo-Publicado (ej. Mayo 2026) marcados como pub_only=True
- Agrega bloque 'directiva' con KPIs ejecutivos agregados
- Segmenta por rank (CP/FO) y fleet_type (Wide Body / Narrow Body)
"""
import sys, json, math
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent   # scripts/ -> repo root
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

adh  = adh[adh["rank"].isin(RANKS)].copy()
kpis = kpis[kpis["rank"].isin(RANKS)].copy()

fleet_map = kpis.drop_duplicates("staff_num").set_index("staff_num")["fleet_type"].to_dict()
adh["fleet_type"] = adh["staff_num"].map(fleet_map)

adh["diff_hrs"] = (adh["exe_flight_hours"].fillna(0) - adh["pub_flight_hours"].fillna(0)).round(2)
adh["more_is"] = np.where(
    adh["diff_hrs"] >  0.5, "Ejecutado",
    np.where(adh["diff_hrs"] < -0.5, "Publicado", "Igual")
)

# Períodos con ejecutado — solo incluir si tiene >= 50 pilotos activos
# (evita overflow de días de fin de mes del archivo siguiente)
all_exe_periods = kpis[kpis["rol_type"]=="Ejecutado"]["periodo"].dropna().unique()
exe_pilot_counts = kpis[kpis["rol_type"]=="Ejecutado"].groupby("periodo")["staff_num"].nunique()
pub_periods_set = set(kpis[kpis["rol_type"]=="Publicado"]["periodo"].dropna().unique())
periods_exe = sorted(
    [p for p in all_exe_periods
     if exe_pilot_counts.get(p, 0) >= 50 and p in pub_periods_set],
    reverse=True
)
# Períodos SOLO publicado (sin ejecutado aún – ej. Mayo 2026)
all_pub_periods = kpis[kpis["rol_type"]=="Publicado"]["periodo"].dropna().unique()
periods_pub_only = sorted([
    p for p in all_pub_periods if p not in periods_exe
], reverse=True)

# Lista completa para el dropdown (ejecutados primero, luego pub-only)
all_dropdown_periods = periods_exe + periods_pub_only
all_periods_chron    = sorted(set(periods_exe) | set(periods_pub_only))

print(f"  periods_exe      = {periods_exe}")
print(f"  periods_pub_only = {periods_pub_only}")

# ── Helper: overview block ───────────────────────────────────────────────────
def build_overview_block(exe_sub, adh_sub, pub_only=False):
    exe_active = exe_sub[~exe_sub["prolonged_absence"]] if not pub_only else exe_sub
    diff_valid = adh_sub[
        adh_sub["exe_flight_hours"].notna() & adh_sub["pub_flight_hours"].notna() &
        ~(adh_sub["exe_prolonged"].fillna(False) | adh_sub["pub_prolonged"].fillna(False))
    ].copy()

    hrs = exe_active["flight_block_hours"].dropna().tolist() if not pub_only else []
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

    if pub_only:
        acts = {"Vuelos":0,"Días Libre":0,"Vacaciones":0,"L. Médica":0,
                "Simulador":0,"Turno Apto.":0,"Turno Dom.":0,"Entrenamiento":0,"OOF":0}
    else:
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

    top20 = exe_active.nlargest(20,"flight_block_hours")[["full_name","flight_block_hours","flight_sectors"]].copy() if not pub_only else pd.DataFrame()
    if not top20.empty:
        top20["short"] = top20["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")
        top20_d = {"names": top20["short"].tolist(), "hours": [safe(h) for h in top20["flight_block_hours"]], "sectors": top20["flight_sectors"].tolist()}
    else:
        top20_d = {"names":[], "hours":[], "sectors":[]}

    scat = diff_valid[diff_valid["exe_flight_hours"].notna()].copy()
    scat["short"] = scat["full_name"].apply(lambda n: " ".join(str(n).split()[:2]) if pd.notna(n) else "")

    # For pub_only: get pub stats from adh_sub pub_flight_hours
    avg_pub = safe(adh_sub["pub_flight_hours"].mean()) if not adh_sub.empty else None

    return {
        "pub_only":    pub_only,
        "n_total":     int(adh_sub["staff_num"].nunique()) if pub_only else int(exe_sub["staff_num"].nunique()),
        "n_active":    int(adh_sub["staff_num"].nunique()) if pub_only else int(exe_active["staff_num"].nunique()),
        "avg_exe_hrs": None if pub_only else safe(exe_active["flight_block_hours"].mean()),
        "avg_pub_hrs": avg_pub,
        "avg_diff":    None if pub_only else safe(diff_valid["diff_hrs"].mean()),
        "avg_sectors": None if pub_only else safe(exe_active["flight_sectors"].mean()),
        "n_more_exe":  0 if pub_only else int((diff_valid["more_is"]=="Ejecutado").sum()),
        "n_more_pub":  0 if pub_only else int((diff_valid["more_is"]=="Publicado").sum()),
        "n_equal":     0 if pub_only else int((diff_valid["more_is"]=="Igual").sum()),
        "hist_hrs":    hist_hrs,
        "hist_diff":   hist_diff,
        "activities":  acts,
        "top20":       top20_d,
        "scatter":     {"exe_hrs":[safe(v) for v in scat["exe_flight_hours"]],
                        "diff_hrs":[safe(v) for v in scat["diff_hrs"]],
                        "names":scat["short"].tolist()},
    }

# ── Overview: rank → fleet_type → period (exe + pub_only) ──────────────────
overview = {}
for rank in RANKS:
    overview[rank] = {}
    for ft in FLEET_TYPES:
        overview[rank][ft] = {}
        for period in all_dropdown_periods:
            is_pub_only = period in periods_pub_only
            exe_s = kpis[
                (kpis["rol_type"]=="Ejecutado") & (kpis["periodo"]==period) &
                (kpis["rank"]==rank) & (kpis["fleet_type"]==ft)
            ]
            adh_s = adh[
                (adh["rank"]==rank) & (adh["fleet_type"]==ft) & (adh["periodo"]==period)
            ]
            # For pub_only periods, adh_s will have pub_flight_hours from the Publicado kpis
            if is_pub_only:
                # Build a pseudo adh_s from pub kpis — enough for avg_pub_hrs display
                pub_k = kpis[
                    (kpis["rol_type"]=="Publicado") & (kpis["periodo"]==period) &
                    (kpis["rank"]==rank) & (kpis["fleet_type"]==ft)
                ].copy()
                pub_k = pub_k.rename(columns={"flight_block_hours":"pub_flight_hours"})
                pub_k["exe_flight_hours"] = None
                pub_k["exe_prolonged"]    = False
                pub_k["pub_prolonged"]    = pub_k["prolonged_absence"]
                pub_k["diff_hrs"]         = None
                pub_k["more_is"]          = None
                adh_s = pub_k[["staff_num","full_name","pub_flight_hours","exe_flight_hours",
                                "exe_prolonged","pub_prolonged","diff_hrs","more_is"]]
            overview[rank][ft][period] = build_overview_block(exe_s, adh_s, pub_only=is_pub_only)

# ── Trends ───────────────────────────────────────────────────────────────────
trends = {}
for rank in RANKS:
    trends[rank] = {}
    for ft in FLEET_TYPES:
        t_hrs = kpis[
            (kpis["rol_type"]=="Ejecutado") & (kpis["rank"]==rank) &
            (kpis["fleet_type"]==ft) & (~kpis["prolonged_absence"])
        ].groupby("periodo").agg(avg_exe=("flight_block_hours","mean"), n_pilots=("staff_num","nunique")).reset_index()
        t_hrs = t_hrs[t_hrs["periodo"].isin(periods_exe)].sort_values("periodo")

        t_diff = adh[
            (adh["rank"]==rank) & (adh["fleet_type"]==ft) &
            adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna() &
            ~(adh["exe_prolonged"].fillna(False) | adh["pub_prolonged"].fillna(False))
        ].groupby("periodo").agg(avg_exe=("exe_flight_hours","mean"), avg_pub=("pub_flight_hours","mean"), avg_diff=("diff_hrs","mean")).reset_index()
        t_diff = t_diff[t_diff["periodo"].isin(periods_exe)].sort_values("periodo")

        # Include pub_only periods in trend (pub hrs only)
        pub_trend = kpis[
            (kpis["rol_type"]=="Publicado") & (kpis["rank"]==rank) &
            (kpis["fleet_type"]==ft) & (~kpis["prolonged_absence"])
        ].groupby("periodo").agg(avg_pub=("flight_block_hours","mean")).reset_index()
        pub_trend = pub_trend[pub_trend["periodo"].isin(periods_pub_only)].sort_values("periodo")

        trends[rank][ft] = {
            "periods":      t_hrs["periodo"].tolist(),
            "avg_exe":      [round(float(v),2) for v in t_hrs["avg_exe"].fillna(0)],
            "n_pilots":     t_hrs["n_pilots"].tolist(),
            "diff_periods": t_diff["periodo"].tolist(),
            "avg_exe_trend":[round(float(v),2) for v in t_diff["avg_exe"].fillna(0)],
            "avg_pub_trend":[round(float(v),2) for v in t_diff["avg_pub"].fillna(0)],
            "avg_diff":     [round(float(v),2) for v in t_diff["avg_diff"].fillna(0)],
            # Extra: pub-only periods for the programmed view
            "pub_only_periods": pub_trend["periodo"].tolist(),
            "pub_only_avg_pub": [round(float(v),2) for v in pub_trend["avg_pub"].fillna(0)],
        }

# ── Pilots, peer_stats, peer_trends (unchanged) ──────────────────────────────
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

peer_stats = {}
for rank in RANKS:
    peer_stats[rank] = {}
    for ft in FLEET_TYPES:
        peer_stats[rank][ft] = {}
        for period in all_dropdown_periods:
            pe = kpis[(kpis["rol_type"]=="Ejecutado")&(kpis["rank"]==rank)&(kpis["fleet_type"]==ft)&(kpis["periodo"]==period)&(~kpis["prolonged_absence"])]
            pa = adh[(adh["rank"]==rank)&(adh["fleet_type"]==ft)&(adh["periodo"]==period)&adh["exe_flight_hours"].notna()&adh["pub_flight_hours"].notna()&~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))]
            peer_stats[rank][ft][period] = {
                "avg_exe_hrs":sm(pe["flight_block_hours"]), "avg_pub_hrs":sm(pa["pub_flight_hours"]),
                "avg_sectors":sm(pe["flight_sectors"]),    "avg_days_fly":sm(pe["days_with_flights"]),
                "avg_diff":sm(pa["diff_hrs"]),             "avg_day_off":sm(pe["day_off"]),
                "avg_vac":sm(pe["vac_days"]),              "avg_sick":sm(pe["sick_days"]),
                "avg_sim":sm(pe["sim_days"]),              "avg_asb":sm(pe["asb_days"]),
                "avg_hsb":sm(pe["hsb_days"]),              "avg_ground":sm(pe["ground_days"]),
                "avg_oof":sm(pe["oof_days"]),
                "avg_blk_day":round(float(pe["block_per_fly_day"].mean()),2) if pe["block_per_fly_day"].notna().any() else 0.0,
                "avg_legs_day":round(float(pe["legs_per_fly_day"].mean()),2) if pe["legs_per_fly_day"].notna().any() else 0.0,
                "hrs_dist":[round(float(v),2) for v in pe["flight_block_hours"].dropna()],
                "diff_dist":[round(float(v),2) for v in pa["diff_hrs"].dropna()],
            }

peer_trends = {}
for rank in RANKS:
    peer_trends[rank] = {}
    for ft in FLEET_TYPES:
        pt = adh[(adh["rank"]==rank)&(adh["fleet_type"]==ft)&adh["exe_flight_hours"].notna()&adh["pub_flight_hours"].notna()&~(adh["exe_prolonged"].fillna(False)|adh["pub_prolonged"].fillna(False))].groupby("periodo").agg(avg_exe=("exe_flight_hours","mean"),avg_pub=("pub_flight_hours","mean"),avg_diff=("diff_hrs","mean")).reset_index().sort_values("periodo")
        pt = pt[pt["periodo"].isin(periods_exe)]
        peer_trends[rank][ft] = {
            "periods":pt["periodo"].tolist(),
            "avg_exe":[round(float(v),2) for v in pt["avg_exe"].fillna(0)],
            "avg_pub":[round(float(v),2) for v in pt["avg_pub"].fillna(0)],
            "avg_diff":[round(float(v),2) for v in pt["avg_diff"].fillna(0)],
        }

# ── Per-pilot history ─────────────────────────────────────────────────────────
print(f"Computing pilot data for {sum(len(v) for ft_d in pilots.values() for v in ft_d.values())} pilots...")
pilot_data = {}
for rank in RANKS:
    for ft in FLEET_TYPES:
        for p in pilots[rank][ft]:
            pid = p["id"]
            if pid in pilot_data: continue
            p_adh = adh[adh["staff_num"]==pid]
            p_kpi_exe = kpis[(kpis["staff_num"]==pid)&(kpis["rol_type"]=="Ejecutado")]
            p_kpi_pub = kpis[(kpis["staff_num"]==pid)&(kpis["rol_type"]=="Publicado")]

            history = {}
            for period in all_periods_chron:
                is_pub_only = period in periods_pub_only
                row  = p_adh[p_adh["periodo"]==period]
                ekpi = p_kpi_exe[p_kpi_exe["periodo"]==period]
                pkpi = p_kpi_pub[p_kpi_pub["periodo"]==period]
                r    = row.iloc[0] if len(row) else None

                if is_pub_only:
                    # Only pub data available
                    pub_h = clean(pkpi["flight_block_hours"].iloc[0]) if len(pkpi) else None
                    history[period] = {
                        "exe_hrs":None, "pub_hrs":pub_h, "diff_hrs":None, "more_is":None,
                        "sectors":0,"days_fly":0,"day_off":0,"sick":0,"vac":0,"sim":0,"asb":0,"hsb":0,"ground":0,"oof":0,
                    }
                else:
                    exe_h = clean(r["exe_flight_hours"]) if r is not None else None
                    pub_h = clean(r["pub_flight_hours"]) if r is not None else None
                    diff_h = None; more_is = None
                    if exe_h is not None and pub_h is not None:
                        diff_h = round(exe_h - pub_h, 2)
                        more_is = "Ejecutado" if diff_h > 0.5 else ("Publicado" if diff_h < -0.5 else "Igual")
                    elif pub_h is not None:
                        diff_h = round(-pub_h, 2); more_is = "Publicado"
                    history[period] = {
                        "exe_hrs":exe_h, "pub_hrs":pub_h, "diff_hrs":diff_h, "more_is":more_is,
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
            pilot_data[pid] = {"name":p["name"],"rank":rank,"fleet_type":ft,"history":history}

# ── Directiva: KPIs ejecutivos agregados por período ─────────────────────────
print("Building directiva data...")

# Para la vista de directiva usamos TODOS los períodos (exe + pub_only)
# y sumamos CP + FO, WB + NB
directiva_periods = sorted(set(periods_exe) | set(periods_pub_only))

directiva = {}
for period in directiva_periods:
    is_pub = period in periods_pub_only
    exe_all = kpis[(kpis["rol_type"]=="Ejecutado") & (kpis["periodo"]==period) & (~kpis["prolonged_absence"])]
    pub_all = kpis[(kpis["rol_type"]=="Publicado") & (kpis["periodo"]==period) & (~kpis["prolonged_absence"])]
    adh_all = adh[(adh["periodo"]==period) & adh["exe_flight_hours"].notna() & adh["pub_flight_hours"].notna()
                  & ~(adh["exe_prolonged"].fillna(False) | adh["pub_prolonged"].fillna(False))]

    # Totales generales
    total_pilotos  = exe_all["staff_num"].nunique() if not is_pub else pub_all["staff_num"].nunique()
    total_legs     = int(exe_all["flight_sectors"].sum())
    total_exe_hrs  = round(float(exe_all["flight_block_hours"].sum()), 1)
    total_pub_hrs  = round(float(pub_all["flight_block_hours"].sum()), 1)
    total_diff_hrs = round(total_exe_hrs - total_pub_hrs, 1)
    sick_days_tot  = int(exe_all["sick_days"].sum())
    vac_days_tot   = int(exe_all["vac_days"].sum())
    oof_days_tot   = int(exe_all["oof_days"].sum())
    sim_days_tot   = int(exe_all["sim_days"].sum())

    # Por cargo
    by_rank = {}
    for rank in RANKS:
        re = exe_all[exe_all["rank"]==rank]
        rp = pub_all[pub_all["rank"]==rank]
        by_rank[rank] = {
            "n_pilotos":  int(re["staff_num"].nunique()),
            "total_legs": int(re["flight_sectors"].sum()),
            "exe_hrs":    round(float(re["flight_block_hours"].sum()),1),
            "pub_hrs":    round(float(rp["flight_block_hours"].sum()),1),
            "diff_hrs":   round(float(re["flight_block_hours"].sum()) - float(rp["flight_block_hours"].sum()),1),
            "sick_days":  int(re["sick_days"].sum()),
            "vac_days":   int(re["vac_days"].sum()),
            "oof_days":   int(re["oof_days"].sum()),
        }

    # Por flota
    by_fleet = {}
    for ft in FLEET_TYPES:
        fe = exe_all[exe_all["fleet_type"]==ft]
        fp = pub_all[pub_all["fleet_type"]==ft]
        by_fleet[ft] = {
            "n_pilotos":  int(fe["staff_num"].nunique()),
            "total_legs": int(fe["flight_sectors"].sum()),
            "exe_hrs":    round(float(fe["flight_block_hours"].sum()),1),
            "pub_hrs":    round(float(fp["flight_block_hours"].sum()),1),
            "diff_hrs":   round(float(fe["flight_block_hours"].sum()) - float(fp["flight_block_hours"].sum()),1),
        }

    # Distribución de diferencia (para el donut del directiva)
    n_more_exe = int((adh_all["more_is"]=="Ejecutado").sum())
    n_more_pub = int((adh_all["more_is"]=="Publicado").sum())
    n_equal    = int((adh_all["more_is"]=="Igual").sum())
    avg_diff   = safe(adh_all["diff_hrs"].mean())

    directiva[period] = {
        "pub_only":       is_pub,
        "total_pilotos":  total_pilotos,
        "total_legs":     total_legs,
        "total_exe_hrs":  total_exe_hrs,
        "total_pub_hrs":  total_pub_hrs,
        "total_diff_hrs": total_diff_hrs,
        "avg_diff":       avg_diff,
        "sick_days":      sick_days_tot,
        "vac_days":       vac_days_tot,
        "oof_days":       oof_days_tot,
        "sim_days":       sim_days_tot,
        "n_more_exe":     n_more_exe,
        "n_more_pub":     n_more_pub,
        "n_equal":        n_equal,
        "by_rank":        by_rank,
        "by_fleet":       by_fleet,
    }

# ── Directiva trend (multi-período) ──────────────────────────────────────────
dir_trend_periods = sorted(directiva.keys())
dir_trend = {
    "periods":       dir_trend_periods,
    "total_exe_hrs": [directiva[p]["total_exe_hrs"]  for p in dir_trend_periods],
    "total_pub_hrs": [directiva[p]["total_pub_hrs"]  for p in dir_trend_periods],
    "total_diff":    [directiva[p]["total_diff_hrs"] for p in dir_trend_periods],
    "total_legs":    [directiva[p]["total_legs"]     for p in dir_trend_periods],
    "sick_days":     [directiva[p]["sick_days"]      for p in dir_trend_periods],
    "pub_only":      [directiva[p]["pub_only"]       for p in dir_trend_periods],
}

# ── Assemble & write ──────────────────────────────────────────────────────────
all_fmt_p = set(all_dropdown_periods)
payload = {
    "generated_at":      pd.Timestamp.now().strftime("%d/%m/%Y %H:%M UTC"),
    "periods_exe":       periods_exe,
    "periods_pub_only":  periods_pub_only,
    "periods_dropdown":  all_dropdown_periods,   # ← nuevo: incluye pub-only
    "periods_chron":     all_periods_chron,
    "periods_fmt":       {p: fmt_period(p) for p in set(all_periods_chron)|all_fmt_p},
    "fleet_types":       FLEET_TYPES,
    "ranks":             RANKS,
    "overview":          overview,
    "trends":            trends,
    "peer_stats":        peer_stats,
    "peer_trends":       peer_trends,
    "pilots":            pilots,
    "pilot_data":        pilot_data,
    "directiva":         directiva,
    "dir_trend":         dir_trend,
}

out_path = OUT_DIR / "data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",",":"))

kb = out_path.stat().st_size / 1024
print(f"✓  {out_path}  ({kb:.0f} KB)")
print(f"   Dropdown periods: {all_dropdown_periods}")
for rank in RANKS:
    for ft in FLEET_TYPES:
        print(f"   {rank}/{ft}: {len(pilots[rank][ft])} pilotos")
