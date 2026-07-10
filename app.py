import io
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================
st.set_page_config(
    page_title="Control de Boletines",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 Control de Boletines")
st.markdown("---")


# =============================================================================
# CONEXIÓN A GOOGLE SHEETS
# =============================================================================
# Reemplaza únicamente esta URL por el enlace real de tu Google Sheets.
# La hoja debe permitir lectura mediante enlace.
URL_DRIVE = "PEGA_AQUI_EL_ENLACE_DE_TU_GOOGLE_SHEETS"

# Nombre exacto de la única pestaña consolidada.
NOMBRE_PESTANA = "Control de boletines"


@st.cache_data(ttl=300, show_spinner="Actualizando información desde Google Sheets...")
def cargar_datos_pestana(url: str, nombre_pestana: str) -> pd.DataFrame | None:
    """Descarga una pestaña de Google Sheets en formato CSV."""
    try:
        if not url or "PEGA_AQUI" in url:
            st.error("⚠️ Debes reemplazar URL_DRIVE por el enlace real de Google Sheets.")
            return None

        if "/edit" in url:
            url_base = url.split("/edit")[0]
        else:
            url_base = url.rstrip("/")

        csv_url = (
            f"{url_base}/gviz/tq?"
            f"tqx=out:csv&sheet={quote(nombre_pestana)}"
        )

        respuesta = requests.get(csv_url, timeout=20)
        respuesta.raise_for_status()

        df = pd.read_csv(io.StringIO(respuesta.text))
        df.columns = df.columns.astype(str).str.strip()

        return df

    except requests.exceptions.Timeout:
        st.error("⏱️ Google Sheets no respondió dentro del tiempo esperado.")
        return None

    except requests.exceptions.HTTPError as e:
        st.error(
            "❌ Google Sheets respondió con un error HTTP. "
            "Verifica que el archivo esté compartido para lectura."
        )
        st.caption(str(e))
        return None

    except requests.exceptions.RequestException as e:
        st.error("❌ No fue posible conectarse con Google Sheets.")
        st.caption(str(e))
        return None

    except Exception as e:
        st.error(
            f"❌ Error al cargar la pestaña '{nombre_pestana}'. "
            "Verifica el nombre de la hoja y sus encabezados."
        )
        st.caption(str(e))
        return None


# =============================================================================
# UTILIDADES
# =============================================================================
def normalizar_texto(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip()


def ordenar_meses(meses_disponibles: list[str]) -> list[str]:
    orden = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]

    mapa = {mes.upper(): mes for mes in orden}
    unicos = []

    for valor in meses_disponibles:
        texto = str(valor).strip()
        if texto and texto.lower() != "nan":
            nombre = mapa.get(texto.upper(), texto)
            if nombre not in unicos:
                unicos.append(nombre)

    return sorted(
        unicos,
        key=lambda x: orden.index(x) if x in orden else len(orden),
    )


def lista_filtro(serie: pd.Series) -> list:
    valores = (
        serie.dropna()
        .astype(str)
        .str.strip()
    )
    valores = valores[valores != ""]
    return ["TODOS"] + sorted(valores.unique().tolist())


def validar_columnas(df: pd.DataFrame, columnas: list[str]) -> list[str]:
    return [col for col in columnas if col not in df.columns]


# =============================================================================
# CARGA GENERAL DE LA HOJA CONSOLIDADA
# =============================================================================
df_total = cargar_datos_pestana(URL_DRIVE, NOMBRE_PESTANA)

if df_total is None:
    st.stop()

if df_total.empty:
    st.warning(f"⚠️ La pestaña '{NOMBRE_PESTANA}' está vacía.")
    st.stop()


# =============================================================================
# COLUMNAS EXACTAS DEL ARCHIVO
# =============================================================================
COL_MES = "MES"
COL_GRUPO = "GRUPO"
COL_AREA = "AREA COMERCIAL"
COL_CLIENTE = "CLIENTE INSTITUCIONAL"
COL_RECURRENCIA = "RECURRENCIA DE BOLETIN"
COL_EJECUTIVO = "Ejecutivo Comercial / Coordinador"
COL_GERENTE = "Gerente Comercial / Director"
COL_ENTREGA = "FECHA DE ENTREGA DE BOLETIN"
COL_ODOO = "FECHA DE CARGA ODOO"
COL_OBSERVACION = "OBSERVACION RETRASO"
COL_DIAS_MAX = "DIAS MAXIMAS DEL MES PARA ENTREGA DE BOLETIN"

columnas_obligatorias = [
    COL_MES,
    COL_GRUPO,
    COL_AREA,
    COL_CLIENTE,
    COL_RECURRENCIA,
    COL_EJECUTIVO,
    COL_ENTREGA,
    COL_ODOO,
]

faltantes = validar_columnas(df_total, columnas_obligatorias)

if faltantes:
    st.error("❌ Faltan columnas obligatorias en Google Sheets:")
    st.code("\n".join(faltantes))
    st.stop()


# =============================================================================
# FILTROS
# =============================================================================
st.sidebar.header("📅 Calendario Operativo")

meses_disponibles = ordenar_meses(df_total[COL_MES].dropna().tolist())

if not meses_disponibles:
    st.error("❌ No se encontraron valores válidos en la columna MES.")
    st.stop()

mes_actual_indice = 0
mes_seleccionado = st.sidebar.selectbox(
    "Selecciona el mes a consultar:",
    meses_disponibles,
    index=mes_actual_indice,
)

df_raw = df_total[
    normalizar_texto(df_total[COL_MES]).str.upper()
    == mes_seleccionado.upper()
].copy()

if df_raw.empty:
    st.warning(f"⚠️ No existen registros para el mes de {mes_seleccionado}.")
    st.stop()


# =============================================================================
# LÓGICA DE AUDITORÍA DE TIEMPOS (SLA)
# =============================================================================
fechas_entrega = pd.to_datetime(
    df_raw[COL_ENTREGA],
    errors="coerce",
    dayfirst=True,
)

fechas_odoo = pd.to_datetime(
    df_raw[COL_ODOO],
    errors="coerce",
    dayfirst=True,
)


def clasificar_tiempo(indice) -> str:
    valor_odoo = df_raw.at[indice, COL_ODOO]

    if pd.isna(valor_odoo) or str(valor_odoo).strip() == "":
        return "Pendiente de Carga"

    fecha_entrega = fechas_entrega.loc[indice]
    fecha_odoo = fechas_odoo.loc[indice]

    if pd.isna(fecha_entrega) or pd.isna(fecha_odoo):
        return "Entregado (Formato Variable)"

    if fecha_odoo > fecha_entrega:
        return "Entregado Atrasado"

    return "Entregado a Tiempo"


df_raw["Evaluación de Entrega Raw"] = [
    clasificar_tiempo(indice)
    for indice in df_raw.index
]

mapeo_emojis = {
    "Pendiente de Carga": "⏳ Pendiente de Carga",
    "Entregado Atrasado": "⚠️ Entregado Atrasado",
    "Entregado a Tiempo": "🚀 Entregado a Tiempo",
    "Entregado (Formato Variable)": "✅ Entregado (Formato Variable)",
}

df_raw["Estatus de Entrega"] = (
    df_raw["Evaluación de Entrega Raw"]
    .map(mapeo_emojis)
    .fillna("⏳ Pendiente de Carga")
)


# =============================================================================
# FILTROS LATERALES
# =============================================================================
st.sidebar.markdown("---")
st.sidebar.header("🔍 Estado de entrega")

opciones_estatus = [
    "TODOS",
    "🚀 Entregado a Tiempo",
    "⚠️ Entregado Atrasado",
    "⏳ Pendiente de Carga",
    "✅ Entregado (Formato Variable)",
]

filtro_estatus = st.sidebar.selectbox(
    "Selecciona un estatus:",
    opciones_estatus,
)

st.sidebar.markdown("---")
st.sidebar.header("🎯 Equipo comercial")

filtro_area = st.sidebar.selectbox(
    "Área comercial:",
    lista_filtro(df_raw[COL_AREA]),
)

df_opciones_ejecutivo = df_raw.copy()
if filtro_area != "TODOS":
    df_opciones_ejecutivo = df_opciones_ejecutivo[
        normalizar_texto(df_opciones_ejecutivo[COL_AREA]) == str(filtro_area)
    ]

filtro_ejecutivo = st.sidebar.selectbox(
    "Ejecutivo / Coordinador:",
    lista_filtro(df_opciones_ejecutivo[COL_EJECUTIVO]),
)

st.sidebar.markdown("---")
st.sidebar.header("🔄 Frecuencia de entrega")

filtro_recurrencia = st.sidebar.selectbox(
    "Selecciona recurrencia:",
    lista_filtro(df_raw[COL_RECURRENCIA]),
)

st.sidebar.markdown("---")

if st.sidebar.button("🔄 Actualizar datos", use_container_width=True):
    st.cache_data.clear()
    st.rerun()


# =============================================================================
# PROCESAMIENTO DE FILTROS
# =============================================================================
df_base_universo = df_raw.copy()

if filtro_recurrencia != "TODOS":
    df_base_universo = df_base_universo[
        normalizar_texto(df_base_universo[COL_RECURRENCIA])
        == str(filtro_recurrencia)
    ]

if filtro_area != "TODOS":
    df_base_universo = df_base_universo[
        normalizar_texto(df_base_universo[COL_AREA])
        == str(filtro_area)
    ]

if filtro_ejecutivo != "TODOS":
    df_base_universo = df_base_universo[
        normalizar_texto(df_base_universo[COL_EJECUTIVO])
        == str(filtro_ejecutivo)
    ]

df_filtrado = df_base_universo.copy()

if filtro_estatus != "TODOS":
    df_filtrado = df_filtrado[
        df_filtrado["Estatus de Entrega"] == filtro_estatus
    ]


# =============================================================================
# INDICADORES
# =============================================================================
total_boletines = len(df_base_universo)

a_tiempo = int(
    (df_base_universo["Evaluación de Entrega Raw"] == "Entregado a Tiempo").sum()
)
atrasados = int(
    (df_base_universo["Evaluación de Entrega Raw"] == "Entregado Atrasado").sum()
)
pendientes = int(
    (df_base_universo["Evaluación de Entrega Raw"] == "Pendiente de Carga").sum()
)

entregados_validos = a_tiempo + atrasados
efectividad_pct = (
    round((a_tiempo / entregados_validos) * 100, 1)
    if entregados_validos > 0
    else 0
)

c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        label=f"Total de boletines — {mes_seleccionado}",
        value=f"{total_boletines} cuentas",
    )

