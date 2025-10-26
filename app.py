import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import os
import altair as alt
import json  # ¡MUY IMPORTANTE!

# --- Conexión a Firebase (a prueba de despliegues) ---
def connect_to_firebase():
    """
    Se conecta a Firebase usando credenciales locales 
    (service-account-key.json) o de Streamlit Secrets.
    """
    if firebase_admin._apps:
        # Si ya está inicializado, no hacer nada
        return
    
    try:
        if os.path.exists("service-account-key.json"):
            # --- MODO LOCAL ---
            cred_path = "service-account-key.json"
            cred = credentials.Certificate(cred_path)
            st.sidebar.success("Credencial local cargada 🔑", icon="🔑")
        else:
            # --- MODO NUBE (Streamlit Cloud) ---
            st.sidebar.info("Modo Nube. Buscando secretos...")
            
            # 1. Carga el secreto como un string de texto
            # Usamos un NUEVO nombre de secreto para estar seguros
            cred_json_str = st.secrets["firebase_creds_json"]
            
            if not cred_json_str:
                st.error("El secreto 'firebase_creds_json' está vacío.")
                st.stop()
                
            # 2. Convierte (parsea) el string de texto a un diccionario
            cred_dict = json.loads(cred_json_str)
            
            # 3. Usa el diccionario para crear la credencial
            cred = credentials.Certificate(cred_dict)
            st.sidebar.success("Credencial de nube cargada ☁️", icon="☁️")
        
        # Inicializa la app de Firebase
        firebase_admin.initialize_app(cred)

    except KeyError as e:
        st.error(f"Error: No se encontró el secreto 'firebase_creds_json'.")
        st.info("Asegúrate de haber pegado el bloque TOML en 'Settings > Secrets' y haber guardado.")
        st.stop()
    except json.JSONDecodeError as e:
        st.error(f"Error al decodificar el JSON del secreto: {e}")
        st.info("El JSON pegado en los secretos parece estar corrupto o incompleto.")
        st.stop()
    except Exception as e:
        st.error(f"Error inesperado al inicializar Firebase: {e}")
        st.stop()

# --- Conexión (se ejecuta al inicio) ---
connect_to_firebase()

# Conectamos a la base de datos
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Error al conectar con la base de datos Firestore: {e}")
    st.stop()

# --- Configuración de la Página ---
st.set_page_config(page_title="Dashboard SIOMA", layout="wide")
st.title("🛰️ Dashboard de Sincronización (SIOMA)")
st.write("Visualización de los registros de entrada/salida sincronizados desde la App Android.")

# --- Cargar Datos ---
@st.cache_data(ttl=60)
def load_data():
    try:
        logs_ref = db.collection("work_logs").order_by("timestamp", direction=firestore.Query.DESCENDING)
        docs = logs_ref.stream()

        logs_list = []
        for doc in docs:
            log = doc.to_dict()
            log['firebase_id'] = doc.id
            if 'timestamp' in log and hasattr(log['timestamp'], 'to_datetime'):
                 log['timestamp'] = log['timestamp'].to_datetime().astimezone()
            logs_list.append(log)

        if not logs_list:
            return pd.DataFrame() 

        df = pd.DataFrame(logs_list)
        
        columns_order = ['timestamp', 'workerName', 'eventType', 'synced', 'id', 'firebase_id'] 
        existing_cols = [col for col in columns_order if col in df.columns]
        
        if 'timestamp' not in df.columns:
            st.warning("La colección 'work_logs' no contiene la columna 'timestamp'.")
            return pd.DataFrame()
            
        return df[existing_cols]
        
    except Exception as e:
        st.error(f"Error al cargar datos desde Firestore: {e}")
        return pd.DataFrame()

# --- Mostrar Dashboard ---
df_logs = load_data()

if df_logs.empty:
    st.warning("No se han sincronizado registros desde la App todavía o hubo un error al cargar datos.")
