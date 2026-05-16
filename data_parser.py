"""
SPL Dashboard - Data Parser
Handles all Excel file formats and normalizes data for the dashboard.
Designed to auto-detect and load new files dropped into the data/ folder.
"""

import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"

# ─── Activity code mappings ──────────────────────────────────────────────────
CODES_FILE = DATA_DIR / "CA__DIGOS_IFN.xlsx"

def load_activity_codes():
    try:
        df = pd.read_excel(CODES_FILE, sheet_name="Table 1", header=1)
        df.columns = ["sabre_code", "description", "activity_type", "code_ifn"]
        df = df.dropna(subset=["sabre_code"])
        df["sabre_code"] = df["sabre_code"].astype(str).str.strip()
        return df.set_index("sabre_code").to_dict(orient="index")
    except Exception:
        return {}

ACTIVITY_CODES = load_activity_codes()

# Extended manual mappings for patterns not in the codes file
FLIGHT_PATTERN = re.compile(r'^LA\d+', re.IGNORECASE)
AIRPORT_PATTERN = re.compile(r'^(AS|RAP|RAM|RTA|RIA)', re.IGNORECASE)
HOME_PATTERN = re.compile(r'^(HS|RAB|GAM|GPM)', re.IGNORECASE)
SIM_PATTERN = re.compile(r'^(ISIM|SIM|ASS)', re.IGNORECASE)

ABSENCE_ACTIVITY_TYPES = {"DayOff", "Vacation", "Medical", "OOF"}
ABSENCE_CODES = {"VAC", "SICK", "OOF", "VUSA", "DO", "DH", "DB", "DR",
                 "DOR1", "DOR2", "DOR3", "DOR4", "DW", "DOM", "Q", "LAC", "LFS"}
PROLONGED_ABSENCE_CODES = {"VAC", "SICK", "OOF"}

def classify_activity(code):
    if pd.isna(code) or code == "":
        return "Unknown", "Unknown"
    code_str = str(code).strip().upper()

    if FLIGHT_PATTERN.match(code_str):
        return "Flight", "Vuelo"

    info = ACTIVITY_CODES.get(code_str, ACTIVITY_CODES.get(code.strip(), None))
    if info:
        atype = info.get("activity_type", "Unknown")
        desc = info.get("description", code_str)
        return atype, desc

    if AIRPORT_PATTERN.match(code_str):
        return "Airport Stand by", "Turno Aeropuerto"
    if HOME_PATTERN.match(code_str):
        return "Home Stand by", "Turno Domicilio"
    if SIM_PATTERN.match(code_str):
        return "SIM", "Simulador"
    if code_str in ("B", "BLANK"):
        return "Blank", "Día Blanco"
    if code_str in ("DO", "DH", "DB", "DR", "DOR1", "DOR2", "DOR3", "DOR4", "DW", "DOM", "LAC", "LFS"):
        return "DayOff", "Día Libre"
    if code_str == "VAC":
        return "Vacation", "Vacaciones"
    if code_str == "SICK":
        return "Medical", "Licencia Médica"
    if code_str == "OOF":
        return "OOF", "Fuera de Vuelo"
    if code_str == "VUSA":
        return "VUSA", "Trámite Visado"
    if code_str == "Q":
        return "Blank", "Bloque Libre Quincena"
    if code_str.startswith("CLA") or code_str.startswith("CTE"):
        return "Ground training", "Clases en Tierra"
    if code_str == "RL":
        return "Ground", "REVA"
    if code_str.startswith("AS"):
        return "Airport Stand by", "Turno Aeropuerto"
    if code_str.startswith("HS"):
        return "Home Stand by", "Turno Domicilio"
    return "Other", code_str

# ─── Time helpers ────────────────────────────────────────────────────────────

def block_time_to_hours(val):
    if pd.isna(val):
        return 0.0
    if hasattr(val, "hour"):
        return val.hour + val.minute / 60 + val.second / 3600
    if isinstance(val, str):
        parts = val.strip().split(":")
        if len(parts) >= 2:
            return int(parts[0]) + int(parts[1]) / 60
    if isinstance(val, (int, float)):
        return float(val) * 24
    return 0.0

def parse_date(val):
    if pd.isna(val):
        return pd.NaT
    if isinstance(val, (pd.Timestamp, datetime)):
        return pd.Timestamp(val)
    s = str(val).strip()
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    try:
        return pd.Timestamp(s)
    except Exception:
        return pd.NaT

# ─── Normaliser for SPL new format (columns in Spanish) ──────────────────────

