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
        # --- LECTURA Y PREPARACIÓN DE DATOS (MÉTODO ULTRA ROBUSTO) ---
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            # Función para limpiar y estandarizar nombres de columnas
            def limpiar_nombres_columnas(df):
                df.columns = [
                    str(col).strip().upper().replace(" ", "_") for col in df.columns
                ]
                return df

            df_original = limpiar_nombres_columnas(df_original)

            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)
            df_a_mostrar = df_saf_base

            if not df_ediciones.empty:
                df_ediciones = limpiar_nombres_columnas(df_ediciones)
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                df_a_mostrar = df_a_mostrar.set_index("ID_SERVICIO")
                df_ediciones_a_aplicar = df_ediciones.set_index("ID_SERVICIO")
                df_a_mostrar.update(df_ediciones_a_aplicar)
                df_a_mostrar.reset_index(inplace=True)

            df_a_mostrar = df_a_mostrar.sort_values(
                by=["SUBORGANIZACION", "DOCUMENTO"], ignore_index=True
            )

            # --- DEFINICIÓN DE LA INTERFAZ ---
            columnas_bloqueadas_std = [
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
            columnas_editables_std = [
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

            columnas_visibles_std = columnas_bloqueadas_std + columnas_editables_std

            # Crear DataFrame final para mostrar con el orden correcto y columnas existentes
            df_final_para_mostrar = pd.DataFrame(columns=columnas_visibles_std)
            for col in columnas_visibles_std:
                if col in df_a_mostrar.columns:
                    df_final_para_mostrar[col] = df_a_mostrar[col]
                else:
                    df_final_para_mostrar[col] = pd.NA

            # --- RENDERIZADO ---
            st.info(
                "Edite en la tabla. Las filas modificadas se guardarán al presionar el botón."
            )

            st.session_state["df_mostrado"] = df_final_para_mostrar.copy()

            edited_df = st.data_editor(
                df_final_para_mostrar,
                disabled=columnas_bloqueadas_std,
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="editor",
            )

            # --- LÓGICA DE GUARDADO (COMPARACIÓN MANUAL) ---
            if st.button("💾 Guardar Cambios", type="primary"):
                with st.spinner("Procesando..."):
                    df_original_sesion = st.session_state["df_mostrado"]

                    indices_modificados = []
                    df_comp_orig = df_original_sesion.fillna("__NULL__").astype(str)
                    df_comp_edit = edited_df.fillna("__NULL__").astype(str)

                    for i in range(len(df_comp_edit)):
                        if not df_comp_orig.iloc[i].equals(df_comp_edit.iloc[i]):
                            indices_modificados.append(i)

                    if indices_modificados:
                        filas_modificadas = edited_df.iloc[indices_modificados].copy()

                        if filas_modificadas["ESTADO"].isin(["__NULL__", ""]).any():
                            st.error(
                                "❌ Error: Se detectaron filas modificadas con 'ESTADO' vacío."
                            )
                        else:
                            filas_para_guardar = filas_modificadas
                            filas_para_guardar["USUARIO_QUE_EDITO"] = username
                            filas_para_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            filas_para_guardar["SAF"] = user_saf

                            df_ediciones_actuales = get_sheet_as_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS"
                            )
                            if not df_ediciones_actuales.empty:
                                df_ediciones_actuales = limpiar_nombres_columnas(
                                    df_ediciones_actuales
                                ).astype(str)

                            filas_para_guardar = filas_para_guardar.astype(str)
                            df_ediciones_final = pd.concat(
                                [df_ediciones_actuales, filas_para_guardar],
                                ignore_index=True,
                            ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                            # Devolver los nombres a su formato original antes de guardar
                            hoja_destino_cols_originales = spreadsheet.worksheet(
                                "EDICIONES_USUARIOS"
                            ).row_values(1)
                            # Creamos un diccionario para renombrar de ESTANDAR -> Original
                            rename_dict = {
                                std_col: orig_col
                                for std_col, orig_col in zip(
                                    [
                                        c.upper().replace(" ", "_")
                                        for c in hoja_destino_cols_originales
                                    ],
                                    hoja_destino_cols_originales,
                                )
                            }
                            df_ediciones_final.rename(columns=rename_dict, inplace=True)

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

elif st.session_state["authentication_status"] is False:
    st.error("Usuario/contraseña incorrecto.")
elif st.session_state["authentication_status"] is None:
    st.warning("Ingrese su usuario y contraseña.")
