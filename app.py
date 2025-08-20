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
            # --- PREPARACIÓN Y FUSIÓN DE DATOS ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"},
                inplace=True,
                errors="ignore",
            )
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)

            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                # Seleccionar solo ediciones relevantes para una fusión más limpia
                df_ediciones_saf = df_ediciones[df_ediciones["SAF"] == user_saf]

                # Unimos el DF base con las ediciones del SAF actual
                df_a_mostrar = pd.merge(
                    df_saf_base,
                    df_ediciones_saf,
                    on="ID_SERVICIO",
                    how="left",
                    suffixes=("", "_edicion"),
                )

                # Para cada columna editable, si hay una versión "_edicion", la usamos. Si no, mantenemos la original.
                for col in df_ediciones.columns:
                    if f"{col}_edicion" in df_a_mostrar.columns:
                        df_a_mostrar[col] = df_a_mostrar[f"{col}_edicion"].fillna(
                            df_a_mostrar[col]
                        )
                        df_a_mostrar.drop(columns=[f"{col}_edicion"], inplace=True)
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

            columnas_visibles = columnas_bloqueadas + columnas_editables
            for col in columnas_visibles:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA

            # --- RENDERIZADO ---
            st.info(
                "Edite directamente en la tabla. El campo 'ESTADO' es obligatorio al modificar una fila."
            )

            # ★★★ LÍNEA CORREGIDA ★★★
            # Aseguramos usar el mismo nombre de clave de sesión en ambos lugares
            st.session_state["df_mostrado_al_usuario"] = df_a_mostrar.copy()

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
                with st.spinner("Procesando y guardando cambios..."):
                    df_original_sesion = st.session_state["df_mostrado_al_usuario"]

                    indices_modificados = []
                    df_comp_original = df_original_sesion.fillna("__NULL__").astype(str)
                    df_comp_editado = edited_df.fillna("__NULL__").astype(str)

                    for i in range(len(df_comp_editado)):
                        if not df_comp_original.iloc[i].equals(df_comp_editado.iloc[i]):
                            indices_modificados.append(i)

                    if indices_modificados:
                        filas_modificadas = edited_df.iloc[indices_modificados].copy()

                        if (
                            filas_modificadas["ESTADO"].isnull().any()
                            or (filas_modificadas["ESTADO"] == "").any()
                        ):
                            st.error(
                                "❌ Error de validación: Se detectaron filas modificadas con 'ESTADO' vacío."
                            )
                        else:
                            # Preparar las "fotos completas" de las filas modificadas para guardar
                            filas_para_guardar = filas_modificadas

                            filas_para_guardar["USUARIO_QUE_EDITO"] = username
                            filas_para_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            # Actualizar el registro maestro de ediciones
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

                            # Alinear columnas con la hoja de destino
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
                                del st.session_state["df_mostrado_al_usuario"]
                                st.rerun()
                            else:
                                st.error("❌ Ocurrió un error al guardar los cambios.")
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
