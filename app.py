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
                "Agrupamiento", "SituacionRevista", "FUNCION", "SituacionLaboral", 
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

                        # --- RENDERIZADO DE LA INTERFAZ CON PESTAÑAS ---
            st.info("Utilice la tabla a continuación para editar los datos. Los cambios se guardarán al presionar el botón.")

            # Crear pestañas para organizar la vista
            tab1, tab2 = st.tabs(["📝 Planilla de Trabajo Principal", "📄 Instrucciones"])

            with tab1:
                st.write("### Agentes del SAF")
                
                edited_df = st.data_editor(
                    df_a_mostrar[columnas_visibles],
                    key="data_editor_final",
                    use_container_width=True, # <-- Clave para usar todo el ancho
                    height=600,
                    disabled=columnas_bloqueadas
                )
                
                st.write("") # Espacio
                
                # --- BOTÓN Y LÓGICA DE GUARDADO (Ahora visible y funcional) ---
                if st.button("💾 Guardar Cambios Realizados", type="primary"):
                    with st.spinner("Comparando y guardando los cambios..."):
                        # (La lógica de guardado que ya teníamos va aquí, sin cambios)
                        df_ediciones_actuales = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")
                        if not df_ediciones_actuales.empty:
                            df_ediciones_actuales['ID_SERVICIO'] = df_ediciones_actuales['ID_SERVICIO'].astype(str)

                        # Comparar el DF mostrado original con el editado
                        original_df = st.session_state.get('df_mostrado', pd.DataFrame())
                        
                        # Convertir tipos antes de comparar para evitar errores
                        edited_df['ID_SERVICIO'] = edited_df['ID_SERVICIO'].astype(str)
                        original_df['ID_SERVICIO'] = original_df['ID_SERVICIO'].astype(str)
                        
                        # Usar 'ID_SERVICIO' como índice para una comparación robusta
                        original_indexed = original_df.set_index('ID_SERVICIO')
                        edited_indexed = edited_df.set_index('ID_SERVICIO')
                        
                        # Encontrar los índices donde hay diferencias
                        diff_indices = original_indexed.ne(edited_indexed).any(axis=1)
                        filas_modificadas = edited_df[edited_df['ID_SERVICIO'].isin(diff_indices[diff_indices].index)]

                        if not filas_modificadas.empty:
                            columnas_para_guardar = [col for col in df_ediciones.columns if col in filas_modificadas.columns]
                            df_a_guardar = filas_modificadas[columnas_para_guardar].copy()
                            
                            df_a_guardar['USUARIO_QUE_EDITO'] = username
                            df_a_guardar['FECHA_DE_EDICION'] = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires") # O tu zona horaria
                            
                            df_ediciones_final = pd.concat([df_ediciones_actuales, df_a_guardar]).drop_duplicates(subset=['ID_SERVICIO'], keep='last')
                            
                            success = update_sheet_from_dataframe(spreadsheet, "EDICIONES_USUARIOS", df_ediciones_final)

                            if success:
                                st.success("✅ ¡Cambios guardados con éxito!")
                                st.experimental_rerun()
                            else:
                                st.error("❌ Ocurrió un error al guardar.")
                        else:
                            st.info("No se detectaron cambios para guardar.")

            with tab2:
                st.write("### Guía de Uso")
                st.markdown("""
                - **Edición:** Haga doble clic en cualquier celda de la sección derecha (azul claro) para editar su contenido.
                - **Guardado:** Una vez que haya finalizado todas sus modificaciones, haga clic en el botón azul **"Guardar Cambios Realizados"**.
                - **Trazabilidad:** Cada vez que guarde, su usuario y la fecha quedarán registrados automáticamente.
                - **Adscriptos de Otros:** Utilice el menú `➕ Cargar Adscripto DE Otro Organismo` en la parte superior para registrar agentes que no pertenecen a su planta pero prestan servicios en su SAF.
                """)
else:
    # ... (código de login como antes)