# app.py
import io, re, os, tempfile, csv
import pandas as pd
import streamlit as st
from fpdf import FPDF
from plan_cine import planificar  # motor

st.set_page_config(page_title="Planificador Cinépolis", page_icon="🎬", layout="wide")
st.title("🎬 Planificador automático de cartelera Cinépolis Maipú")

st.markdown("""
Sube un **Excel (.xlsx)** o **CSV (.csv)** con la programación semanal.
La app normaliza los datos, aplica las reglas y genera los archivos listos para descargar.
""")

uploaded = st.file_uploader("📂 Sube tu archivo", type=["xlsx","csv"])

ROMANCE_KW = ["amor","romance","enamor","bodas","novia","novio","corazon","corazón"]
TERROR_KW  = ["terror","miedo","susto","exorc","siniest","maldici","conjuro","it ","annabelle","la monja","chainsaw"]

def guess_genero(titulo):
    t = str(titulo).lower()
    if any(k in t for k in TERROR_KW): return "terror"
    if any(k in t for k in ROMANCE_KW): return "romántica"
    return "otro"

def normalize_excel(file) -> pd.DataFrame:
    xls = pd.ExcelFile(file)
    sheet = next((s for s in xls.sheet_names if "cine" in s.lower()), xls.sheet_names[0])
    df_raw = pd.read_excel(xls, sheet_name=sheet)

    # Ubicar encabezado "Película"
    header_idx = None
    for i in range(min(30, len(df_raw))):
        if str(df_raw.iloc[i,0]).strip().lower() in ("película","pelicula"):
            header_idx = i; break
    if header_idx is None:
        raise ValueError("No se encontró encabezado con 'Película'.")

    headers = list(df_raw.iloc[header_idx].fillna("").astype(str))
    df = df_raw.iloc[header_idx+1:].copy()
    df.columns = headers

    # Renombrar columnas típicas
    ren = {"Película":"titulo","Duración":"duracion_min","Sala":"sala","Clasif":"clasificacion","Nota":"nota"}
    for k,v in ren.items():
        if k in df.columns: df = df.rename(columns={k:v})

    df = df[df["titulo"].notna()].copy()
    df["titulo"] = df["titulo"].astype(str).str.strip()

    # Expandir funciones "1a, 2a ..."
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

def normalize_csv(file) -> pd.DataFrame:
    df = pd.read_csv(file)
    if "genero" not in df.columns:
        df["genero"] = df["titulo"].apply(guess_genero)
    if "clasificacion" not in df.columns:
        df["clasificacion"] = ""
    if "funcion" not in df.columns:
        df["funcion"] = 1
    # Asegurar columnas y tipos
    cols = ["sala","titulo","genero","duracion_min","clasificacion","funcion"]
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c != "duracion_min" else 120
    df["duracion_min"] = df["duracion_min"].astype(int)
    return df[cols].copy()

def dataframe_to_pdf(df: pd.DataFrame, title: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, txt=title, ln=True, align="C")
    pdf.ln(3)
    pdf.set_font("Arial", size=10)

    # Encabezados
    headers = list(df.columns)
    header_line = " | ".join(headers)
    pdf.cell(0, 8, txt=header_line, ln=True)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    # Filas
    for _, row in df.iterrows():
        txt = " | ".join(str(row[c]) for c in headers)
        pdf.cell(0, 7, txt=txt, ln=True)

    out = io.BytesIO()
    pdf.output(out)
    return out.getvalue()

if uploaded is not None:
    st.success("Archivo cargado correctamente ✅")
    try:
        if uploaded.name.lower().endswith(".xlsx"):
            df_norm = normalize_excel(uploaded)
        else:
            df_norm = normalize_csv(uploaded)

        st.subheader("Vista previa del archivo normalizado")
        st.dataframe(df_norm.head(50), use_container_width=True)

        if st.button("🧮 Generar planificación"):
            # Guardamos el normalizado a un CSV temporal (entrada del motor)
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp_in:
                df_norm.to_csv(tmp_in.name, index=False)
                tmp_in_path = tmp_in.name

            # Archivo temporal de salida por si el motor escribe CSV
            tmp_out = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
            tmp_out_path = tmp_out.name
            tmp_out.close()

            df_plan: pd.DataFrame | None = None

            # 1) Intento A: planificar(path_in) que devuelve rows
            try:
                rows_or_none = planificar(tmp_in_path)   # algunos motores devuelven rows
                if rows_or_none is not None:
                    df_plan = pd.DataFrame(rows_or_none)
                # Si devolvió None, intentaremos la ruta de salida
            except TypeError:
                # 2) Intento B: planificar(path_in, path_out) que escribe CSV
                planificar(tmp_in_path, tmp_out_path)

            # Si aún no tenemos df_plan, intentamos leer el CSV de salida
            if df_plan is None:
                if os.path.exists(tmp_out_path) and os.path.getsize(tmp_out_path) > 0:
                    try:
                        df_plan = pd.read_csv(tmp_out_path)
                    except Exception:
                        # como respaldo, parsear con ; si hiciera falta
                        df_plan = pd.read_csv(tmp_out_path, sep=";")

            if df_plan is None or df_plan.empty:
                st.error("No se pudo generar la planificación. Revisa el archivo de entrada o el motor.")
            else:
                st.subheader("Planificación generada")
                st.dataframe(df_plan, use_container_width=True)

                # Descarga CSV con separador ; (amigable para Excel ES)
                csv_bytes = df_plan.to_csv(index=False, sep=";").encode("utf-8")
                st.download_button(
                    "⬇️ Descargar planificación (CSV ;)",
                    data=csv_bytes,
                    file_name="planificacion_cinepolis_maipu.csv",
                    mime="text/csv",
                )

                # Excel por sala
                xlsx_buf = io.BytesIO()
                with pd.ExcelWriter(xlsx_buf, engine="xlsxwriter") as writer:
                    df_plan.to_excel(writer, index=False, sheet_name="General")
                    for sala, sub in df_plan.groupby("sala"):
                        sub.to_excel(writer, index=False, sheet_name=f"Sala_{sala}")
                st.download_button(
                    "⬇️ Descargar planificación (Excel por sala)",
                    data=xlsx_buf.getvalue(),
                    file_name="planificacion_cinepolis_maipu.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                # PDF simple (tabla en texto)
                pdf_bytes = dataframe_to_pdf(df_plan, "Planificación Cinépolis Maipú")
                st.download_button(
                    "📄 Descargar PDF",
                    data=pdf_bytes,
                    file_name="planificacion_cinepolis_maipu.pdf",
                    mime="application/pdf",
                )

    except Exception as e:
        st.error(f"Ocurrió un error: {e}")
else:
    st.info("Sube tu archivo para comenzar.")
