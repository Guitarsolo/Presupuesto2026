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
    # --- Interfaz de Usuario ---
    name = st.session_state["name"]
    username = st.session_state["username"]
    authenticator.logout(location="sidebar")
    st.sidebar.write(f"Bienvenido/a, **{name}**")

    user_saf = config["credentials"]["usernames"][username]["saf"]
    st.header(f"Planilla de Trabajo - SAF {user_saf}")

    spreadsheet = connect_to_gsheet()
    if spreadsheet:
        # --- LECTURA Y PREPARACIÓN DE DATOS ---
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"},
                inplace=True,
                errors="ignore",
            )

            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)
            df_a_mostrar = df_saf_base.copy()

            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                df_a_mostrar = df_a_mostrar.set_index("ID_SERVICIO")
                df_ediciones_filtradas = df_ediciones.set_index("ID_SERVICIO")
                df_a_mostrar.update(df_ediciones_filtradas)
                df_a_mostrar.reset_index(inplace=True)

            df_a_mostrar = df_a_mostrar.sort_values(
                by=["Suborganizacion", "Documento"], ignore_index=True
            )

            # --- DEFINICIÓN DE LA INTERFAZ ---
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

            # --- RENDERIZADO DE LA INTERFAZ CON st.data_editor ---
            st.info(
                "Edite directamente en la tabla. No se permite añadir ni borrar filas. El campo 'ESTADO' es obligatorio al modificar una fila."
            )

            if "df_mostrado_al_usuario" not in st.session_state:
                st.session_state["df_mostrado_al_usuario"] = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="data_editor_saf_final",
            )

            # --- LÓGICA DE GUARDADO (VERSIÓN CON ALINEACIÓN FORZADA) ---
            if st.button("💾 Guardar Cambios Realizados", type="primary"):
                with st.spinner("Procesando y guardando cambios..."):
                    df_original_sesion = st.session_state["df_mostrado_al_usuario"]

                    # ★★★ PASO 1: ALINEAR LOS DATAFRAMES ANTES DE COMPARAR ★★★
                    # Esto previene el ValueError asegurando que las columnas y sus órdenes son idénticos.
                    orden_columnas = df_original_sesion.columns.tolist()
                    df_editado_alineado = edited_df[orden_columnas]

                    # 2. COMPARAR LOS DATAFRAMES ALINEADOS
                    cambios_df = df_original_sesion.compare(df_editado_alineado)

                    if not cambios_df.empty:
                        indices_modificados = cambios_df.index.unique()
                        filas_modificadas = df_editado_alineado.loc[indices_modificados]

                        if (
                            filas_modificadas["ESTADO"].isnull().any()
                            or (filas_modificadas["ESTADO"] == "").any()
                        ):
                            st.error(
                                "❌ Error de validación: Se detectaron filas modificadas donde el campo 'ESTADO' está vacío. Por favor, complete todos los campos 'ESTADO' antes de guardar."
                            )
