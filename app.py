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

            # --- RENDERIZADO DE LA INTERFAZ ---
            st.info(
                "La siguiente tabla muestra la nómina de agentes de su SAF. Seleccione un agente del menú desplegable para editar su información."
            )

            # Mostrar la tabla como de solo lectura (excepto el índice que es útil)
            st.dataframe(df_a_mostrar, use_container_width=True, hide_index=True)
            st.divider()

            # --- FORMULARIO DE EDICIÓN ---
            # Crear una lista legible para que el usuario seleccione al agente
            df_a_mostrar["display"] = (
                df_a_mostrar["Nombres"]
                + " (DNI: "
                + df_a_mostrar["Documento"].astype(str)
                + ")"
            )
            agente_seleccionado_display = st.selectbox(
                "**Paso 1: Seleccione un agente para editar sus datos**",
                options=["---"] + df_a_mostrar["display"].tolist(),
                index=0,
            )

            if agente_seleccionado_display != "---":
                # Encontrar la fila completa de datos del agente seleccionado
                datos_agente = df_a_mostrar[
                    df_a_mostrar["display"] == agente_seleccionado_display
                ].iloc[0]

                with st.form(key=f"form_{datos_agente['ID_SERVICIO']}"):
                    st.subheader(f"📝 Editando a: {datos_agente['Nombres']}")
                    st.write(
                        "Complete o corrija los siguientes campos. Los campos marcados con * son obligatorios."
                    )

                    # ---- RENDERIZAR CAMPOS DEL FORMULARIO ----
                    # Leer listas de opciones desde la hoja PARAMS
                    df_params = get_sheet_as_dataframe(spreadsheet, "PARAMETROS")

                    # Columna 1
                    col1, col2 = st.columns(2)
                    with col1:
                        # Campo ESTADO (obligatorio)
                        estados_validos = df_params["ESTADOS_VALIDOS"].dropna().tolist()
                        estado_actual = datos_agente.get("ESTADO")
                        indice_estado = (
                            estados_validos.index(estado_actual)
                            if estado_actual in estados_validos
                            else 0
                        )
                        nuevo_estado = st.selectbox(
                            "ESTADO *", options=estados_validos, index=indice_estado
                        )

                        nuevo_adscripto = st.checkbox(
                            "ADSCRIPTO A OTRO",
                            value=bool(datos_agente.get("ADSCRIPTO A OTRO")),
                        )
                        nuevo_org_destino_adscripto = st.text_input(
                            "ORGANISMO DESTINO DE ADSCRIPTO",
                            value=datos_agente.get(
                                "ORGANISMO DESTINO DE ADSCRIPTO", ""
                            ),
                        )

                        nuevo_subrogante = st.checkbox(
                            "SITUACIÓN SUBROGANTE",
                            value=bool(datos_agente.get("SITUACIÓN SUBROGANTE")),
                        )
                        categorias_validas = (
                            df_params["CATEGORIAS_SUBROGANCIA"].dropna().tolist()
                        )
                        categoria_actual = datos_agente.get("CATEGORIA QUE SUBROGA")
                        indice_cat = (
                            categorias_validas.index(categoria_actual)
                            if categoria_actual in categorias_validas
                            else 0
                        )
                        nueva_cat_subroga = st.selectbox(
                            "CATEGORIA QUE SUBROGA",
                            options=categorias_validas,
                            index=indice_cat,
                        )

                    with col2:
                        nuevo_org_actualizado = st.text_input(
                            "ORGANISMO ORIGEN ACTUALIZADO",
                            value=datos_agente.get("ORGANISMO ORIGEN ACTUALIZADO", ""),
                        )

                        nuevo_afectado_a = st.checkbox(
                            "AGENTE AFECTADO A OTRO",
                            value=bool(datos_agente.get("AGENTE AFECTADO A OTRO")),
                        )
                        nuevo_org_destino_afectado = st.text_input(
                            "ORGANISMO DESTINO DEL AGENTE AFECTADO",
                            value=datos_agente.get(
                                "ORGANISMO DESTINO DEL AGENTE AFECTADO", ""
                            ),
                        )

                        nuevo_afectado_de = st.checkbox(
                            "AGENTE AFECTADO DE OTRO",
                            value=bool(datos_agente.get("AGENTE AFECTADO DE OTRO")),
                        )
                        nuevo_org_origen_afectado = st.text_input(
                            "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)",
                            value=datos_agente.get(
                                "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)",
                                "",
                            ),
                        )

                        nuevo_retiro = st.checkbox(
                            "ACOGIDO A RETIRO VOLUNTARIO",
                            value=bool(datos_agente.get("ACOGIDO A RETIRO VOLUNTARIO")),
                        )

                    nuevo_acto_admin = st.text_area(
                        "ACTO ADMINISTRATIVO",
                        value=datos_agente.get("ACTO ADMINISTRATIVO", ""),
                    )

                    # Botón de guardado DENTRO del formulario
                    submitted = st.form_submit_button(
                        "💾 Guardar Cambios para este Agente"
                    )

                    if submitted:
                        # --- LÓGICA DE GUARDADO (PARA UNA SOLA FILA) ---
                        if not nuevo_estado:
                            st.error(
                                "El campo ESTADO es obligatorio. No se guardaron los cambios."
                            )
                        else:
                            with st.spinner("Guardando..."):
                                # Crear un DataFrame de una sola fila con los datos originales
                                fila_modificada = datos_agente.to_frame().T

                                # Actualizar la fila con los nuevos valores del formulario
                                fila_modificada["ESTADO"] = nuevo_estado
                                fila_modificada["ORGANISMO ORIGEN ACTUALIZADO"] = (
                                    nuevo_org_actualizado
                                )
                                fila_modificada["ADSCRIPTO A OTRO"] = nuevo_adscripto
                                fila_modificada["ORGANISMO DESTINO DE ADSCRIPTO"] = (
                                    nuevo_org_destino_adscripto
                                )
                                fila_modificada["SITUACIÓN SUBROGANTE"] = (
                                    nuevo_subrogante
                                )
                                fila_modificada["CATEGORIA QUE SUBROGA"] = (
                                    nueva_cat_subroga
                                )
                                fila_modificada["AGENTE AFECTADO A OTRO"] = (
                                    nuevo_afectado_a
                                )
                                fila_modificada[
                                    "ORGANISMO DESTINO DEL AGENTE AFECTADO"
                                ] = nuevo_org_destino_afectado
                                fila_modificada["AGENTE AFECTADO DE OTRO"] = (
                                    nuevo_afectado_de
                                )
                                fila_modificada[
                                    "ORGANISMO ORIGEN DEL AGENTE AFECTADO (DE DONDE VIENE)"
                                ] = nuevo_org_origen_afectado
                                fila_modificada["ACOGIDO A RETIRO VOLUNTARIO"] = (
                                    nuevo_retiro
                                )
                                fila_modificada["ACTO ADMINISTRATIVO"] = (
                                    nuevo_acto_admin
                                )
                                fila_modificada["USUARIO_QUE_EDITO"] = username
                                fila_modificada["FECHA_DE_EDICION"] = pd.Timestamp.now(
                                    tz="America/Argentina/Buenos_Aires"
                                ).strftime("%Y-%m-%d %H:%M:%S")

                                # Combinar con las ediciones existentes
                                df_ediciones_final = pd.concat(
                                    [df_ediciones, fila_modificada]
                                ).drop_duplicates(subset=["ID_SERVICIO"], keep="last")

                                # Guardar de vuelta en Google Sheets
                                success = update_sheet_from_dataframe(
                                    spreadsheet,
                                    "EDICIONES_USUARIOS",
                                    df_ediciones_final,
                                )

                                if success:
                                    st.success(
                                        f"¡Datos de {datos_agente['Nombres']} guardados con éxito!"
                                    )
                                    st.cache_data.clear()  # Limpiar caché para forzar la recarga
                                    st.rerun()
                                else:
                                    st.error("❌ Ocurrió un error al guardar.")
        else:
            st.error("No se encontraron datos en la hoja 'BD_CARGOS_COMPLETA'.")
    else:
        st.error("Falló la conexión con Google Sheets.")

# --- Manejo de casos de autenticación fallida o pendiente ---
elif st.session_state["authentication_status"] is False:
    st.error("Usuario o contraseña incorrecto.")
elif st.session_state["authentication_status"] is None:
    st.warning("Por favor, ingrese su usuario y contraseña para continuar.")
