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
            # --- PREPARACIÓN Y FUSIÓN DE DATOS (MÉTODO ROBUSTO) ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"},
                inplace=True,
                errors="ignore",
            )
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)

            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                # Seleccionar solo ediciones relevantes y la última por ID
                df_ediciones_saf = df_ediciones[
                    df_ediciones["SAF"] == user_saf
                ].drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                # Fusionar con pd.merge
                df_a_mostrar = pd.merge(
                    df_saf_base,
                    df_ediciones_saf,
                    on="ID_SERVICIO",
                    how="left",
                    suffixes=("", "_y"),
                )
                # Limpiar columnas duplicadas por el merge
                df_a_mostrar.drop(
                    [col for col in df_a_mostrar.columns if "_y" in str(col)],
                    axis=1,
                    inplace=True,
                )
            else:
                df_a_mostrar = df_saf_base

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

            # Asegurar que todas las columnas necesarias existan
            for col in columnas_editables:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA

            columnas_visibles = columnas_bloqueadas + columnas_editables

            # --- RENDERIZADO ---
            st.info(
                "Edite directamente en la tabla. El campo 'ESTADO' es obligatorio al modificar una fila."
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

            # --- LÓGICA DE GUARDADO ---
            if st.button("💾 Guardar Cambios Realizados", type="primary"):
                with st.spinner("Procesando y guardando..."):
                    df_original_mostrado = st.session_state["df_mostrado"]

                    # Identificar cambios con el método robusto de comparación normalizada
                    df_comp_orig = df_original_mostrado.astype(str).fillna("__NULL__")
                    df_comp_edit = edited_df.astype(str).fillna("__NULL__")
                    diff_mask = (df_comp_orig != df_comp_edit).any(axis=1)
                    filas_modificadas = edited_df[diff_mask]

                    if not filas_modificadas.empty:
                        if (
                            filas_modificadas["ESTADO"]
                            .isin(["nan", "None", "", "NaT"])
                            .any()
                        ):
                            st.error(
                                "❌ Error de validación: Se detectaron filas modificadas con 'ESTADO' vacío. Complete el campo antes de guardar."
                            )
                        else:
                            # Preparar y guardar las filas
                            filas_para_guardar = filas_modificadas.copy()
                            filas_para_guardar["USUARIO_QUE_EDITO"] = username
                            filas_para_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            df_ediciones_actuales = get_sheet_as_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS"
                            )
                            if not df_ediciones_actuales.empty:
                                df_ediciones_actuales = df_ediciones_actuales.astype(
                                    str
                                )

                            filas_para_guardar = filas_para_guardar.astype(str)

                            df_ediciones_final = pd.concat(
                                [df_ediciones_actuales, filas_para_guardar],
                                ignore_index=True,
                            ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                            columnas_hoja_destino = spreadsheet.worksheet(
                                "EDICIONES_USUARIOS"
                            ).row_values(1)
                            df_ediciones_final = df_ediciones_final.reindex(
                                columns=columnas_hoja_destino
                            )

                            success = update_sheet_from_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final
                            )

                            if success:
                                st.success("✅ ¡Cambios guardados con éxito!")
                                st.cache_data.clear()
                                del st.session_state["df_mostrado"]
                                st.rerun()
                            else:
                                st.error("❌ Ocurrió un error al guardar.")
                    else:
                        st.info("No se detectaron cambios para guardar.")
        else:
            st.error("No se encontraron datos en la hoja 'BD_CARGOS_COMPLETA'.")
    else:
        st.error("Falló la conexión con Google Sheets.")

# --- Manejo de casos de autenticación fallida o pendiente ---
elif st.session_state["authentication_status"] is False:
    st.error("Usuario o contraseña incorrecto.")
elif st.session_state["authentication_status"] is None:
    st.warning("Por favor, ingrese su usuario y contraseña para continuar.")
