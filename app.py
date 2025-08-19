import streamlit as st
import pandas as pd
from google_sheets_connector import connect_to_gsheet, get_sheet_as_dataframe

# Configuración de la página
st.set_page_config(layout="wide", page_title="App Presupuesto RRHH")

st.title("Sistema de Carga de Presupuesto RRHH 2026")
st.header("Fase 1: Prueba de Conexión a Google Sheets")

# 1. Intentar conectar a la hoja de cálculo
spreadsheet = connect_to_gsheet()

# 2. Si la conexión es exitosa, proceder a leer los datos
if spreadsheet:
    st.success("✅ ¡Conexión con Google Sheets establecida con éxito!")

    sheet_name = "BD_CARGOS_COMPLETA"  # <-- VERIFICA EL NOMBRE DE TU HOJA PRINCIPAL

    st.info(f"Intentando leer datos de la hoja: '{sheet_name}'...")

    # 3. Leer los datos y mostrarlos en pantalla
    df = get_sheet_as_dataframe(spreadsheet, sheet_name)

    if not df.empty:
        st.success(f"✔️ Se leyeron {len(df)} filas de la hoja de cálculo.")
        st.write("Primeras 5 filas encontradas:")
        st.dataframe(df.head())  # Muestra las primeras 5 filas de la tabla
    else:
        st.error(
            "❌ No se pudieron leer datos de la hoja. Verifica el nombre o los permisos."
        )
else:
    st.error(
        "❌ Falló la conexión con Google Sheets. Verifica tu archivo `secrets.toml`."
    )