with c2:
    st.metric(
        label="Efectividad de entregas realizadas",
        value=f"{efectividad_pct}% a tiempo",
        delta=f"{a_tiempo} de {entregados_validos} entregados",
    )

with c3:
    st.metric(
        label="Pendientes de carga",
        value=f"{pendientes} pendientes",
        delta=f"{atrasados} entregados con retraso",
        delta_color="inverse",
    )

st.markdown("---")


# =============================================================================
# GRÁFICO Y TABLA
# =============================================================================
col_grafico, col_tabla = st.columns([4, 6])

with col_grafico:
    st.write("### 📊 Auditoría de SLA")

    conteo_tiempos = (
        df_filtrado["Estatus de Entrega"]
        .value_counts()
        .rename_axis("Estatus de Entrega")
        .reset_index(name="Cantidad")
    )

    if not conteo_tiempos.empty:
        total_filtrado = int(conteo_tiempos["Cantidad"].sum())

        conteo_tiempos["Porcentaje"] = (
            conteo_tiempos["Cantidad"] / total_filtrado * 100
        ).round(1)

        conteo_tiempos["Etiqueta"] = conteo_tiempos.apply(
            lambda fila: f"{fila['Cantidad']} ({fila['Porcentaje']}%)",
            axis=1,
        )

        fig_sla = px.bar(
            conteo_tiempos,
            x="Cantidad",
            y="Estatus de Entrega",
            text="Etiqueta",
            orientation="h",
            color="Estatus de Entrega",
            color_discrete_map={
                "🚀 Entregado a Tiempo": "#2ca02c",
                "⚠️ Entregado Atrasado": "#d62728",
                "⏳ Pendiente de Carga": "#ff7f0e",
                "✅ Entregado (Formato Variable)": "#1f77b4",
            },
        )

        fig_sla.update_traces(textposition="outside")
        fig_sla.update_layout(
            xaxis_title="Boletines",
            yaxis_title=None,
            showlegend=False,
            height=330,
            margin=dict(t=10, b=10, l=10, r=40),
        )

        st.plotly_chart(
            fig_sla,
            use_container_width=True,
            config={"displayModeBar": False},
        )
    else:
        st.info("Sin datos para graficar con los filtros seleccionados.")


