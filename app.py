import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber
import streamlit as st

st.set_page_config(page_title="Importador ONVIO", page_icon="📥", layout="wide")

# ==========================
# Configuración base
# ==========================
PLAN_DEFAULTS = {
    "banco_macro": "1.1.1/02/02",
    "tarjetas_a_depositar": "1.1.1/01/07",
    "ret_iibb": "1.1.4/01/04",
    "impuesto_cheque": "4.2.1/07/06",
    "comisiones": "4.2.1/04/14",
    "sueldos_gasto": "4.2.1/03/01",
    "cargas_sociales_gasto": "4.2.1/03/02",
    "seguro_gasto": "4.2.1/03/17",
    "sueldos_a_pagar": "2.1.2/01/00",
    "cargas_sociales_a_pagar": "2.1.2/02/00",
    "art_a_pagar": "2.1.2/02/02",
}

IVA_MAP = {
    "RI": "Responsable Inscripto",
    "CF": "Consumidor Final",
    "RM": "Responsable Monotributo",
    "EX": "Exento",
    "MT": "Responsable Monotributo",
}

COMP_MAP = {
    "FA": "Factura",
    "FB": "Factura",
    "FA A": "Factura",
    "FA B": "Factura",
    "NC": "Nota de Crédito",
    "NC A": "Nota de Crédito",
    "NC B": "Nota de Crédito",
    "ND": "Nota de Débito",
    "ND A": "Nota de Débito",
    "ND B": "Nota de Débito",
}

PRE002_COLUMNS = [
    "Fecha de Emisión",
    "Código de Cliente",
    "Razón social del Cliente",
    "Tipo de Comprobante",
    "Letra",
    "Punto de Venta",
    "Número",
    "Número de Documento del Cliente",
    "Situación de IVA del Cliente",
    "Importe Neto",
    "Impuestos Internos / No Gravado",
    "IVA Inscripto",
    "IVA No Inscripto",
    "IVA Exento",
    "Importe Total del Comprobante",
]

ASIENTO_COLUMNS = [
    "Número de asiento",
    "Número de Pase",
    "Fecha",
    "Concepto",
    "Código de cuenta",
    "Importe en moneda local",
    "Importe en moneda ext.present.",
    "Leyenda",
    "Código de centro de costos",
    "Porcentaje de distribución",
    "Imp.mon.local dist.C.Costos",
    "Imp.mon.present.dist.C.Costos",
]


@dataclass
class ParsedPDF:
    text: str
    pages: int


# ==========================
# Utilidades
# ==========================
def money_to_float(value: str) -> float:
    value = str(value).strip().replace(".", "").replace(",", ".")
    value = re.sub(r"[^0-9\.-]", "", value)
    return float(value) if value not in {"", ".", "-"} else 0.0


def norm_doc(value) -> str:
    if pd.isna(value):
        return ""
    value = str(value)
    return re.sub(r"\D", "", value)


def parse_pdf(uploaded_file) -> ParsedPDF:
    text_parts = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return ParsedPDF(text="\n".join(text_parts), pages=len(text_parts))


def detect_type(filename: str, df: Optional[pd.DataFrame] = None, pdf_text: str = "") -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        if "931" in pdf_text or "declaración en linea formulario f.931" in pdf_text.lower() or "seguridad social" in pdf_text.lower():
            return "F931"
        if "detalle de movimiento" in pdf_text.lower() or "banco macro" in pdf_text.lower():
            return "BANCO"
    if df is not None:
        cols = [str(c).upper().strip() for c in df.columns]
        if {"FECHA", "TIPO_COMPR", "CLIENTE", "CUIT", "IMPORTE_TO"}.issubset(set(cols)):
            return "VENTAS_PRE002"
    return "DESCONOCIDO"


def split_numero(value: str) -> Tuple[str, str]:
    if pd.isna(value):
        return "", ""
    value = str(value).strip()
    m = re.match(r"(\d{1,5})-(\d{1,8})", value)
    if not m:
        return "", value
    return m.group(1).zfill(5), m.group(2).zfill(8)


