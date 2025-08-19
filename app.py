import streamlit as st
import pandas as pd
import yaml
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader
from google_sheets_connector import connect_to_gsheet, get_sheet_as_dataframe

# --- CONFIGURACIÓN DE PÁGINA Y TÍTULO ---
st.set_page_config(layout="wide", page_title="App Presupuesto RRHH")
st.title("Sistema de Carga de Presupuesto RRHH 2026")

# --- 1. AUTENTICACIÓN ---
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

# --- ★★★ CAMBIO FUNDAMENTAL EN LA LÓGICA DE LOGIN ★★★ ---
# La función login ahora se llama sin asignarla a variables.
authenticator.login("main")

# Verificamos el estado de la autenticación desde st.session_state
if st.session_state["authentication_status"]:
    # --- Interfaz de Usuario Principal ---
    # Accedemos al nombre y username también desde st.session_state
    name = st.session_state["name"]
    username = st.session_state["username"]

    authenticator.logout(location="sidebar")
    st.sidebar.write(f"Bienvenido/a, **{name}**")

    # Obtener el SAF del usuario logueado desde nuestra configuración
    user_saf = config["credentials"]["usernames"][username]["saf"]
    st.header(f"Planilla de Trabajo - SAF {user_saf}")

    # Conectar a Google Sheets
    spreadsheet = connect_to_gsheet()
    if spreadsheet:
        df_completo = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")

        if not df_completo.empty:
            # Lógica de filtrado y ordenamiento...
            df_saf = df_completo[df_completo["SAF"] == user_saf].copy()
            if "Suborganizacion" in df_saf.columns and "Documento" in df_saf.columns:
                df_saf = df_saf.sort_values(by=["Suborganizacion", "Documento"])

            # Definición de la estructura de la tabla...
            columnas_bloqueadas = [
                "Documento",
                "Nombres",
                "Suborganizacion",
                "ID_Servicio",
                "cargo",
                "Agrupamiento",
                "SituacionRevista",
                "funcion",
                "SituacionLaboral",
                "FORMULARIOS_F4",
            ]
            columnas_editables = [
                "ESTADO",
                "ORGANISMO ACTUALIZADO",
                "ADSCRIPTO A OTRO",
                "ORGANISMO DESTINO DE ADSCRIPTO",
                "SITUACIÓN SUBROGANTE",
                "CATEGORIA QUE SUBROGA",
                "AGENTE AFECTADO A OTRO",
                "ORGANISMO DESTINO DEL AGENTE AFECTADO",
                "AGENTE AFECTADO DE OTRO",
                "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)",
                "ACOGIDO A RETIRO VOLUNTARIO",
                "OBSERVACIONES GENERALES",
            ]
            columnas_visibles = columnas_bloqueadas + columnas_editables
            for col in columnas_visibles:
                if col not in df_saf.columns:
                    df_saf[col] = None

            st.info(
                "A continuación, puede editar las celdas de la tabla. Las primeras columnas están bloqueadas."
            )

            st.session_state["original_df"] = df_saf
            edited_df = st.data_editor(
                df_saf[columnas_visibles],
                key="data_editor_saf",
                num_rows="dynamic",
                disabled=columnas_bloqueadas,
                height=600,
            )
            st.session_state["edited_df"] = edited_df

        else:
            st.error("No se pudieron leer datos de la hoja 'BD_CARGOS_COMPLETA'.")
    else:
        st.error("Falló la conexión con Google Sheets.")

elif st.session_state["authentication_status"] == False:
    st.error("Usuario o contraseña incorrecto.")
elif st.session_state["authentication_status"] == None:
    st.warning("Por favor, ingrese su usuario y contraseña para continuar.")
