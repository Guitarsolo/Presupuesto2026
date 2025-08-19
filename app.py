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

                # --- BOTÓN Y LÓGICA DE GUARDADO (VERSIÓN FINAL CON FOTO COMPLETA) ---
                if st.button("💾 Guardar Cambios Realizados", type="primary"):
                    with st.spinner("Comparando y guardando los cambios..."):

                        # Obtener DFs desde el estado de la sesión y el editor
                        edited_df = edited_df  # Viene del data_editor
                        original_df_mostrado = st.session_state.df_mostrado

                        # Asegurar tipos de datos para la comparación
                        edited_df["ID_SERVICIO"] = edited_df["ID_SERVICIO"].astype(str)
                        original_df_mostrado["ID_SERVICIO"] = original_df_mostrado[
                            "ID_SERVICIO"
                        ].astype(str)

                        # Identificar las filas que realmente han cambiado
                        original_indexed = original_df_mostrado.set_index("ID_SERVICIO")
                        edited_indexed = edited_df.set_index("ID_SERVICIO")

                        diff_indices = original_indexed.ne(edited_indexed).any(axis=1)
                        filas_modificadas_completas = edited_df[
                            edited_df["ID_SERVICIO"].isin(
                                diff_indices[diff_indices].index
                            )
                        ]

                        if not filas_modificadas_completas.empty:
                            # Obtener el estado actual de la hoja de ediciones
                            df_ediciones_actuales = get_sheet_as_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS"
                            )

                            # --- PREPARAR LAS NUEVAS FILAS PARA GUARDAR ---
                            df_a_guardar = filas_modificadas_completas.copy()

                            # Añadir la información de trazabilidad
                            df_a_guardar["USUARIO_QUE_EDITO"] = username
                            df_a_guardar["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            # --- COMBINAR CON EDICIONES EXISTENTES Y ESCRIBIR ---
                            # Si la hoja de ediciones está vacía, simplemente guardamos las nuevas filas.
                            if df_ediciones_actuales.empty:
                                df_ediciones_final = df_a_guardar
                            else:
                                # Si ya hay datos, combinamos y eliminamos duplicados para actualizar
                                df_ediciones_actuales["ID_SERVICIO"] = (
                                    df_ediciones_actuales["ID_SERVICIO"].astype(str)
                                )
                                df_ediciones_final = pd.concat(
                                    [df_ediciones_actuales, df_a_guardar],
                                    ignore_index=True,
                                )
                                df_ediciones_final.drop_duplicates(
                                    subset=["ID_SERVICIO"], keep="last", inplace=True
                                )

                            # Alinear columnas antes de guardar para evitar errores de orden
                            columnas_finales = spreadsheet.worksheet(
                                "EDICIONES_USUARIOS"
                            ).row_values(1)
                            df_ediciones_final = df_ediciones_final.reindex(
                                columns=columnas_finales
                            )

                            success = update_sheet_from_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final
                            )

                            if success:
                                st.success("✅ ¡Cambios guardados con éxito!")
                                st.cache_data.clear()
                                del st.session_state.df_mostrado
                                st.experimental_rerun()
                            else:
                                st.error("❌ Ocurrió un error al guardar los cambios.")
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
