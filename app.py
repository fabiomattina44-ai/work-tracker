import sqlite3
import datetime
import holidays
import streamlit as st
import pandas as pd
import time
import os
import pytz

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Il Conta Lavoro", page_icon="⏱️", layout="centered")

# --- GESTIONE FUSO ORARIO ITALIANO ---
def get_ita_now():
    """Restituisce l'orario attuale in Italia gestendo fuso e ora legale."""
    tz_ita = pytz.timezone('Europe/Rome')
    return datetime.datetime.now(tz_ita)

# --- GESTIONE DATABASE ---
DB_NAME = "lavoro.db"

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
    
    curr = start_dt.replace(tzinfo=None)
    end_naive = end_dt.replace(tzinfo=None)
    
    while curr < end_naive:
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
st.title("Il Conta Lavoro")

# SIDEBAR BACKUP
with st.sidebar:
    st.header("💾 Gestione Dati")
    if os.path.exists(DB_NAME):
        with open(DB_NAME, "rb") as file:
            st.download_button("⬇️ Scarica Backup (.db)", file, file_name="backup_lavoro.db")
    uploaded_file = st.file_uploader("⬆️ Carica un backup", type="db")
    if uploaded_file is not None:
        if st.button("Sovrascrivi dati attuali"):
            with open(DB_NAME, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success("Ripristinato! Ricarica...")
            time.sleep(2)
            st.rerun()

st.markdown("""<style>div.stButton > button:first-child {height: 3em; font-size: 18px; border-radius: 8px;}</style>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["⏱️", "🗓️", "💰", "⚙️"])

# TAB 1: TRACKER
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
            end_dt = get_ita_now().replace(tzinfo=None)
            
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
            now_ita = get_ita_now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT INTO sessions (start_time) VALUES (?)", (now_ita,))
            conn.commit()
            conn.close()
            st.rerun()

# TAB 2: TURNI (MODIFICATA PER CANCELLAZIONE SINGOLA)
with tab2:
    st.header("Turni")
    conn = get_connection()
    # Recuperiamo anche l'ID per poter cancellare
    df = pd.read_sql("SELECT id, weekday, start_hm, end_hm FROM shifts ORDER BY weekday, start_hm", conn)
    conn.close()
    map_g = {0:"Lunedì", 1:"Martedì", 2:"Mercoledì", 3:"Giovedì", 4:"Venerdì", 5:"Sabato", 6:"Domenica"}
    
    st.write("Turni Attuali:")
    if df.empty:
        st.warning("Nessun turno salvato.")
    else:
        # Loop per creare una riga per ogni turno con bottone elimina
        for index, row in df.iterrows():
            col_info, col_del = st.columns([4, 1])
            giorno_nome = map_g[row['weekday']]
            with col_info:
                st.write(f"**{giorno_nome}**: {row['start_hm']} - {row['end_hm']}")
            with col_del:
                if st.button("🗑️", key=f"del_shift_{row['id']}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM shifts WHERE id=?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.rerun()
        st.divider()

    # Form Aggiunta
    with st.form("add_shift"):
        st.write("➕ Aggiungi Turno")
        d = st.selectbox("Giorno", list(map_g.keys()), format_func=lambda x: map_g[x])
        c1, c2 = st.columns(2)
        s = c1.time_input("Start", datetime.time(9,0))
        e = c2.time_input("End", datetime.time(18,0))
        if st.form_submit_button("Salva Turno"):
            conn = get_connection()
            conn.execute("INSERT INTO shifts (weekday, start_hm, end_hm) VALUES (?,?,?)", (d, s.strftime("%H:%M"), e.strftime("%H:%M")))
            conn.commit()
            conn.close()
            st.rerun()

# TAB 3: STIPENDIO (MODIFICATA PER CANCELLAZIONE SESSIONI)
with tab3:
    st.header("Stipendio")
    mese = st.text_input("Mese", get_ita_now().strftime("%Y-%m"))
    conn = get_connection()
    # Recuperiamo anche l'ID
    df = pd.read_sql("SELECT * FROM sessions WHERE start_time LIKE ? AND end_time IS NOT NULL ORDER BY start_time DESC", conn, params=(f'{mese}%',))
    conn.close()
    
    if not df.empty:
        tot_euro = df['total_pay'].sum()
        tot_min = df['total_minutes'].sum()
        
        c1,c2 = st.columns(2)
        c1.metric("€ Tot", f"{tot_euro:.2f}")
        c2.metric("Ore Tot", f"{tot_min//60}h {tot_min%60}m")
        
        st.divider()
        st.subheader("Dettaglio Sessioni")
        st.caption("Clicca sulla freccia per espandere ed eliminare.")

        # Loop per mostrare expander interattivi
        for index, row in df.iterrows():
            giorno_breve = row['start_time'][5:10] # MM-DD
            ora_breve = row['start_time'][11:16]
            label = f"{giorno_breve} ({ora_breve}) - € {row['total_pay']:.2f}"
            
            with st.expander(label):
                st.write(f"📅 **Inizio:** {row['start_time']}")
                st.write(f"🛑 **Fine:** {row['end_time']}")
                st.write(f"⏱️ **Durata:** {row['total_minutes']//60}h {row['total_minutes']%60}m")
                st.write(f"💰 **Guadagno:** € {row['total_pay']:.2f}")
                
                # Tasto eliminazione singola sessione
                if st.button("❌ Elimina questa sessione", key=f"del_sess_{row['id']}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM sessions WHERE id=?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.success("Cancellata!")
                    time.sleep(1)
                    st.rerun()

        # Generazione TXT
        txt_output = [f"--- RESOCONTO: {mese} ---\n"]
        for _, row in df.iterrows():
            line = f"📅 {row['start_time'][8:10]} | ⏰ {row['start_time'][11:16]}-{row['end_time'][11:16]} | 💰 € {row['total_pay']:.2f}"
            txt_output.append(line)
        txt_output.append("\n" + "="*30)
        txt_output.append(f"TOTALE: € {tot_euro:.2f}")
        st.download_button("📄 Scarica TXT", "\n".join(txt_output), file_name=f"Stipendio_{mese}.txt")

# TAB 4: SETUP
with tab4:
    st.header("Setup")
    def ui(k, l, fl=True):
        v = get_setting(k, float if fl else int)
        n = st.number_input(l, value=v, step=0.5 if fl else 1)
        if n!=v: set_setting(k, n)
    ui("paga_oraria", "Paga Base"); ui("inizio_notturno", "Inizio Notte", False)
    st.caption("Percentuali %"); ui("bonus_festivo", "Festivi"); ui("bonus_domenica", "Domenica"); ui("bonus_notturno", "Notte (Turno)"); ui("str_diurno", "Str. Diurno"); ui("str_notturno", "Str. Notturno")
