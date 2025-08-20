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
        # --- LECTURA DE FUENTES DE DATOS ---
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            # --- LÓGICA DE FUSIÓN DE DATOS (PARA LA VISTA) ---
            # 1. Filtrar la base original por el SAF del usuario
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()

            # Renombrar columnas clave para consistencia interna
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"},
                inplace=True,
                errors="ignore",
            )
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)

            # 2. Preparar la fusión: empezar con la base del SAF
            df_a_mostrar = df_saf_base

            # 3. Si hay ediciones, las aplicamos
            if not df_ediciones.empty:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                # Seleccionar solo las columnas editables de la hoja de ediciones
                columnas_solo_editables = [
                    "ID_SERVICIO",
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
                # Asegurarnos que las columnas existan en df_ediciones antes de seleccionarlas
                columnas_presentes = [
                    col
                    for col in columnas_solo_editables
                    if col in df_ediciones.columns
                ]
                df_ediciones_a_fusionar = df_ediciones[columnas_presentes]

                # Fusionar (merge) los datos. Los datos de la derecha (ediciones) sobreescribirán los de la izquierda
                df_a_mostrar = pd.merge(
                    df_a_mostrar,
                    df_ediciones_a_fusionar,
                    on="ID_SERVICIO",
                    how="left",
                    suffixes=("", "_edicion"),
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
                "Edite directamente en la tabla. El campo 'ESTADO' es obligatorio al modificar una fila."
            )

            st.session_state["df_mostrado_al_usuario"] = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="editor_principal",
            )

            # --- LÓGICA DE GUARDADO ---
            if st.button("💾 Guardar Cambios Realizados", type="primary"):
                with st.spinner("Procesando y guardando..."):
                    df_original_sesion = st.session_state["df_mostrado_al_usuario"]

                    # Identificar filas modificadas con el método manual robusto
                    indices_modificados = []
                    for i in range(len(edited_df)):
                        if not df_original_sesion.iloc[i].equals(edited_df.iloc[i]):
                            indices_modificados.append(i)

                    if indices_modificados:
                        filas_modificadas = edited_df.iloc[indices_modificados].copy()

                        if (
                            filas_modificadas["ESTADO"].isnull().any()
                            or (filas_modificadas["ESTADO"] == "").any()
                        ):
                            st.error(
                                "❌ Error: Se detectaron filas modificadas con 'ESTADO' vacío. Complete el campo antes de guardar."
                            )
                        else:
                            # Preparar las filas para guardar, asegurando que tengan la estructura completa
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

                            # Alinear columnas antes de escribir, para máxima seguridad
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
