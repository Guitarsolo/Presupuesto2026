import streamlit as st
import gspread
import pandas as pd
from gspread_dataframe import set_with_dataframe


# La anotación @st.cache_resource asegura que solo nos conectemos a GSheets una vez.
@st.cache_resource
def connect_to_gsheet():
    """Establece la conexión con Google Sheets usando los secrets de Streamlit."""
    try:
        creds = st.secrets["gcp_service_account"]
        sa = gspread.service_account_from_dict(creds)
        spreadsheet = sa.open("Control Presupuesto 2026")  # <-- VERIFICA ESTE NOMBRE
        return spreadsheet
    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return None


# La anotación @st.cache_data guarda los datos en caché para no sobrecargar la API.
@st.cache_data(ttl="10m")  # Los datos se actualizan cada 10 minutos
def get_sheet_as_dataframe(_spreadsheet, sheet_name):
    """Obtiene una hoja específica como un DataFrame de pandas."""
    if _spreadsheet:
        try:
            worksheet = _spreadsheet.worksheet(sheet_name)
            # .get_all_records() es genial porque usa la primera fila como encabezados
            df = pd.DataFrame(worksheet.get_all_records())
            return df
        except gspread.exceptions.WorksheetNotFound:
            st.warning(f"La hoja '{sheet_name}' no fue encontrada.")
            return pd.DataFrame()
        except Exception as e:
            st.error(f"Error al leer la hoja '{sheet_name}': {e}")
            return pd.DataFrame()
    return pd.DataFrame()


def update_sheet_from_dataframe(_spreadsheet, sheet_name, df):
    """Actualiza una hoja completa con los datos de un DataFrame."""
    if _spreadsheet:
        try:
            worksheet = _spreadsheet.worksheet(sheet_name)
            worksheet.clear()  # Limpia la hoja antes de escribir
            set_with_dataframe(worksheet, df)
            # Importante: Limpia la caché para que la próxima lectura traiga los datos nuevos
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"Error al actualizar la hoja '{sheet_name}': {e}")
            return False
    return False
