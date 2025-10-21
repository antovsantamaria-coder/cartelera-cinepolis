# app.py
import io, re, os, csv, tempfile
import pandas as pd
import streamlit as st
from fpdf import FPDF
from plan_cine import planificar  # motor

st.set_page_config(page_title="Planificador Cinépolis", page_icon="🎬", layout="wide")
st.title("🎬 Planificador automático de cartelera Cinépolis Maipú")

st.markdown("""
Sube un **Excel (.xlsx)**, **CSV (.csv)** o **PDF (.pdf)** con la programación semanal.
La app normaliza los datos, aplica las reglas y genera los archivos listos para descargar.
""")

# ⬇️ ahora aceptamos PDF también
uploaded = st.file_uploader("📂 Sube tu archivo", type=["xlsx","csv","pdf"])

ROMANCE_KW = ["amor","romance","enamor","bodas","novia","novio","corazon","corazón"]
TERROR_KW  = ["terror","miedo","susto","exorc","siniest","maldici","conjuro","it ","annabelle","la monja","chainsaw"]

def guess_genero(titulo):
    t = str(titulo).lower()
    if any(k in t for k in TERROR_KW): return "terror"
    if any(k in t for k in ROMANCE_KW): return "romántica"
    return "otro"

def _expand_rows_from_df(df_base: pd.DataFrame) -> pd.DataFrame:
    # Renombrar si existen columnas típicas
    ren = {"Película":"titulo","Duración":"duracion_min","Sala":"sala","Clasif":"clasificacion","Nota":"nota"}
    for k,v in ren.items():
        if k in df_base.columns: df_base = df_base.rename(columns={k:v})

    # columnas mínimas
    for c in ["titulo","sala","duracion_min","clasificacion","nota"]:
        if c not in df_base.columns: df_base[c] = ""

    df_base = df_base[df_base["titulo"].notna()].copy()
    df_base["titulo"] = df_base["titulo"].astype(str).str.strip()

    def extract_funciones(nota):
        if not isinstance(nota,str): return []
        return [int(n) for n in re.findall(r"(\d+)\s*a", nota)]

    rows = []
    for _, r in df_base.iterrows():
        funcs = extract_funciones(r.get("nota","")) or [1]
        for fnum in funcs:
            rows.append({
                "sala": str(r.get("sala","")),
                "titulo": str(r.get("titulo","")),
                "genero": guess_genero(r.get("titulo","")),
                "duracion_min": int(pd.to_numeric(r.get("duracion_min", 120), errors="coerce") or 120),
                "clasificacion": str(r.get("clasificacion","")),
                "funcion": int(fnum)
            })
    return pd.DataFrame(rows)

