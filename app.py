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
with open("config.yaml") as file: config = yaml.load(file, Loader=SafeLoader)
authenticator = stauth.Authenticate(
    config["credentials"], config["cookie"]["name"],
    config["cookie"]["key"], config["cookie"]["expiry_days"],
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
            # --- PREPARACIÓN Y FUSIÓN DE DATOS (MÉTODO FINAL Y ROBUSTO) ---
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(columns={"idServicioAgente": "ID_SERVICIO", "funcion": "FUNCION"}, inplace=True, errors="ignore")
            
            # ★★★ SOLUCIÓN A DUPLICADOS ★★★
            # Aseguramos que no haya ID_SERVICIO duplicados en la base que vamos a mostrar.
            # Nos quedamos con la primera aparición de cada ID_SERVICIO.
            df_saf_base.drop_duplicates(subset=['ID_SERVICIO'], keep='first', inplace=True)
            
            df_saf_base["ID_SERVICIO"] = df_saf_base["ID_SERVICIO"].astype(str)
            df_a_mostrar = df_saf_base

            if not df_ediciones.empty and "ID_SERVICIO" in df_ediciones.columns:
                df_ediciones["ID_SERVICIO"] = df_ediciones["ID_SERVICIO"].astype(str)
                # Establecer el índice para la fusión. update() es bueno si el índice es único.
                df_a_mostrar.set_index("ID_SERVICIO", inplace=True)
                df_ediciones_a_aplicar = df_ediciones.drop_duplicates(subset=['ID_SERVICIO'], keep='last').set_index("ID_SERVICIO")
                df_a_mostrar.update(df_ediciones_a_aplicar)
                df_a_mostrar.reset_index(inplace=True)

            df_a_mostrar = df_a_mostrar.sort_values(by=["Suborganizacion", "Documento"], ignore_index=True)

            # --- DEFINICIÓN DE LA INTERFAZ ---
            columnas_bloqueadas = [ "Documento", "Nombres", "Suborganizacion", "ID_SERVICIO", "cargo", "Agrupamiento", "SituacionRevista", "FUNCION", "SituacionLaboral", "FORMULARIOS_F4" ]
            columnas_editables = [ "ESTADO", "ORGANISMO ORIGEN ACTUALIZADO", "ADSCRIPTO A OTRO", "ORGANISMO DESTINO DE ADSCRIPTO", "CARGO SUBROGANTE", "CATEGORIA QUE SUBROGA", "AGENTE AFECTADO A OTRO", "ORGANISMO DESTINO DEL AGENTE AFECTADO", "AGENTE AFECTADO DE OTRO", "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)", "ACOGIDO A RETIRO VOLUNTARIO", "ACTO ADMINISTRATIVO" ]
            
            for col in columnas_bloqueadas + columnas_editables:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA
            
            columnas_visibles = columnas_bloqueadas + columnas_editables
            
            # --- RENDERIZADO ---
            st.info("Edite en la tabla. Las filas modificadas se guardarán al presionar el botón.")
            
            st.session_state['df_mostrado'] = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas, num_rows="fixed",
                use_container_width=True, height=600, key="editor"
            )

            # --- LÓGICA DE GUARDADO ---
            if st.button("💾 Guardar Cambios", type="primary"):
                with st.spinner("Procesando..."):
                    # La lógica de guardado con comparación manual es la más segura y se mantiene
                    df_original_sesion = st.session_state['df_mostrado']
                    
                    indices_modificados = []
                    df_comp_orig = df_original_sesion.fillna("__NULL__").astype(str)
                    df_comp_edit = edited_df.fillna("__NULL__").astype(str)

                    for i in range(len(df_comp_edit)):
                        if not df_comp_orig.iloc[i].equals(df_comp_edit.iloc[i]):
                            indices_modificados.append(i)

                    if indices_modificados:
                        # ... (El resto de tu lógica de guardado es correcta y se mantiene igual)
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