def map_tipo_comprobante(row: pd.Series) -> str:
    raw = str(row.get("TIPO_COMPR", "")).strip().upper()
    return COMP_MAP.get(raw, raw)


def map_letra(row: pd.Series) -> str:
    tipo_fact = str(row.get("TIPO_FACTU", "")).strip().upper()
    if tipo_fact:
        return tipo_fact
    raw = str(row.get("TIPO_COMPR", "")).strip().upper()
    m = re.search(r"\b([ABCEM])$", raw)
    return m.group(1) if m else ""


def to_pre002(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(columns=PRE002_COLUMNS)
    work = df.copy()
    work.columns = [str(c).strip().upper() for c in work.columns]

    pv_num = work.get("NUMERO", pd.Series(dtype=str)).apply(split_numero)
    out["Fecha de Emisión"] = pd.to_datetime(work.get("FECHA"), errors="coerce").dt.strftime("%d/%m/%Y")
    out["Código de Cliente"] = work.get("ID_DESTINO", "")
    out["Razón social del Cliente"] = work.get("CLIENTE", "")
    out["Tipo de Comprobante"] = work.apply(map_tipo_comprobante, axis=1)
    out["Letra"] = work.apply(map_letra, axis=1)
    out["Punto de Venta"] = pv_num.apply(lambda x: x[0])
    out["Número"] = pv_num.apply(lambda x: x[1])
    out["Número de Documento del Cliente"] = work.get("CUIT", "").apply(norm_doc)
    out["Situación de IVA del Cliente"] = work.get("CATEGORIA_", "").astype(str).str.upper().map(IVA_MAP).fillna(work.get("CATEGORIA_", ""))
    out["Importe Neto"] = pd.to_numeric(work.get("IMPORTE_NE", 0), errors="coerce").fillna(0).round(2)
    internos = pd.to_numeric(work.get("IMP_INTERN", 0), errors="coerce").fillna(0)
    no_grav = pd.to_numeric(work.get("NO_GRABADO", 0), errors="coerce").fillna(0)
    out["Impuestos Internos / No Gravado"] = (internos + no_grav).round(2)
    out["IVA Inscripto"] = pd.to_numeric(work.get("IMPORTE_IV", 0), errors="coerce").fillna(0).round(2)
    out["IVA No Inscripto"] = 0.0
    out["IVA Exento"] = pd.to_numeric(work.get("NETO_NO_GR", 0), errors="coerce").fillna(0).round(2)
    out["Importe Total del Comprobante"] = pd.to_numeric(work.get("IMPORTE_TO", 0), errors="coerce").fillna(0).round(2)
    return out


def parse_f931_values(text: str) -> Dict[str, float]:
    patterns = {
        "remuneracion": [r"Suma de Rem\. 1:\s*([\d\.,]+)", r"Suma de Rem\. 9:\s*([\d\.,]+)"],
        "aportes_ss": [r"Aportes S\.S\. a pagar\s*([\d\.,]+)", r"301\s*-\s*Aportes de Seguridad Social\s*([\d\.,]+)"],
        "contrib_ss": [r"Contribuciones S\.S\. a pagar\s*([\d\.,]+)", r"351\s*-\s*Contribuciones de Seguridad Social\s*([\d\.,]+)"],
        "obra_social": [r"Contribuciones O\.S\. a pagar\s*([\d\.,]+)", r"352\s*-\s*Contribuciones de Obra Social\s*([\d\.,]+)"],
        "art": [r"L\.R\.T\. total a pagar\s*([\d\.,]+)", r"312\s*-\s*L\.R\.T\.\s*([\d\.,]+)"],
        "seguro": [r"S\.C\.V\.O\. a pagar\s*([\d\.,]+)", r"028\s*-\s*Seguro Colectivo de Vida Obligatorio\s*([\d\.,]+)"],
    }
    result = {k: 0.0 for k in patterns}
    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                result[key] = money_to_float(m.group(1))
                break
    return result


def f931_to_asiento(values: Dict[str, float], fecha: str, cuentas: Dict[str, str]) -> pd.DataFrame:
    asiento = []
    nro = 1
    concepto = f"Devengamiento F931 {fecha[3:10]}"

    def add(cuenta: str, importe: float, leyenda: str):
        nonlocal nro
        if round(float(importe or 0), 2) == 0:
            return
        asiento.append([
            1,
            nro,
            fecha,
            concepto,
            cuenta,
            round(float(importe), 2),
            "",
            leyenda,
            "",
            "",
            "",
            "",
        ])
        nro += 1

    # Debe
    add(cuentas["sueldos_gasto"], values.get("remuneracion", 0), "Sueldos")
    add(cuentas["cargas_sociales_gasto"], values.get("contrib_ss", 0) + values.get("obra_social", 0) + values.get("art", 0), "Cargas sociales")
    add(cuentas["seguro_gasto"], values.get("seguro", 0), "Seguro de vida")

    # Haber
    add(cuentas["sueldos_a_pagar"], values.get("remuneracion", 0) - values.get("aportes_ss", 0), "Sueldos netos a pagar")
    add(cuentas["cargas_sociales_a_pagar"], values.get("aportes_ss", 0) + values.get("contrib_ss", 0) + values.get("obra_social", 0), "AFIP / cargas sociales a pagar")
    add(cuentas["art_a_pagar"], values.get("art", 0), "ART a pagar")
    add(cuentas["cargas_sociales_a_pagar"], values.get("seguro", 0), "Seguro de vida a pagar")

    return pd.DataFrame(asiento, columns=ASIENTO_COLUMNS)


def parse_bank_lines(text: str) -> pd.DataFrame:
    records = []
    current_date = None
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        if line.startswith("SALDO ") or line.startswith("TOTAL ") or line.startswith("DETALLE DE MOVIMIENTO"):
            continue
        m = re.match(r"^(\d{2}/\d{2}/\d{2})\s+(.+?)\s+(-?[\d\.,]+)\s*$", line)
        if not m:
            continue
        date = m.group(1)
        rest = m.group(2)
        saldo = money_to_float(m.group(3))

        # buscar los 2 importes previos al saldo (débito / crédito) o solo 1
        nums = list(re.finditer(r"(-?[\d\.,]+)", rest))
        deb = cred = 0.0
        desc = rest
        if len(nums) >= 2:
            last = nums[-1]
            pen = nums[-2]
            candidate1 = money_to_float(pen.group(1))
            candidate2 = money_to_float(last.group(1))
            desc = rest[: pen.start()].strip()
            # Heurística Banco Macro: línea con dos números al final suele ser débito y saldo o crédito y saldo.
            # Si el penúltimo es 0, tomar el último como débito.
            if candidate1 == 0:
                deb = candidate2
            else:
                # Resolver por texto: pagos/ingresos sin texto N/D
                if any(tag in desc.upper() for tag in ["PAGO", "ING TRANSF", "TRANSF:", "N/C "]):
                    cred = candidate2
                else:
                    deb = candidate2
        elif len(nums) == 1:
            val = money_to_float(nums[0].group(1))
            desc = rest[: nums[0].start()].strip()
            if any(tag in desc.upper() for tag in ["PAGO", "ING TRANSF", "TRANSF:", "N/C "]):
                cred = val
            else:
                deb = val

        records.append({
            "Fecha": date,
            "Descripción": desc,
            "Débitos": round(deb, 2),
            "Créditos": round(cred, 2),
            "Saldo": round(saldo, 2),
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df[(df["Débitos"] != 0) | (df["Créditos"] != 0)].copy()
    return df


def classify_bank(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    desc = out["Descripción"].str.upper().fillna("")
    out["Clase"] = "A revisar"
    out.loc[desc.str.contains("PRISMA"), "Clase"] = "Cobranza tarjetas"
    out.loc[desc.str.contains("RET IIBB"), "Clase"] = "Retención IIBB"
    out.loc[desc.str.contains("DBCR 25413|IMPDBCR"), "Clase"] = "Impuesto al cheque"
    out.loc[desc.str.contains("COMISION"), "Clase"] = "Comisión bancaria"
    out.loc[desc.str.contains("ING TRANSF|TRANSF:") & (out["Créditos"] > 0), "Clase"] = "Transferencia recibida"
    out.loc[desc.str.contains("TRF MO CCDO|DB TRANSF|TRANSF\. MACRONLINE") & (out["Débitos"] > 0), "Clase"] = "Transferencia emitida"
    out.loc[desc.str.contains("DEBITO FISCAL IVA"), "Clase"] = "IVA bancario"
    return out


def bank_to_asiento(df: pd.DataFrame, fecha: str, cuentas: Dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=ASIENTO_COLUMNS)
    rows = []
    pase = 1
    concepto = f"Resumen Banco Macro {fecha[3:10]}"
    resumen = df.groupby("Clase", dropna=False).agg({"Débitos": "sum", "Créditos": "sum"}).reset_index()

    for _, r in resumen.iterrows():
        clase = r["Clase"]
        deb = round(float(r["Débitos"] or 0), 2)
        cred = round(float(r["Créditos"] or 0), 2)
        contrap = ""
        ley = clase
        if clase == "Cobranza tarjetas":
            contrap = cuentas["tarjetas_a_depositar"]
            # Debe banco / Haber tarjetas a depositar
            rows.append([1, pase, fecha, concepto, cuentas["banco_macro"], cred, "", ley, "", "", "", ""]); pase += 1
            rows.append([1, pase, fecha, concepto, contrap, -cred, "", ley, "", "", "", ""]); pase += 1
        elif clase == "Retención IIBB":
            contrap = cuentas["ret_iibb"]
            rows.append([1, pase, fecha, concepto, contrap, deb, "", ley, "", "", "", ""]); pase += 1
            rows.append([1, pase, fecha, concepto, cuentas["banco_macro"], -deb, "", ley, "", "", "", ""]); pase += 1
        elif clase == "Impuesto al cheque":
            contrap = cuentas["impuesto_cheque"]
            rows.append([1, pase, fecha, concepto, contrap, deb, "", ley, "", "", "", ""]); pase += 1
            rows.append([1, pase, fecha, concepto, cuentas["banco_macro"], -deb, "", ley, "", "", "", ""]); pase += 1
        elif clase == "Comisión bancaria":
            contrap = cuentas["comisiones"]
            rows.append([1, pase, fecha, concepto, contrap, deb, "", ley, "", "", "", ""]); pase += 1
            rows.append([1, pase, fecha, concepto, cuentas["banco_macro"], -deb, "", ley, "", "", "", ""]); pase += 1

    out = pd.DataFrame(rows, columns=ASIENTO_COLUMNS)
    if not out.empty:
        out["Importe en moneda local"] = out["Importe en moneda local"].round(2)
    return out


def df_to_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            ws = writer.book[name[:31]]
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        max_length = max(max_length, len(str(cell.value)))
                    except Exception:
                        pass
                ws.column_dimensions[column].width = min(max(max_length + 2, 12), 40)
    return bio.getvalue()


# ==========================
# UI
# ==========================
st.title("📥 Importador ONVIO – Prototipo web")
st.caption("Versión MVP para Ortega & Asociados: Ventas PRE002, F931 a Asiento y Banco Macro a clasificación/asiento.")

with st.sidebar:
    st.subheader("Configuración base")
    cliente = st.text_input("Cliente", value="HAHN SAS")
    fecha_asiento = st.text_input("Fecha asiento / período", value="31/01/2026")
    st.markdown("**Cuentas por defecto**")
    cuentas = {}
    for k, v in PLAN_DEFAULTS.items():
        cuentas[k] = st.text_input(k.replace("_", " ").title(), value=v)

uploaded = st.file_uploader("Subí Excel, CSV o PDF", type=["xlsx", "xls", "csv", "pdf"])
modo = st.selectbox("Proceso", ["Automático", "Ventas PRE002", "F931 a Asiento", "Banco Macro"])

if uploaded:
    df = None
    pdf = None
    ext = Path(uploaded.name).suffix.lower()
    try:
        if ext in {".xlsx", ".xls", ".csv"}:
            if ext == ".csv":
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)
        elif ext == ".pdf":
            pdf = parse_pdf(uploaded)
    except Exception as e:
        st.error(f"No pude leer el archivo: {e}")
        st.stop()

    detected = modo
    if modo == "Automático":
        detected = detect_type(uploaded.name, df=df, pdf_text=pdf.text if pdf else "")

    st.success(f"Tipo detectado / elegido: {detected}")

    if detected == "VENTAS_PRE002" or detected == "Ventas PRE002":
        if df is None:
            st.error("Para ventas necesitás subir un Excel o CSV.")
        else:
            out = to_pre002(df)
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Filas convertidas", len(out))
            with c2:
                st.metric("Importe total", f"$ {out['Importe Total del Comprobante'].sum():,.2f}")
            st.dataframe(out.head(50), use_container_width=True)
            excel = df_to_excel_bytes({"PRE002_VENTAS": out})
            st.download_button("Descargar Excel ONVIO PRE002", excel, file_name="PRE002_ventas_onvio.xlsx")

    elif detected == "F931" or detected == "F931 a Asiento":
        st.info("Si el PDF no trae texto legible, podés completar manualmente los importes abajo y el sistema igual genera el asiento.")
        parsed = parse_f931_values(pdf.text if pdf else "") if pdf else {}
        cols = st.columns(3)
        remuneracion = cols[0].number_input("Remuneración base", value=float(parsed.get("remuneracion", 0.0)), step=1000.0)
        aportes_ss = cols[1].number_input("Aportes S.S.", value=float(parsed.get("aportes_ss", 0.0)), step=1000.0)
        contrib_ss = cols[2].number_input("Contribuciones S.S.", value=float(parsed.get("contrib_ss", 0.0)), step=1000.0)
        cols2 = st.columns(3)
        obra_social = cols2[0].number_input("Obra Social", value=float(parsed.get("obra_social", 0.0)), step=1000.0)
        art = cols2[1].number_input("ART", value=float(parsed.get("art", 0.0)), step=1000.0)
        seguro = cols2[2].number_input("Seguro vida", value=float(parsed.get("seguro", 0.0)), step=100.0)

        values = {
            "remuneracion": remuneracion,
            "aportes_ss": aportes_ss,
            "contrib_ss": contrib_ss,
            "obra_social": obra_social,
            "art": art,
            "seguro": seguro,
        }
        asiento = f931_to_asiento(values, fecha_asiento, cuentas)
        debe = asiento[asiento["Importe en moneda local"] > 0]["Importe en moneda local"].sum()
        haber = abs(asiento[asiento["Importe en moneda local"] < 0]["Importe en moneda local"].sum())
        c1, c2 = st.columns(2)
        c1.metric("Debe", f"$ {debe:,.2f}")
        c2.metric("Haber", f"$ {haber:,.2f}")
        st.dataframe(asiento, use_container_width=True)
        excel = df_to_excel_bytes({"ASIENTO_F931": asiento})
        st.download_button("Descargar Asiento ONVIO", excel, file_name="asiento_f931_onvio.xlsx")

    elif detected == "BANCO" or detected == "Banco Macro":
        if not pdf:
            st.error("Para Banco Macro necesitás subir el PDF del extracto.")
        else:
            moves = parse_bank_lines(pdf.text)
            classified = classify_bank(moves)
            asiento = bank_to_asiento(classified, fecha_asiento, cuentas)
            c1, c2, c3 = st.columns(3)
            c1.metric("Movimientos detectados", len(classified))
            c2.metric("Créditos", f"$ {classified['Créditos'].sum():,.2f}" if not classified.empty else "$ 0.00")
            c3.metric("Débitos", f"$ {classified['Débitos'].sum():,.2f}" if not classified.empty else "$ 0.00")
            tab1, tab2 = st.tabs(["Movimientos clasificados", "Asiento resumido"])
            with tab1:
                st.dataframe(classified, use_container_width=True)
            with tab2:
                st.dataframe(asiento, use_container_width=True)
            excel = df_to_excel_bytes({"MOVIMIENTOS": classified, "ASIENTO": asiento})
            st.download_button("Descargar Banco clasificado + asiento", excel, file_name="banco_macro_onvio.xlsx")

    else:
        st.warning("No pude identificar este archivo todavía. En este MVP solo están activos Ventas PRE002, F931 y Banco Macro.")
