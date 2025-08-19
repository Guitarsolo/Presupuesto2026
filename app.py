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
        # --- LECTURA Y PREPARACIÓN DE DATOS ---
        df_original = get_sheet_as_dataframe(spreadsheet, "BD_CARGOS_COMPLETA")
        df_ediciones = get_sheet_as_dataframe(spreadsheet, "EDICIONES_USUARIOS")

        if not df_original.empty:
            df_saf_base = df_original[df_original["SAF"] == user_saf].copy()
            df_saf_base.rename(
                columns={"idServicioAgente": "ID_SERVICIO"},
                inplace=True,
                errors="ignore",
            )
            df_saf_base.rename(
                columns={"funcion": "FUNCION"},
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

            # --- RENDERIZADO DE LA INTERFAZ CON st.data_editor ---
            st.info(
                "Edite directamente en la tabla. Para evitar la eliminación accidental de registros, no se permite añadir ni borrar filas."
            )

            # Guardamos el DF original mostrado para la comparación posterior
            st.session_state["df_mostrado_al_usuario"] = df_a_mostrar.copy()

            edited_df = st.data_editor(
                df_a_mostrar[columnas_visibles],
                disabled=columnas_bloqueadas,
                # --- CAMBIO CLAVE: IMPEDIR AÑADIR/BORRAR FILAS ---
                num_rows="fixed",
                use_container_width=True,
                height=600,
                key="data_editor_saf_final",
            )

            # --- LÓGICA DE GUARDADO ---
            # --- LÓGICA DE GUARDADO (VERSIÓN FINAL CON MERGE, LA MÁS ROBUSTA) ---
            if st.button("💾 Guardar Cambios Realizados", type="primary"):
                with st.spinner("Procesando y guardando cambios..."):
                    df_original_sesion = st.session_state["df_mostrado_al_usuario"]
                    df_editado = edited_df

                    # --- PREPARACIÓN PARA LA COMPARACIÓN ---
                    # Definir un identificador único por fila. ID_SERVICIO es perfecto.
                    id_columna = "ID_SERVICIO"

                    # Seleccionar solo las columnas editables para encontrar diferencias.
                    # Añadimos la columna ID para saber a qué fila pertenece cada cambio.
                    columnas_a_comparar = [id_columna] + columnas_editables

                    df_original_subset = df_original_sesion[columnas_a_comparar].copy()
                    df_editado_subset = df_editado[columnas_a_comparar].copy()

                    # Asegurar que los tipos de datos sean consistentes antes de la fusión
                    for col in df_original_subset.columns:
                        if df_original_subset[col].dtype == "object":
                            df_original_subset[col] = (
                                df_original_subset[col].astype(str).fillna("")
                            )
                            df_editado_subset[col] = (
                                df_editado_subset[col].astype(str).fillna("")
                            )

                    # --- FUSIÓN PARA DETECTAR CAMBIOS ---
                    # `indicator=True` añade una columna `_merge` que nos dice de dónde vino cada fila.
                    df_merged = pd.merge(
                        df_original_subset,
                        df_editado_subset,
                        on=columnas_a_comparar,
                        how="outer",
                        indicator=True,
                    )

                    # Cambios son las filas que existen solo en el 'df_editado_subset'
                    df_diferencias = pd.merge(
                        df_original_subset,
                        df_editado_subset,
                        on=id_columna,
                        how="outer",
                        suffixes=("_original", "_editado"),
                        indicator=True,
                    )
                    df_cambiados = df_diferencias[
                        df_diferencias["_merge"] == "right_only"
                    ]

                    if not df_cambiados.empty:
                        # Obtenemos los ID_SERVICIO de las filas que tienen cambios.
                        ids_modificados = df_cambiados[id_columna].tolist()

                        # De nuestro DataFrame editado completo, seleccionamos solo las filas que han cambiado.
                        filas_modificadas = df_editado[
                            df_editado[id_columna].isin(ids_modificados)
                        ].copy()

                        # --- VALIDACIÓN (igual que antes) ---
                        if (
                            filas_modificadas["ESTADO"].isnull().any()
                            or (filas_modificadas["ESTADO"] == "").any()
                        ):
                            st.error(
                                "❌ Error de validación: Se detectaron filas modificadas donde 'ESTADO' está vacío. Complete todos los campos 'ESTADO' antes de guardar."
                            )
                        else:
                            # --- PROCEDER CON EL GUARDADO ---
                            filas_modificadas["USUARIO_QUE_EDITO"] = username
                            filas_modificadas["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                tz="America/Argentina/Buenos_Aires"
                            ).strftime("%Y-%m-%d %H:%M:%S")

                            df_ediciones_actuales = get_sheet_as_dataframe(
                                spreadsheet, "EDICIONES_USUARIOS"
                            )

                            if not df_ediciones_actuales.empty:
                                df_ediciones_actuales[id_columna] = (
                                    df_ediciones_actuales[id_columna].astype(str)
                                )
                            filas_modificadas[id_columna] = filas_modificadas[
                                id_columna
                            ].astype(str)

                            df_ediciones_final = pd.concat(
                                [df_ediciones_actuales, filas_modificadas],
                                ignore_index=True,
                            ).drop_duplicates(subset=[id_columna], keep="last")

                            # Alinear columnas antes de guardar para máxima seguridad
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
                                del st.session_state["df_mostrado_al_usuario"]
                                st.rerun()
                            else:
                                st.error("❌ Ocurrió un error al guardar.")
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