def _norm_new_format(df, source_file):
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    rename = {
        "crew_id": "staff_num",
        "nombre_completo": "full_name",
        "aircraft_type_desc": "fleet",
        "company_code": "company",
        "rank_code": "rank",
        "str_dt": "str_dt",
        "str_tm": "str_tm",
        "end_dt": "end_dt",
        "end_tm": "end_tm",
        "activity_code": "activity",
        "departure_airport_code": "dep_port",
        "arrival_airport_code": "arv_port",
        "block_time": "block_time",
        "sindicato": "union",
        "periodo": "periodo",
        "tipo_rol": "rol_type",
    }
    df = df.rename(columns=rename)
    df["staff_num"] = df["staff_num"].astype(str).str.strip().str.lstrip("0")
    df["str_dt"] = df["str_dt"].apply(parse_date)
    df["block_hours"] = df["block_time"].apply(block_time_to_hours)
    # periodo already in YYYY-MM format
    df["periodo"] = df["periodo"].astype(str).str.strip()
    df["full_name"] = df["full_name"].str.strip()
    df["source_file"] = source_file
    return df

# ─── Normaliser for old format (English column names) ────────────────────────

def _norm_old_format(df, rol_type, source_file):
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    rename = {
        "Staff Num": "staff_num",
        "First Name": "first_name",
        "Last Name": "last_name",
        "Company": "company",
        "Fleet": "fleet",
        "Rank": "rank",
        "Str Dt": "str_dt",
        "Str Tm": "str_tm",
        "End Dt": "end_dt",
        "End Tm": "end_tm",
        "Activity": "activity",
        "Operating": "operating",
        "Dep Port": "dep_port",
        "Arv Port": "arv_port",
        "Block Time": "block_time",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["staff_num"] = df["staff_num"].astype(str).str.strip().str.lstrip("0")
    df["str_dt"] = df["str_dt"].apply(parse_date)
    if "first_name" in df.columns and "last_name" in df.columns:
        df["full_name"] = (df["last_name"].fillna("") + " " + df["first_name"].fillna("")).str.strip()
    elif "full_name" not in df.columns:
        df["full_name"] = df["staff_num"]
    df["block_hours"] = df["block_time"].apply(block_time_to_hours)
    df["rol_type"] = rol_type
    # Derive periodo from dates
    df["periodo"] = df["str_dt"].dt.to_period("M").astype(str)
    df["source_file"] = source_file
    return df

# ─── File loaders ────────────────────────────────────────────────────────────

def _load_file(path: Path) -> pd.DataFrame:
    fname = path.stem
    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        print(f"  Could not open {path.name}: {e}")
        return pd.DataFrame()

    frames = []
    for sheet in xl.sheet_names:
        try:
            raw = pd.read_excel(path, sheet_name=sheet, header=0, dtype=str)
        except Exception:
            continue
        if raw.empty:
            continue
        cols = [c.strip() for c in raw.columns]

        # New SPL format
        if "crew_id" in cols and "tipo_rol" in cols:
            raw.columns = cols
            f = _norm_new_format(raw, fname)
            frames.append(f)
        # Old format – need to determine rol_type from filename
        elif "Staff Num" in cols or "staff num" in [c.lower() for c in cols]:
            raw.columns = cols
            if "efectuado" in fname.lower() or "efect" in fname.lower():
                rol = "Ejecutado"
            elif "publicado" in fname.lower() or "pub" in fname.lower() or "sind" in fname.lower():
                rol = "Publicado"
            else:
                rol = "Publicado"
            f = _norm_old_format(raw, rol, fname)
            frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

# ─── Main loader ─────────────────────────────────────────────────────────────

SKIP_FILES = {"CA__DIGOS_IFN.xlsx"}

def load_all_data() -> pd.DataFrame:
    all_frames = []
    for fpath in sorted(DATA_DIR.glob("*.xlsx")):
        if fpath.name in SKIP_FILES:
            continue
        print(f"Loading {fpath.name}...")
        df = _load_file(fpath)
        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        return pd.DataFrame()

    data = pd.concat(all_frames, ignore_index=True)

    # Keep only relevant columns
    keep = ["staff_num", "full_name", "rank", "company", "fleet",
            "str_dt", "activity", "dep_port", "arv_port",
            "block_hours", "rol_type", "periodo", "source_file"]
    for c in keep:
        if c not in data.columns:
            data[c] = None
    data = data[keep].copy()

    # Clean up
    data["rank"] = data["rank"].fillna("").str.strip().str.upper()
    data["activity"] = data["activity"].fillna("").str.strip()
    data["rol_type"] = data["rol_type"].fillna("").str.strip()
    data["block_hours"] = pd.to_numeric(data["block_hours"], errors="coerce").fillna(0)

    # Classify activities
    classified = data["activity"].apply(classify_activity)
    data["activity_type"] = [c[0] for c in classified]
    data["activity_label"] = [c[1] for c in classified]

    # Filter to CP/FO only
    data = data[data["rank"].isin(["CP", "FO"])].copy()

    # Deduplicate – same worker/date/activity/rol_type may appear in multiple files
    data = data.drop_duplicates(
        subset=["staff_num", "str_dt", "activity", "rol_type"], keep="last"
    )

    data["str_dt"] = pd.to_datetime(data["str_dt"], errors="coerce")
    data = data.dropna(subset=["str_dt"])

    # Ensure periodo aligns with str_dt month
    data["periodo"] = data["str_dt"].dt.to_period("M").astype(str)

    print(f"Total records loaded: {len(data)}")
    return data

# ─── KPI helpers ─────────────────────────────────────────────────────────────

def is_prolonged_absence(df_worker_month):
    """Return True if worker had prolonged absence (VAC/SICK/OOF) >= 7 days in month."""
    abs_days = df_worker_month[
        df_worker_month["activity"].str.upper().isin(PROLONGED_ABSENCE_CODES)
    ]
    return len(abs_days) >= 7

def compute_monthly_kpis(data: pd.DataFrame) -> pd.DataFrame:
    """Compute per-worker per-period KPIs."""
    records = []
    for (staff, period, rol), grp in data.groupby(["staff_num", "periodo", "rol_type"]):
        flight = grp[grp["activity_type"] == "Flight"]
        total_block = grp["block_hours"].sum()
        flight_block = flight["block_hours"].sum()
        flight_sectors = len(flight)
        days_worked = grp[grp["activity_type"] == "Flight"]["str_dt"].nunique()
        day_off = grp[grp["activity_type"] == "DayOff"]["str_dt"].nunique()
        sick_days = grp[grp["activity"].str.upper() == "SICK"]["str_dt"].nunique()
        vac_days = grp[grp["activity"].str.upper() == "VAC"]["str_dt"].nunique()
        oof_days = grp[grp["activity"].str.upper() == "OOF"]["str_dt"].nunique()
        sim_days = grp[grp["activity_type"] == "SIM"]["str_dt"].nunique()
        asb_days = grp[grp["activity_type"] == "Airport Stand by"]["str_dt"].nunique()
        hsb_days = grp[grp["activity_type"] == "Home Stand by"]["str_dt"].nunique()
        ground_days = grp[grp["activity_type"].isin(["Ground", "Ground training"])]["str_dt"].nunique()
        prolonged = is_prolonged_absence(grp)
        unique_routes = set(zip(flight["dep_port"].fillna(""), flight["arv_port"].fillna("")))
        num_intl = sum(1 for r in unique_routes if r[1] not in ("SCL", "") and r[0] not in ("SCL", ""))

        records.append({
            "staff_num": staff,
            "periodo": period,
            "rol_type": rol,
            "rank": grp["rank"].iloc[0],
            "full_name": grp["full_name"].iloc[0],
            "total_block_hours": round(total_block, 2),
            "flight_block_hours": round(flight_block, 2),
            "flight_sectors": flight_sectors,
            "days_with_flights": days_worked,
            "day_off": day_off,
            "sick_days": sick_days,
            "vac_days": vac_days,
            "oof_days": oof_days,
            "sim_days": sim_days,
            "asb_days": asb_days,
            "hsb_days": hsb_days,
            "ground_days": ground_days,
            "prolonged_absence": prolonged,
            "num_routes": len(unique_routes),
            "num_intl_routes": num_intl,
        })
    return pd.DataFrame(records)

def compute_adherence(kpis: pd.DataFrame) -> pd.DataFrame:
    """Compute adherence ratio (ejecutado / publicado) per worker per month."""
    pub = kpis[kpis["rol_type"] == "Publicado"][
        ["staff_num", "periodo", "rank", "full_name",
         "total_block_hours", "flight_block_hours", "flight_sectors",
         "prolonged_absence"]
    ].rename(columns={
        "total_block_hours": "pub_total_hours",
        "flight_block_hours": "pub_flight_hours",
        "flight_sectors": "pub_sectors",
        "prolonged_absence": "pub_prolonged",
    })

    exe = kpis[kpis["rol_type"] == "Ejecutado"][
        ["staff_num", "periodo",
         "total_block_hours", "flight_block_hours", "flight_sectors",
         "day_off", "sick_days", "vac_days", "oof_days",
         "sim_days", "asb_days", "hsb_days", "ground_days",
         "num_routes", "num_intl_routes",
         "days_with_flights", "prolonged_absence"]
    ].rename(columns={
        "total_block_hours": "exe_total_hours",
        "flight_block_hours": "exe_flight_hours",
        "flight_sectors": "exe_sectors",
        "prolonged_absence": "exe_prolonged",
    })

    merged = pd.merge(pub, exe, on=["staff_num", "periodo"], how="outer")

    def safe_ratio(a, b):
        if pd.isna(b) or b == 0:
            return np.nan
        if pd.isna(a):
            return 0.0
        return min(round(a / b, 4), 2.0)  # cap at 2 to avoid outliers from data issues

    merged["adherence_total"] = merged.apply(
        lambda r: safe_ratio(r["exe_total_hours"], r["pub_total_hours"]), axis=1
    )
    merged["adherence_flight"] = merged.apply(
        lambda r: safe_ratio(r["exe_flight_hours"], r["pub_flight_hours"]), axis=1
    )

    return merged