def normalize_excel(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = next((s for s in xls.sheet_names if "cine" in s.lower()), xls.sheet_names[0])
    df_raw = pd.read_excel(xls, sheet_name=sheet)

    # ubicar encabezado "Película"
    header_idx = None
    for i in range(min(30, len(df_raw))):
        if str(df_raw.iloc[i,0]).strip().lower() in ("película","pelicula"):
            header_idx = i; break
    if header_idx is None:
        # sin encabezado claro: usa tal cual
        df = df_raw.copy()
    else:
        headers = list(df_raw.iloc[header_idx].fillna("").astype(str))
        df = df_raw.iloc[header_idx+1:].copy()
        df.columns = headers
    return _expand_rows_from_df(df)

def normalize_csv(file) -> pd.DataFrame:
    df = pd.read_csv(file)
    # si no tiene columnas estándar, intentamos mapear
    if "titulo" not in df.columns and "Película" in df.columns:
        df = df.rename(columns={"Película":"titulo"})
    if "duracion_min" not in df.columns and "Duración" in df.columns:
        df = df.rename(columns={"Duración":"duracion_min"})
    if "sala" not in df.columns and "Sala" in df.columns:
        df = df.rename(columns={"Sala":"sala"})
    # completar faltantes
    if "genero" not in df.columns:
        df["genero"] = df["titulo"].apply(guess_genero)
    if "clasificacion" not in df.columns:
        df["clasificacion"] = ""
    if "funcion" not in df.columns:
        df["funcion"] = 1
    if "duracion_min" not in df.columns:
        df["duracion_min"] = 120
    df["duracion_min"] = pd.to_numeric(df["duracion_min"], errors="coerce").fillna(120).astype(int)
    cols = ["sala","titulo","genero","duracion_min","clasificacion","funcion"]
    for c in cols:
        if c not in df.columns: df[c] = "" if c != "duracion_min" else 120
    return df[cols].copy()

def normalize_pdf(file) -> pd.DataFrame:
    """Extrae tablas desde PDF (cuando el PDF tiene texto seleccionable).
       Si el PDF es escaneado, esto no funcionará bien sin OCR."""
    import pdfplumber
    tables = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            # intenta leer todas las tablas de la página
            for table in page.extract_tables() or []:
                if not table: continue
                df = pd.DataFrame(table)
                # intentar detectar fila de encabezado con 'Película'/'Pelicula'
                header_row = None
                for i in range(min(5, len(df))):
                    row_str = " ".join(map(str, df.iloc[i].tolist())).lower()
                    if "película" in row_str or "pelicula" in row_str:
                        header_row = i; break
                if header_row is not None:
                    headers = df.iloc[header_row].astype(str).tolist()
                    df2 = df.iloc[header_row+1:].copy()
                    df2.columns = headers
                    tables.append(df2)
                else:
                    tables.append(df)  # mejor que nada
    if not tables:
        raise ValueError("No se detectaron tablas en el PDF. Si es un escaneo, conviértelo a CSV/XLSX.")
    df_all = pd.concat(tables, ignore_index=True)
    return _expand_rows_from_df(df_all)

def dataframe_to_pdf(df: pd.DataFrame, title: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, txt=title, ln=True, align="C")
    pdf.ln(3)
    pdf.set_font("Arial", size=10)

    headers = list(df.columns)
    pdf.cell(0, 8, txt=" | ".join(headers), ln=True)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    for _, row in df.iterrows():
        pdf.cell(0, 7, txt=" | ".join(str(row[c]) for c in headers), ln=True)

    out = io.BytesIO()
    pdf.output(out)
    return out.getvalue()

if uploaded is not None:
    st.success("Archivo cargado correctamente ✅")
    try:
        ext = uploaded.name.lower().split(".")[-1]
        if ext == "xlsx":
            df_norm = normalize_excel(uploaded)
        elif ext == "csv":
            df_norm = normalize_csv(uploaded)
        else:  # pdf
            df_norm = normalize_pdf(uploaded)

        st.subheader("Vista previa del archivo normalizado")
        st.dataframe(df_norm.head(50), use_container_width=True)

        if st.button("🧮 Generar planificación"):
            # Guardamos normalizado a CSV temporal (entrada del motor)
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp_in:
                df_norm.to_csv(tmp_in.name, index=False)
                tmp_in_path = tmp_in.name

            # Archivo temporal de salida por si el motor escribe CSV
            tmp_out = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
            tmp_out_path = tmp_out.name
            tmp_out.close()

            df_plan: pd.DataFrame | None = None

            # Intento A: planificar(path_in) que devuelve rows
            try:
                rows_or_none = planificar(tmp_in_path)
                if rows_or_none is not None:
                    df_plan = pd.DataFrame(rows_or_none)
            except TypeError:
                # Intento B: planificar(path_in, path_out)
                planificar(tmp_in_path, tmp_out_path)

            # Si no hay df_plan, leer CSV que pudo escribir el motor
            if df_plan is None:
                if os.path.exists(tmp_out_path) and os.path.getsize(tmp_out_path) > 0:
                    try:
                        df_plan = pd.read_csv(tmp_out_path)
                    except Exception:
                        df_plan = pd.read_csv(tmp_out_path, sep=";")

            if df_plan is None or df_plan.empty:
                st.error("No se pudo generar la planificación. Revisa el archivo de entrada o el motor.")
            else:
                st.subheader("Planificación generada")
                st.dataframe(df_plan, use_container_width=True)

                # CSV con ; (Excel ES)
                st.download_button(
                    "⬇️ Descargar planificación (CSV ;)",
                    data=df_plan.to_csv(index=False, sep=";").encode("utf-8"),
                    file_name="planificacion_cinepolis_maipu.csv",
                    mime="text/csv",
                )

                # Excel por sala
                xlsx_buf = io.BytesIO()
                with pd.ExcelWriter(xlsx_buf, engine="xlsxwriter") as w:
                    df_plan.to_excel(w, index=False, sheet_name="General")
                    for sala, sub in df_plan.groupby("sala"):
                        sub.to_excel(w, index=False, sheet_name=f"Sala_{sala}")
                st.download_button(
                    "⬇️ Descargar planificación (Excel por sala)",
                    data=xlsx_buf.getvalue(),
                    file_name="planificacion_cinepolis_maipu.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                # PDF simple
                st.download_button(
                    "📄 Descargar planificación (PDF)",
                    data=dataframe_to_pdf(df_plan, "Planificación Cinépolis Maipú"),
                    file_name="planificacion_cinepolis_maipu.pdf",
                    mime="application/pdf",
                )

    except Exception as e:
        st.error(f"Ocurrió un error: {e}")
else:
    st.info("Sube tu archivo para comenzar.")

