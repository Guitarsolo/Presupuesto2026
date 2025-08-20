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
            # --- PREPARACIÓN Y FUSIÓN DE DATOS (MÉTODO CON GUARDIA) ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"},
                inplace=True,
                errors="ignore",
            )
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)

            df_a_mostrar = df_saf_base  # Por defecto, mostramos la base

            # Solo intentar fusionar si 'df_ediciones' TIENE datos
            if not df_ediciones.empty:
                # La guardia que previene el KeyError
                if "ID_SERVICIO" in df_ediciones.columns:
                    df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(
                        str
                    )
                    df_a_mostrar.set_index("ID_SERVICIO", inplace=True)
                    df_ediciones_a_aplicar = df_ediciones.set_index("ID_SERVICIO")
                    df_a_mostrar.update(df_ediciones_a_aplicar)
                    df_a_mostrar.reset_index(inplace=True)
                else:
                    st.warning(
                        "Advertencia: La hoja 'EDICIONES_USUARIOS' no tiene una columna 'ID_SERVICIO'. No se pudieron cargar las ediciones previas."
                    )

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

            # --- RENDERIZADO ---
            st.info(
                "Edite en la tabla. Las filas modificadas se guardarán al presionar el botón."
            )

            st.session_state["df_mostrado"] = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="editor",
            )

            # --- LÓGICA DE GUARDADO (se mantiene igual, es robusta) ---
            if st.button("💾 Guardar Cambios", type="primary"):
                with st.spinner("Procesando..."):
                    df_original_sesion = st.session_state["df_mostrado"]

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
                        filas_para_guardar["SAF"] = (
                            user_saf  # Añadir SAF para referencia
                        )

                        df_ediciones_actuales = get_sheet_as_dataframe(
                            spreadsheet, "EDICIONES_USUARIOS"
                        )
                        if not df_ediciones_actuales.empty:
                            df_ediciones_actuales = df_ediciones_actuales.astype(str)

                        df_ediciones_final = pd.concat(
                            [df_ediciones_actuales, filas_para_guardar],
                            ignore_index=True,
                        ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                        hoja_destino_cols_originales = spreadsheet.worksheet(
                            "EDICIONES_USUARIOS"
                        ).row_values(1)
                        df_ediciones_final = df_ediciones_final.reindex(
                            columns=hoja_destino_cols_originales
                        )

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
