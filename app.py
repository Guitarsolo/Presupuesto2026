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
            # --- PREPARACIÓN Y FUSIÓN DE DATOS ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO"},
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

            # --- RENDERIZADO DE LA INTERFAZ Y LÓGICA DE GUARDADO ---
            st.info(
                "Utilice la tabla a continuación para editar. Los cambios se guardarán al presionar el botón."
            )

            # Guardamos el DF fusionado que se muestra, para poder compararlo al guardar
            st.session_state["df_mostrado_al_usuario"] = df_a_mostrar

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                num_rows="dynamic",
                use_container_width=True,
                height=600,
                key="data_editor_saf",
            )

            if st.button("💾 Guardar Cambios Realizados", type="primary"):
                with st.spinner("Procesando y guardando cambios..."):
                    df_original_sesion = st.session_state["df_mostrado_al_usuario"]

                    cambios = df_original_sesion.compare(edited_df)

                    if not cambios.empty:
                        ids_modificados = cambios.index.tolist()
                        filas_modificadas = edited_df.iloc[ids_modificados].copy()

                        filas_modificadas["USUARIO_QUE_EDITO"] = username
                        filas_modificadas["FECHA_DE_EDICION"] = pd.Timestamp.now(
                            tz="America/Argentina/Buenos_Aires"
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        df_ediciones_actuales = get_sheet_as_dataframe(
                            spreadsheet, "EDICIONES_USUARIOS"
                        )

                        if not df_ediciones_actuales.empty:
                            df_ediciones_actuales["ID_SERVICIO"] = (
                                df_ediciones_actuales["ID_SERVICIO"].astype(str)
                            )
                        filas_modificadas["ID_SERVICIO"] = filas_modificadas[
                            "ID_SERVICIO"
                        ].astype(str)

                        df_ediciones_final = pd.concat(
                            [df_ediciones_actuales, filas_modificadas]
                        ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

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
elif st.session_state["authentication_status"] == False:
    st.error("Usuario o contraseña incorrecto.")
elif st.session_state["authentication_status"] == None:
    st.warning("Por favor, ingrese su usuario y contraseña para continuar.")
