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

# --- CONFIGURACIÓN ---
st.set_page_config(layout="wide", page_title="App Presupuesto RRHH")
st.title("Sistema de Carga de Presupuesto RRHH 2026")

# --- AUTENTICACIÓN ---
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)
authenticator.login("main")

# --- LÓGICA DE LA APLICACIÓN ---
if st.session_state["authentication_status"]:
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
            # --- LÓGICA DE FUSIÓN (ROBUSTA) ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()

            # Estandarizar nombres de columnas clave al cargar
            df_saf_base.columns = [
                col.upper().replace(" ", "_") for col in df_saf_base.columns
            ]
            df_ediciones.columns = [
                col.upper().replace(" ", "_") for col in df_ediciones.columns
            ]

            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)
            df_a_mostrar = df_saf_base.copy()

            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                df_a_mostrar = df_a_mostrar.set_index("ID_SERVICIO")
                df_ediciones_filtradas = df_ediciones[
                    df_ediciones["SAF"] == user_saf
                ].set_index("ID_SERVICIO")
                df_a_mostrar.update(df_ediciones_filtradas)
                df_a_mostrar.reset_index(inplace=True)

            df_a_mostrar = df_a_mostrar.sort_values(
                by=["SUBORGANIZACION", "DOCUMENTO"], ignore_index=True
            )

            # --- DEFINICIÓN DE LA INTERFAZ ---
            columnas_bloqueadas = [
                "DOCUMENTO",
                "NOMBRES",
                "SUBORGANIZACION",
                "ID_SERVICIO",
                "CARGO",
                "AGRUPAMIENTO",
                "SITUACIONREVISTA",
                "FUNCION",
                "SITUACIONLABORAL",
                "FORMULARIOS_F4",
            ]
            columnas_editables = [
                "ESTADO",
                "ORGANISMO_ORIGEN_ACTUALIZADO",
                "ADSCRIPTO_A_OTRO",
                "ORGANISMO_DESTINO_DE_ADSCRIPTO",
                "CARGO_SUBROGANTE",
                "CATEGORIA_QUE_SUBROGA",
                "AGENTE_AFECTADO_A_OTRO",
                "ORGANISMO_DESTINO_DEL_AGENTE_AFECTADO",
                "AGENTE_AFECTADO_DE_OTRO",
                "ORGANISMO_ORIGEN_DEL_AGENTE_AFECTADO_(DE_DONDE_VIENE)",
                "ACOGIDO_A_RETIRO_VOLUNTARIO",
                "ACTO_ADMINISTRATIVO",
            ]

            # Asegurar que las columnas existan
            for col in columnas_bloqueadas + columnas_editables:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA

            # --- RENDERIZADO ---
            st.info(
                "Edite en la tabla. Las filas modificadas se guardarán al presionar el botón."
            )
            if "df_mostrado" not in st.session_state:
                st.session_state.df_mostrado = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar,
                disabled=columnas_bloqueadas,
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="editor",
            )

            # --- LÓGICA DE GUARDADO ---
            if st.button("💾 Guardar Cambios", type="primary"):
                with st.spinner("Procesando..."):
                    df_original_sesion = st.session_state.df_mostrado

                    # Estandarizar también el DF editado
                    edited_df.columns = [
                        col.upper().replace(" ", "_") for col in edited_df.columns
                    ]

                    # Comparar valores como strings para evitar errores de tipo
                    df_comp_orig = df_original_sesion.fillna("__NULL__").astype(str)
                    df_comp_edit = edited_df.fillna("__NULL__").astype(str)

                    diff_mask = (df_comp_orig != df_comp_edit).any(axis=1)
                    filas_modificadas = edited_df[diff_mask]

                    if not filas_modificadas.empty:
                        filas_para_guardar = filas_modificadas.copy()
                        filas_para_guardar["USUARIO_QUE_EDITO"] = username
                        filas_para_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                            tz="America/Argentina/Buenos_Aires"
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        # Guardar de vuelta en EDICIONES_USUARIOS
                        df_ediciones_actuales = get_sheet_as_dataframe(
                            spreadsheet, "EDICIONES_USUARIOS"
                        )
                        df_ediciones_actuales.columns = [
                            col.upper().replace(" ", "_")
                            for col in df_ediciones_actuales.columns
                        ]

                        df_ediciones_final = pd.concat(
                            [df_ediciones_actuales, filas_para_guardar],
                            ignore_index=True,
                        ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                        # Es importante devolver los nombres a su formato original antes de guardar
                        hoja_destino_cols_originales = spreadsheet.worksheet(
                            "EDICIONES_USUARIOS"
                        ).row_values(1)
                        df_ediciones_final.columns = hoja_destino_cols_originales

                        success = update_sheet_from_dataframe(
                            spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final
                        )

                        if success:
                            st.success("✅ ¡Cambios guardados!")
                            st.cache_data.clear()
                            del st.session_state.df_mostrado
                            st.rerun()
                        else:
                            st.error("❌ Ocurrió un error al guardar.")
                    else:
                        st.info("No se detectaron cambios para guardar.")
        else:
            st.error("No se encontraron datos en 'BD_CARGOS_COMPLETA'.")
    else:
        st.error("Falló la conexión con Google Sheets.")

# --- Manejo de errores de autenticación ---
elif st.session_state["authentication_status"] is False:
    st.error("Usuario/contraseña incorrecto.")
elif st.session_state["authentication_status"] is None:
    st.warning("Ingrese su usuario y contraseña.")