with col_tabla:
    st.write("### 🗂️ Resumen Ejecutivo de Cumplimiento")

    if df_filtrado.empty:
        st.info("No existen registros con los filtros seleccionados.")
    else:
        estructura_columnas = {
            "GRUPO": df_filtrado[COL_GRUPO].fillna("---"),
            "ÁREA COMERCIAL": df_filtrado[COL_AREA].fillna("---"),
            "CLIENTE / INSTITUCIÓN": df_filtrado[COL_CLIENTE].fillna("---"),
            "EJECUTIVO / COORDINADOR": df_filtrado[COL_EJECUTIVO].fillna("---"),
            "F. ENTREGA": df_filtrado[COL_ENTREGA].fillna("---"),
            "F. ODOO": df_filtrado[COL_ODOO].fillna("---"),
        }

        mostrar_dias = COL_DIAS_MAX in df_filtrado.columns
        mostrar_observacion = (
            filtro_estatus == "⚠️ Entregado Atrasado"
            and COL_OBSERVACION in df_filtrado.columns
        )

        if mostrar_dias:
            estructura_columnas["MÁX. DÍAS"] = (
                df_filtrado[COL_DIAS_MAX].fillna("---")
            )

        if mostrar_observacion:
            estructura_columnas["OBSERVACIÓN RETRASO"] = (
                df_filtrado[COL_OBSERVACION].fillna("Sin observación")
            )

        estructura_columnas["ESTATUS"] = df_filtrado["Estatus de Entrega"]

        df_tabla_final = pd.DataFrame(estructura_columnas)

        # Formato y orden cronológico.
        fechas_ordenamiento = pd.to_datetime(
            df_tabla_final["F. ENTREGA"],
            errors="coerce",
            dayfirst=True,
        )

        df_tabla_final["_orden_fecha"] = fechas_ordenamiento
        df_tabla_final = (
            df_tabla_final
            .sort_values("_orden_fecha", na_position="last")
            .drop(columns="_orden_fecha")
            .reset_index(drop=True)
        )

        for columna_fecha in ["F. ENTREGA", "F. ODOO"]:
            fechas_formateadas = pd.to_datetime(
                df_tabla_final[columna_fecha],
                errors="coerce",
                dayfirst=True,
            )

            df_tabla_final[columna_fecha] = fechas_formateadas.dt.strftime(
                "%d/%m/%Y"
            ).fillna("---")

        # Fila totalizadora, con exactamente las mismas columnas.
        fila_total = {
            columna: ""
            for columna in df_tabla_final.columns
        }

        fila_total["GRUPO"] = "🟦 TOTAL GENERAL"
        fila_total["CLIENTE / INSTITUCIÓN"] = (
            f"📊 {len(df_tabla_final)} casos filtrados"
        )
        fila_total["ESTATUS"] = "📈 Resumen de selección"

        df_desplegar = pd.concat(
            [df_tabla_final, pd.DataFrame([fila_total])],
            ignore_index=True,
        )

        st.dataframe(
            df_desplegar,
            use_container_width=True,
            hide_index=True,
            height=360,
        )

