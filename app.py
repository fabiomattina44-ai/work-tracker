import sqlite3
import datetime
import holidays
import streamlit as st
import pandas as pd
import time
import os
import pytz

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Work Tracker", page_icon="⏱️", layout="centered")

# --- GESTIONE DATABASE ---
DB_NAME = "lavoro.db"

def get_now_it():
    # Ottiene l'ora corrente con fuso orario Roma
    tz = pytz.timezone('Europe/Rome')
    now_aware = datetime.datetime.now(tz)
    # Rimuove le info sul fuso (tzinfo) per renderlo compatibile 
    # con i calcoli "naive" e con SQLite che hai già scritto.
    # Restituisce un oggetto datetime "pulito" ma con l'orario giusto.
    return now_aware.replace(tzinfo=None)

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT, end_time TEXT, total_minutes INTEGER, total_pay REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, weekday INTEGER, start_hm TEXT, end_hm TEXT)''')
    defaults = {"paga_oraria": "7.80", "inizio_notturno": "22", "bonus_notturno": "20.0",
                "bonus_festivo": "30.0", "bonus_domenica": "10.0", "str_diurno": "25.0", "str_notturno": "50.0"}
    for key, val in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()
    conn.close()

def get_setting(key, type_func=str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = c.fetchone()
    conn.close()
    return type_func(res[0]) if res else None

def set_setting(key, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- MOTORE DI CALCOLO ---
def is_in_turno_previsto(dt):
    wd = dt.weekday()
    time_str = dt.strftime("%H:%M")
    conn = get_connection()
    shifts = conn.cursor().execute("SELECT start_hm, end_hm FROM shifts WHERE weekday = ?", (wd,)).fetchall()
    conn.close()
    for start, end in shifts:
        if start <= end:
            if start <= time_str < end: return True
        else:
            if time_str >= start or time_str < end: return True
    return False

def calcola_guadagno_sessione(start_dt, end_dt):
    paga_base_min = get_setting("paga_oraria", float) / 60
    inizio_notturno = get_setting("inizio_notturno", int)
    b_notte = get_setting("bonus_notturno", float) / 100.0
    b_fest = get_setting("bonus_festivo", float) / 100.0
    b_dom = get_setting("bonus_domenica", float) / 100.0
    b_str_d = get_setting("str_diurno", float) / 100.0
    b_str_n = get_setting("str_notturno", float) / 100.0
    
    totale = 0.0
    it_holidays = holidays.IT()
    curr = start_dt
    while curr < end_dt:
        mult = 1.0
        ora = curr.hour
        is_notte = (inizio_notturno < 6 and inizio_notturno <= ora < 6) or (inizio_notturno >= 6 and (ora >= inizio_notturno or ora < 6))
        is_fest = curr in it_holidays
        is_dom = curr.weekday() == 6
        in_turno = is_in_turno_previsto(curr)
        
        if in_turno:
            if is_notte: mult += b_notte
        else:
            if is_notte: mult += b_str_n
            else: mult += b_str_d
        if is_fest: mult += b_fest
        if is_dom and in_turno: mult += b_dom
        
        totale += (paga_base_min * mult)
        curr += datetime.timedelta(minutes=1)
    return round(totale, 2)

# --- INTERFACCIA ---
init_db()
st.title("📱 Work Tracker Pro")

# SIDEBAR PER BACKUP DATI
with st.sidebar:
    st.header("💾 Gestione Dati")
    st.info("I server gratuiti possono resettarsi. Scarica spesso il backup!")
    
    # Download
    if os.path.exists(DB_NAME):
        with open(DB_NAME, "rb") as file:
            st.download_button("⬇️ Scarica Backup (.db)", file, file_name="backup_lavoro.db")
    
    # Upload
    uploaded_file = st.file_uploader("⬆️ Carica un backup", type="db")
    if uploaded_file is not None:
        if st.button("Sovrascrivi dati attuali"):
            with open(DB_NAME, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success("Database ripristinato! Ricarica la pagina.")
            time.sleep(2)
            st.rerun()

# CSS Mobile
st.markdown("""<style>div.stButton > button:first-child {height: 3em; font-size: 20px; border-radius: 10px;}</style>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["⏱️", "🗓️", "💰", "⚙️"])

with tab1:
    st.header("Tracker")
    conn = get_connection()
    active = conn.cursor().execute("SELECT id, start_time FROM sessions WHERE end_time IS NULL").fetchone()
    conn.close()
    
    if active:
        st.info(f"Iniziato: {active[1][11:16]}")
        if st.button("⏹️ FERMA", type="primary", use_container_width=True):
            conn = get_connection()
            start_dt = datetime.datetime.strptime(active[1], "%Y-%m-%d %H:%M:%S")
            end_dt = get_now_it()
            mins = int((end_dt - start_dt).total_seconds() / 60)
            if mins < 1:
                conn.execute("DELETE FROM sessions WHERE id=?", (active[0],))
                st.warning("Annullato (<1m)")
            else:
                pay = calcola_guadagno_sessione(start_dt, end_dt)
                conn.execute("UPDATE sessions SET end_time=?, total_minutes=?, total_pay=? WHERE id=?", 
                             (end_dt.strftime("%Y-%m-%d %H:%M:%S"), mins, pay, active[0]))
                conn.commit()
                st.success(f"Guadagno: € {pay:.2f}")
                time.sleep(2)
            conn.close()
            st.rerun()
    else:
        if st.button("▶️ AVVIA", type="primary", use_container_width=True):
            conn = get_connection()
            conn.execute("INSERT INTO sessions (start_time) VALUES (?)", (get_now_it().strftime("%Y-%m-%d %H:%M:%S"),))
            conn.commit()
            conn.close()
            st.rerun()

with tab2:
    st.header("Turni")
    conn = get_connection()
    df = pd.read_sql("SELECT weekday, start_hm, end_hm FROM shifts ORDER BY weekday, start_hm", conn)
    conn.close()
    map_g = {0:"Lunedì", 1:"Martedì", 2:"Mercoledì", 3:"Giovedì", 4:"Venerdì", 5:"Sabato", 6:"Domenica"}
    if not df.empty:
        df["Giorno"] = df["weekday"].map(map_g)
        st.dataframe(df[["Giorno", "start_hm", "end_hm"]], hide_index=True, use_container_width=True)
    else: st.warning("Nessun turno (Tutto Straordinario)")
    
    col_del, col_add = st.columns([1,2])
    with col_del:
        if st.button("🗑️ Reset"):
            conn=get_connection(); conn.execute("DELETE FROM shifts"); conn.commit(); conn.close(); st.rerun()
    with col_add:
        with st.form("a"):
            d=st.selectbox("Giorno", list(map_g.keys()), format_func=lambda x: map_g[x])
            c1,c2=st.columns(2)
            s=c1.time_input("Start", datetime.time(9,0)); e=c2.time_input("End", datetime.time(18,0))
            if st.form_submit_button("Salva"):
                conn=get_connection()
                conn.execute("INSERT INTO shifts (weekday, start_hm, end_hm) VALUES (?,?,?)", (d, s.strftime("%H:%M"), e.strftime("%H:%M")))
                conn.commit(); conn.close(); st.rerun()

with tab3:
    st.header("Stipendio")
    mese = st.text_input("Mese", get_now_it().strftime("%Y-%m"))
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM sessions WHERE start_time LIKE ? AND end_time IS NOT NULL ORDER BY start_time DESC", conn, params=(f'{mese}%',))
    conn.close()
    if not df.empty:
        c1,c2 = st.columns(2)
        c1.metric("€ Tot", f"{df['total_pay'].sum():.2f}")
        c2.metric("Ore Tot", f"{df['total_minutes'].sum()//60}h {df['total_minutes'].sum()%60}m")
        st.dataframe(df[["start_time", "end_time", "total_pay"]], use_container_width=True)

with tab4:
    st.header("Setup")
    def ui(k, l, fl=True):
        v = get_setting(k, float if fl else int)
        n = st.number_input(l, value=v, step=0.5 if fl else 1)
        if n!=v: set_setting(k, n)
    ui("paga_oraria", "Paga Base"); ui("inizio_notturno", "Inizio Notte", False)
    st.caption("Percentuali %"); ui("bonus_festivo", "Festivi"); ui("bonus_domenica", "Domenica"); ui("bonus_notturno", "Notte (Turno)"); ui("str_diurno", "Str. Diurno"); ui("str_notturno", "Str. Notturno")