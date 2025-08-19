import streamlit as st
import pandas as pd
import yaml
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader
from google_sheets_connector import (
    connect_to_gsheet,
    get_sheet_as_dataframe,
    update_sheet_from_dataframe,
)

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

authenticator.login("main")

# --- 2. LÓGICA DE LA APLICACIÓN POST-LOGIN ---
if st.session_state["authentication_status"]:
    # --- Interfaz de Usuario Principal ---
    name = st.session_state["name"]
    username = st.session_state["username"]
    authenticator.logout(location="sidebar")
    st.sidebar.write(f"Bienvenido/a, **{name}**")

    user_saf = config["credentials"]["usernames"][username]["saf"]
    st.header(f"Planilla de Trabajo - SAF {user_saf}")

    spreadsheet = connect_to_gsheet()
    if spreadsheet:
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()

            if "idServicioAgente" in df_saf_base.columns:
                df_saf_base.rename(
                    columns={"idServicioAgente": "ID_SERVICIO"}, inplace=True
                )

            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)
            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                df_saf_base = df_saf_base.set_index("ID_SERVICIO")
                df_ediciones_filtradas = df_ediciones.set_index("ID_SERVICIO")
                df_saf_base.update(df_ediciones_filtradas)
                df_saf_base.reset_index(inplace=True)

            df_a_mostrar = df_saf_base.sort_values(by=["Suborganizacion", "Documento"])

            columnas_bloqueadas = [
                "Documento",
                "Nombres",
                "Suborganizacion",
                "ID_SERVICIO",
                "cargo",
                "Agrupamiento",
                "SituacionRevista",
                "FUNCION",
                "SituacionLaboral",
                "FORMULARIOS_F4",
            ]
            columnas_editables = [
                "ESTADO",
                "ORGANISMO ORIGEN ACTUALIZADO",
                "ADSCRIPTO A OTRO",
                "ORGANISMO DESTINO DE ADSCRIPTO",
                "CARGO SUBROGANTE",
                "CATEGORIA QUE SUBROGA",
                "AGENTE AFECTADO A OTRO",
                "ORGANISMO DESTINO DEL AGENTE AFECTADO",
                "AGENTE AFECTADO DE OTRO",
                "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)",
                "ACOGIDO A RETIRO VOLUNTARIO",
                "ACTO ADMINISTRATIVO",
            ]

            columnas_visibles = columnas_bloqueadas + columnas_editables
            for col in columnas_visibles:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA

            # --- Guardamos el estado que se muestra al usuario para la comparación
            if "df_mostrado" not in st.session_state:
                st.session_state.df_mostrado = df_a_mostrar

            # --- RENDERIZADO DE LA INTERFAZ CON PESTAÑAS ---
            st.info(
                "Utilice la tabla a continuación para editar los datos. Los cambios se guardarán al presionar el botón."
            )

            tab1, tab2 = st.tabs(
                ["📝 Planilla de Trabajo Principal", "📄 Instrucciones"]
            )

            with tab1:
                st.write("### Agentes del SAF")

                edited_df = st.data_editor(
                    df_a_mostrar[columnas_visibles],
                    key="data_editor_final",
                    use_container_width=True,
                    height=600,
                    disabled=columnas_bloqueadas,
                )

                st.write("")

                if st.button("💾 Guardar Cambios Realizados", type="primary"):
                    with st.spinner("Comparando y guardando los cambios..."):
                        # ... (Tu lógica de guardado, que parece correcta, iría aquí)
                        # ... Para ser concisos, la dejamos como la tenías.
                        st.success("Guardado (lógica placeholder)")

            with tab2:
                st.write("### Guía de Uso")
                st.markdown(
                    """
                - **Edición:** Haga doble clic en una celda de la sección derecha para editar.
                - **Guardado:** Una vez finalizadas las modificaciones, haga clic en "Guardar Cambios Realizados".
                - **Trazabilidad:** Su usuario y la fecha quedarán registrados automáticamente.
                - **Adscriptos de Otros:** Utilice el menú `➕ Cargar Adscripto DE Otro Organismo` en la parte superior para registrar agentes que no pertenecen a su planta.
                """
                )

# ★★★ BLOQUE 'else' CORREGIDO Y RESTAURADO ★★★
elif st.session_state["authentication_status"] == False:
    st.error("Usuario o contraseña incorrecto.")
elif st.session_state["authentication_status"] == None:
    st.warning("Por favor, ingrese su usuario y contraseña para continuar.")
