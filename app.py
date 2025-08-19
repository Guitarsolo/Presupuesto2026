import streamlit as st
import pandas as pd
import yaml
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader
from google_sheets_connector import connect_to_gsheet, get_sheet_as_dataframe, update_sheet_from_dataframe

# --- CONFIGURACIÓN DE PÁGINA Y TÍTULO ---
st.set_page_config(layout="wide", page_title="App Presupuesto RRHH")
st.title("Sistema de Carga de Presupuesto RRHH 2026")

# --- 1. AUTENTICACIÓN ---
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
)

authenticator.login('main')

# --- 2. LÓGICA DE LA APLICACIÓN POST-LOGIN ---
if st.session_state["authentication_status"]:
    # --- Interfaz de Usuario Principal ---
    name = st.session_state["name"]
    username = st.session_state["username"]
    authenticator.logout(location='sidebar')
    st.sidebar.write(f'Bienvenido/a, **{name}**')
    
    user_saf = config['credentials']['usernames'][username]['saf']
    st.header(f"Planilla de Trabajo - SAF {user_saf}")
    
    spreadsheet = connect_to_gsheet()
    if spreadsheet:
        # --- LECTURA DE FUENTES DE DATOS ---
        # Leemos la base original inmutable
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        # Leemos el registro de cambios hechos por los usuarios
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            # --- PREPARACIÓN Y FUSIÓN DE DATOS ---
            # 1. Filtrar la base original por el SAF del usuario
            df_saf_base = df_original[df_original['SAF'] == user_saf].copy()

            # 2. Renombrar columnas clave para consistencia (ej: si los nombres son diferentes)
            # Asegúrate de que los nombres de columna en tu GSheet sean los mismos.
            if 'idServicioAgente' in df_saf_base.columns:
                 df_saf_base.rename(columns={'idServicioAgente': 'ID_SERVICIO'}, inplace=True)
            
            # 3. FUSIONAR: Combinar los datos originales con las ediciones guardadas
            # Asegurarse de que las claves de unión (ID_SERVICIO) sean del mismo tipo
            df_saf_base['ID_SERVICIO'] = df_saf_base['ID_SERVICIO'].astype(str)
            if not df_ediciones.empty:
                df_ediciones['ID_SERVICIO'] = df_ediciones['ID_SERVICIO'].astype(str)
                # Establecer el ID como índice para actualizar
                df_saf_base = df_saf_base.set_index('ID_SERVICIO')
                df_ediciones_filtradas = df_ediciones.set_index('ID_SERVICIO')
                # La función update es perfecta para esto
                df_saf_base.update(df_ediciones_filtradas)
                # Restaurar el índice
                df_saf_base.reset_index(inplace=True)

            # 4. Ordenar el resultado final para mostrarlo
            df_a_mostrar = df_saf_base.sort_values(by=["Suborganizacion", "Documento"])
            
            # --- DEFINICIÓN DE LA INTERFAZ ---
            # Columnas bloqueadas de la base original
            columnas_bloqueadas = [
                "Documento", "Nombres", "Suborganizacion", "ID_SERVICIO", "cargo", 
                "Agrupamiento", "SituacionRevista", "funcion", "SituacionLaboral", 
                "FORMULARIOS_F4"
            ]
            
            # Columnas editables que el usuario verá
            # Estas deben coincidir con las columnas de tu hoja 'EDICIONES_USUARIOS'
            columnas_editables = [
                "ESTADO", "ORGANISMO ORIGEN ACTUALIZADO", "ADSCRIPTO A OTRO", 
                "ORGANISMO DESTINO DE ADSCRIPTO", "CARGO SUBROGANTE", 
                "CATEGORIA QUE SUBROGA", "AGENTE AFECTADO A OTRO", 
                "ORGANISMO DESTINO DEL AGENTE AFECTADO", "AGENTE AFECTADO DE OTRO",
                "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)", 
                "ACOGIDO A RETIRO VOLUNTARIO", "ACTO ADMINISTRATIVO"
            ]
            
            # Combinar y asegurar que todas las columnas existan en el DataFrame a mostrar
            columnas_visibles = columnas_bloqueadas + columnas_editables
            for col in columnas_visibles:
                if col not in df_a_mostrar.columns:
                    df_a_mostrar[col] = pd.NA # Usar NA de pandas para valores nulos

            # --- RENDERIZADO DEL EDITOR DE DATOS ---
            st.info("A continuación, puede modificar los datos. Los cambios se guardarán por separado sin alterar la base original.")
            
            # Guardamos el estado original (mostrado) para la comparación
            if 'df_mostrado' not in st.session_state:
                st.session_state.df_mostrado = df_a_mostrar
            
            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                num_rows="dynamic",
                key="data_editor_final"
            )
            
            # --- NUEVA LÓGICA DE GUARDADO ---
            if st.button("💾 Guardar Cambios", type="primary"):
                with st.spinner("Comparando cambios y guardando..."):
                    original_mostrado = st.session_state.df_mostrado
                    
                    # Comparar para encontrar solo las filas que han cambiado
                    cambios = original_mostrado.compare(edited_df)
                    
                    if not cambios.empty:
                        # Obtener los ID_SERVICIO de las filas que cambiaron
                        ids_modificados = cambios.index.get_level_values('ID_SERVICIO')
                        
                        # Seleccionar las filas completas y actualizadas desde el dataframe editado
                        filas_para_guardar = edited_df[edited_df['ID_SERVICIO'].isin(ids_modificados)]
                        
                        # Preparar las filas para guardar: seleccionar solo las columnas de 'EDICIONES_USUARIOS'
                        columnas_para_guardar = [col for col in df_ediciones.columns if col in filas_para_guardar.columns]
                        df_a_guardar = filas_para_guardar[columnas_para_guardar].copy()

                        # Añadir la trazabilidad
                        df_a_guardar['USUARIO_QUE_EDITO'] = username
                        df_a_guardar['FECHA_DE_EDICION'] = pd.Timestamp.now()
                        
                        # --- Escribir de vuelta en la hoja de EDICIONES ---
                        # Combina ediciones existentes con las nuevas y elimina duplicados
                        df_ediciones_final = pd.concat([df_ediciones.set_index('ID_SERVICIO'), df_a_guardar.set_index('ID_SERVICIO')]).reset_index()
                        df_ediciones_final.drop_duplicates(subset=['ID_SERVICIO'], keep='last', inplace=True)
                        
                        success = update_sheet_from_dataframe(spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final)

                        if success:
                            st.success("✅ ¡Cambios guardados con éxito!")
                            del st.session_state.df_mostrado # Forzar recarga de datos en el próximo rerun
                            st.experimental_rerun()
                        else:
                            st.error("❌ Ocurrió un error al guardar los cambios.")
                    else:
                        st.info("No se detectaron cambios para guardar.")
else:
    # ... (código de login como antes)