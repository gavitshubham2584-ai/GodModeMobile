import streamlit as st
import requests
import pandas as pd
import time
import math
from datetime import datetime
import plotly.graph_objects as go
from scipy.stats import norm

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="God Mode Terminal",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- MOBILE CSS ---
st.markdown("""
<style>
    .stApp { background-color: #131722; }
    h1, h2, h3, h4, h5, p, span, div { color: #d1d4dc !important; }
    div[data-testid="metric-container"] {
        background-color: #1e222d; border: 1px solid #2a2e39; padding: 10px; border-radius: 8px;
    }
    div[data-testid="stMetricValue"] { color: #00E396 !important; font-size: 24px !important; }
    @media (max-width: 600px) {
        div[data-testid="stMetricValue"] { font-size: 18px !important; }
        .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. STATE ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['Time', 'Coin_Adv', 'Coin_Dec', 'BTC_Price'])
if 'start_oi' not in st.session_state:
    st.session_state.start_oi = 0

# --- 3. ROBUST DATA FETCHING ---
def get_safe_json(url):
    """Safely fetch JSON without crashing"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

@st.cache_data(ttl=10)
def fetch_data_snapshot():
    # Default Empty Data (Prevents Crashes)
    data = {
        'price': 0, 'funding': 0, 'ls_ratio': 1.0,
        'coin_adv': 0, 'coin_dec': 0, 
        'max_pain': 0, 'gex': 0,
        'call_wall': 0, 'put_wall': 0,
        'total_oi': 0,
        'source': 'Connecting...'
    }
    
    # --- PLAN A: BYBIT (Best Data) ---
    bybit_data = get_safe_json("https://api.bybit.com/v5/market/tickers?category=linear&limit=1000")
    if bybit_data and 'result' in bybit_data:
        try:
            data['source'] = 'Bybit (Live)'
            c_adv, c_dec = 0, 0
            for t in bybit_data['result']['list']:
                if t['symbol'] == 'BTCUSDT':
                    data['price'] = float(t['lastPrice'])
                    data['funding'] = float(t['fundingRate']) * 100
                try:
                    if float(t['price24hPcnt']) > 0: c_adv += 1
                    else: c_dec += 1
                except: continue
            data['coin_adv'] = c_adv
            data['coin_dec'] = c_dec
            
            # Options (Walls)
            opt_data = get_safe_json("https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC&limit=100")
            if opt_data:
                df = pd.DataFrame(opt_data['result']['list'])
                df['openInterest'] = df['openInterest'].astype(float)
                data['total_oi'] = df['openInterest'].sum()
                
                # Extract Walls
                split = df['symbol'].str.split('-', expand=True)
                df['Type'] = split[3]
                df['Strike'] = split[2].astype(float)
                
                data['call_wall'] = df[df['Type']=='C'].sort_values('openInterest', ascending=False).iloc[0]['Strike']
                data['put_wall'] = df[df['Type']=='P'].sort_values('openInterest', ascending=False).iloc[0]['Strike']
        except:
            pass # Parsing failed, fallback to Plan B

    # --- PLAN B: BINANCE (Backup Price) ---
    if data['price'] == 0:
        binance_data = get_safe_json("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        if binance_data:
            data['price'] = float(binance_data['price'])
            data['source'] = 'Binance (Backup)'

    # --- PLAN C: COINGECKO (Last Resort) ---
    if data['price'] == 0:
        cg_data = get_safe_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        if cg_data:
            data['price'] = cg_data['bitcoin']['usd']
            data['source'] = 'CoinGecko (Slow)'

    # Approximations if data missing
    if data['max_pain'] == 0 and data['price'] > 0:
        data['max_pain'] = round(data['price'] / 1000) * 1000 # Dummy approximation
    
    return data

# --- 4. UI LAYOUT ---
st.title("🦅 GOD MODE TERMINAL")

d = fetch_data_snapshot()

# Update History
curr_time = datetime.now().strftime("%H:%M")
new_row = {'Time': curr_time, 'Coin_Adv': d['coin_adv'], 'Coin_Dec': d['coin_dec'], 'BTC_Price': d['price']}
st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_row])], ignore_index=True)
if len(st.session_state.history) > 60: st.session_state.history = st.session_state.history.iloc[1:]

# Top Metrics
m1, m2 = st.columns(2)
with m1: st.metric("BTC PRICE", f"${d['price']:,.0f}", delta=d['source'])
with m2: st.metric("FUNDING", f"{d['funding']:.4f}%", delta="Normal" if d['funding'] < 0.01 else "High")

m3, m4 = st.columns(2)
with m3: st.metric("RESISTANCE", f"${d['call_wall']:,.0f}" if d['call_wall'] > 0 else "---")
with m4: st.metric("SUPPORT", f"${d['put_wall']:,.0f}" if d['put_wall'] > 0 else "---")

# Chart
st.write("---")
if not st.session_state.history.empty:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=st.session_state.history['Time'], y=st.session_state.history['Coin_Adv'], name='Advancing', line=dict(color='#00E396')))
    fig.add_trace(go.Scatter(x=st.session_state.history['Time'], y=st.session_state.history['Coin_Dec'], name='Declining', line=dict(color='#FF4560')))
    fig.update_layout(title="Market Breath", paper_bgcolor='#1e222d', plot_bgcolor='#131722', font=dict(color='#d1d4dc'))
    st.plotly_chart(fig, use_container_width=True)

time.sleep(10)
st.rerun()
