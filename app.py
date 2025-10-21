# app.py
import io, re, tempfile
import pandas as pd
import streamlit as st
from plan_cine import planificar  # importa el motor

st.set_page_config(page_title="Planificador Cinépolis", page_icon="🎬", layout="wide")
st.title("🎬 Planificador automático de cartelera Cinépolis Maipú")

st.markdown("""
Sube un **Excel (.xlsx)** o **CSV (.csv)** con la programación semanal.
La app normaliza los datos, aplica las reglas de horario y genera los archivos listos para descargar.
""")

uploaded = st.file_uploader("📂 Sube tu archivo", type=["xlsx","csv"])

ROMANCE_KW = ["amor","romance","enamor","bodas","novia","novio","corazon","corazón"]
TERROR_KW  = ["terror","miedo","susto","exorc","siniest","maldici","conjuro","it ","annabelle","la monja","chainsaw"]

def guess_genero(titulo):
    t = str(titulo).lower()
    if any(k in t for k in TERROR_KW): return "terror"
    if any(k in t for k in ROMANCE_KW): return "romántica"
    return "otro"

def normalize_excel(file):
    xls = pd.ExcelFile(file)
    sheet = next((s for s in xls.sheet_names if "cine" in s.lower()), xls.sheet_names[0])
    df_raw = pd.read_excel(xls, sheet_name=sheet)
    header_idx = None
    for i in range(min(30, len(df_raw))):
        if str(df_raw.iloc[i,0]).strip().lower() in ("película","pelicula"):
            header_idx = i; break
    if header_idx is None:
        raise ValueError("No se encontró encabezado con 'Película'.")
    headers = list(df_raw.iloc[header_idx].fillna("").astype(str))
    df = df_raw.iloc[header_idx+1:].copy()
    df.columns = headers
    ren = {"Película":"titulo","Duración":"duracion_min","Sala":"sala","Clasif":"clasificacion","Nota":"nota"}
    for k,v in ren.items():
        if k in df.columns: df = df.rename(columns={k:v})
    df = df[df["titulo"].notna()].copy()
    df["titulo"] = df["titulo"].astype(str).str.strip()
    def extract_funciones(nota):
        if not isinstance(nota,str): return []
        return [int(n) for n in re.findall(r"(\d+)\s*a", nota)]
    rows = []
    for _, r in df.iterrows():
        funcs = extract_funciones(r.get("nota","")) or [1]
        for fnum in funcs:
            rows.append({
                "sala": r.get("sala",""),
                "titulo": r.get("titulo",""),
                "genero": guess_genero(r.get("titulo","")),
                "duracion_min": int(r.get("duracion_min", 120)),
                "clasificacion": r.get("clasificacion",""),
                "funcion": fnum
            })
    return pd.DataFrame(rows)

def normalize_csv(file):
    df = pd.read_csv(file)
    if "genero" not in df.columns:
        df["genero"] = df["titulo"].apply(guess_genero)
    if "clasificacion" not in df.columns:
        df["clasificacion"] = ""
    if "funcion" not in df.columns:
        df["funcion"] = 1
    return df

if uploaded is not None:
    st.success("Archivo cargado correctamente ✅")
    try:
        if uploaded.name.lower().endswith(".xlsx"):
            df = normalize_excel(uploaded)
        else:
            df = normalize_csv(uploaded)
        st.dataframe(df.head(15), use_container_width=True)
        if st.button("🧮 Generar planificación"):
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
                df.to_csv(tmp.name, index=False)
                rows = planificar(tmp.name)
            df_plan = pd.DataFrame(rows)
            st.dataframe(df_plan, use_container_width=True)
            st.download_button("⬇️ Descargar CSV (;)", df_plan.to_csv(index=False, sep=";").encode("utf-8"), "planificacion.csv", "text/csv")
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
                df_plan.to_excel(w, index=False, sheet_name="General")
                for sala, sub in df_plan.groupby("sala"):
                    sub.to_excel(w, index=False, sheet_name=f"Sala_{sala}")
            st.download_button("⬇️ Descargar Excel (por sala)", buf.getvalue(), "planificacion.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        st.error(f"Ocurrió un error: {e}")
else:
    st.info("Sube tu archivo para comenzar.")