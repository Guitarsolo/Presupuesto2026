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

                # --- BOTÓN Y LÓGICA DE GUARDADO (VERSIÓN FINAL Y FUNCIONAL) ---
                if st.button("💾 Guardar Cambios Realizados", type="primary"):
                    with st.spinner("Comparando y guardando los cambios..."):

                        # Obtener el dataframe editado por el usuario
                        edited_df_from_editor = (
                            edited_df  # Este ya lo tenemos del st.data_editor
                        )

                        # Obtener el dataframe original que se mostró al inicio, desde el estado de la sesión
                        original_df_mostrado = st.session_state.df_mostrado

                        # --- Identificar las filas que realmente cambiaron ---
                        # Comparamos el original con el editado. 'compare' es ideal para esto.
                        # Necesitamos un índice único para comparar, usamos ID_SERVICIO.
                        original_indexed = original_df_mostrado.set_index("ID_SERVICIO")
                        edited_indexed = edited_df_from_editor.set_index("ID_SERVICIO")

                        # alineamos las columnas para una comparación justa
                        shared_columns = [
                            col
                            for col in original_indexed.columns
                            if col in edited_indexed.columns
                        ]
                        diff = original_indexed[shared_columns].compare(
                            edited_indexed[shared_columns]
                        )

                        if not diff.empty:
                            # Obtenemos los 'ID_SERVICIO' de las filas que tienen diferencias
                            ids_modificados = diff.index.unique().tolist()

                            # Seleccionamos las filas completas y actualizadas desde el dataframe editado
                            filas_para_guardar = edited_df_from_editor[
                                edited_df_from_editor["ID_SERVICIO"].isin(
                                    ids_modificados
                                )
                            ]

                            # Seleccionar solo las columnas que existen en la hoja 'EDICIONES_USUARIOS'
                            columnas_ediciones = df_ediciones.columns.tolist()
                            columnas_para_guardar_final = [
                                col
                                for col in columnas_ediciones
                                if col in filas_para_guardar.columns
                            ]
                            df_a_guardar = filas_para_guardar[
                                columnas_para_guardar_final
                            ].copy()

                            # Añadir la trazabilidad
                            df_a_guardar["USUARIO_QUE_EDITO"] = username
                            df_a_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            # --- Escribir de vuelta en la hoja de EDICIONES ---
                            # Combina ediciones existentes (de otros usuarios/sesiones) con las nuevas
                            df_ediciones_final = pd.concat(
                                [df_ediciones, df_a_guardar]
                            ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                            success = update_sheet_from_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final
                            )

                            if success:
                                st.success("✅ ¡Cambios guardados con éxito!")
                                # Limpiar la caché y el estado para forzar una recarga completa de datos
                                st.cache_data.clear()
                                del st.session_state.df_mostrado
                                st.experimental_rerun()
                            else:
                                st.error(
                                    "❌ Ocurrió un error al guardar los cambios en Google Sheets."
                                )
                        else:
                            st.info("No se detectaron cambios para guardar.")

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