else:
    # --- Preparación de Datos y Filtros ---
    global_max_y = 0
    df_logs['timestamp'] = pd.to_datetime(df_logs['timestamp'])
    df_timeline_unfiltered = df_logs.copy().set_index('timestamp')
    activity_by_day_unfiltered = df_timeline_unfiltered.resample('D').size()
    if not activity_by_day_unfiltered.empty:
        global_max_y = int(activity_by_day_unfiltered.max()) + 2 

    st.sidebar.header("Filtros del Dashboard")

    all_workers = sorted(df_logs['workerName'].unique())
    select_all_workers = st.sidebar.checkbox("Seleccionar Todos los Trabajadores", value=True)
    default_workers = all_workers if select_all_workers else []
    selected_workers = st.sidebar.multiselect("Trabajador", options=all_workers, default=default_workers)

    all_events = sorted(df_logs['eventType'].unique())
    selected_events = st.sidebar.multiselect("Tipo de Evento", options=all_events, default=all_events)

    min_date = df_logs['timestamp'].min().date()
    max_date = df_logs['timestamp'].max().date()
    selected_date_range = st.sidebar.date_input("Rango de Fechas", value=(min_date, max_date), min_value=min_date, max_value=max_date, format="YYYY/MM/DD")
    
    start_date, end_date = min_date, max_date
    if len(selected_date_range) == 2:
        start_date, end_date = selected_date_range
    else:
         st.sidebar.warning("Por favor, selecciona un rango de fechas (inicio y fin).")
         st.stop()

    # --- Aplicación de Filtros ---
    df_filtered = df_logs[
        (df_logs['workerName'].isin(selected_workers)) &
        (df_logs['eventType'].isin(selected_events)) &
        (df_logs['timestamp'].dt.date >= start_date) &
        (df_logs['timestamp'].dt.date <= end_date)
    ]
    
    if df_filtered.empty:
        st.info("No hay datos que coincidan con los filtros seleccionados.")
    else:
        st.header("Estadísticas Clave (KPIs)")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(label="Total Registros", value=len(df_filtered))
        col2.metric(label="Total Entradas", value=len(df_filtered[df_filtered['eventType'] == 'entrada']))
        col3.metric(label="Total Salidas", value=len(df_filtered[df_filtered['eventType'] == 'salida']))
        col4.metric(label="Trabajadores Únicos", value=df_filtered['workerName'].nunique())

        st.divider()

        st.header("Visualización de Datos")
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.subheader("Distribución de Eventos")
            event_counts = df_filtered['eventType'].value_counts().reset_index()
            event_counts.columns = ['Tipo de Evento', 'Cantidad']
            pie_chart = alt.Chart(event_counts).mark_arc(outerRadius=120).encode(
                theta=alt.Theta("Cantidad:Q", stack=True),
                color=alt.Color("Tipo de Evento:N", legend=alt.Legend(title="Tipo de Evento")),
                tooltip=["Tipo de Evento", "Cantidad"]
            ).properties(title='Distribución de Tipos de Evento')
            st.altair_chart(pie_chart, use_container_width=True)

        with col_chart2:
            st.subheader("Registros por Trabajador")
            activity_by_worker = df_filtered.groupby('workerName').size().sort_values(ascending=False).reset_index(name='Registros')
            bar_chart = alt.Chart(activity_by_worker).mark_bar(color="#008080").encode(
                x=alt.X('workerName:N', title='Trabajador', sort='-y'),
                y=alt.Y('Registros:Q', title='Cantidad de Registros'),
                tooltip=['workerName', 'Registros']
            ).properties(title='Registros Totales por Trabajador').interactive()
            st.altair_chart(bar_chart, use_container_width=True)

        st.subheader("Actividad a lo largo del Tiempo")
        activity_by_day = df_filtered.set_index('timestamp').resample('D').size().reset_index(name='Registros')
        line_chart = alt.Chart(activity_by_day).mark_line(point=True).encode(
            x=alt.X('timestamp:T', title='Fecha'),
            y=alt.Y('Registros:Q', title='Número de Registros', scale=alt.Scale(domain=[0, global_max_y])),
            tooltip=[alt.Tooltip('timestamp:T', title='Fecha', format='%Y-%m-%d'), 'Registros:Q']
        ).properties(title='Registros Diarios a lo largo del Tiempo').interactive()
        st.altair_chart(line_chart, use_container_width=True)

        st.divider()
        
        st.header("Registros Detallados (Filtrados)")
        cols_to_show = ['timestamp', 'workerName', 'eventType', 'id']
        display_df = df_filtered[[col for col in cols_to_show if col in df_filtered.columns]]
        display_df['timestamp'] = display_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        st.dataframe(display_df.sort_values('timestamp', ascending=False), use_container_width=True)

if st.button("Recargar Datos"):
    st.cache_data.clear()
    st.rerun()