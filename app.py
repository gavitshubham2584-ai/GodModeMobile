import streamlit as st
import requests
import pandas as pd
import time
import math
from datetime import datetime
import plotly.graph_objects as go
from scipy.stats import norm

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="God Mode Terminal",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- MOBILE OPTIMIZED CSS ---
st.markdown("""
<style>
    .stApp { background-color: #131722; }
    
    /* Global Text Colors */
    h1, h2, h3, h4, h5, p, span, div { color: #d1d4dc !important; }
    
    /* Metric Cards Styling */
    div[data-testid="metric-container"] {
        background-color: #1e222d;
        border: 1px solid #2a2e39;
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    label[data-testid="stMetricLabel"] { color: #b2b5be !important; font-size: 14px !important; }
    div[data-testid="stMetricValue"] { color: #00E396 !important; font-size: 24px !important; }
    div[data-testid="stMetricDelta"] { font-size: 14px !important; }

    /* Mobile Adjustments */
    @media (max-width: 600px) {
        div[data-testid="stMetricValue"] { font-size: 18px !important; }
        .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. SESSION STATE ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=[
        'Time', 'NSE_Adv', 'NSE_Dec', 
        'Coin_Adv', 'Coin_Dec', 
        'BTC_Price', 'BTC_Funding', 'Net_GEX'
    ])
if 'start_oi' not in st.session_state:
    st.session_state.start_oi = 0

# --- 3. HELPER FUNCTIONS ---
def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

def hex_to_rgba(hex_val, opacity):
    h = hex_val.lstrip('#')
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {opacity})"

def calculate_gamma(S, K, T, sigma):
    if T <= 0.001 or sigma <= 0: return 0
    d1 = (math.log(S / K) + (0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    return gamma

@st.cache_data(ttl=10) # Cache data for 10 seconds to prevent API bans
def fetch_data_snapshot():
    data = {}
    status = "OK"
    try:
        # --- A. BYBIT (CRYPTO) ---
        market_url = "https://api.bybit.com/v5/market/tickers?category=linear&limit=1000"
        all_coins = requests.get(market_url, headers=get_headers(), timeout=5).json()
        
        c_adv, c_dec = 0, 0
        btc_price, funding = 0, 0
        
        for t in all_coins['result']['list']:
            if t['symbol'] == 'BTCUSDT':
                btc_price = float(t['lastPrice'])
                funding = float(t['fundingRate']) * 100
            try:
                if float(t['price24hPcnt']) > 0: c_adv += 1
                else: c_dec += 1
            except: continue

        # Long/Short Ratio
        try:
            ls_url = "https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=BTCUSDT&period=5min&limit=1"
            ls_res = requests.get(ls_url, headers=get_headers(), timeout=3).json()
            buy = float(ls_res['result']['list'][0]['buyRatio'])
            sell = float(ls_res['result']['list'][0]['sellRatio'])
            ls_ratio = buy / sell
        except: ls_ratio = 1.0

        # --- B. OPTIONS (GEX) ---
        opt_url = "https://api.bybit.com/v5/market/tickers?category=option&baseCoin=BTC&limit=200" # Reduced limit for speed
        opt_res = requests.get(opt_url, headers=get_headers(), timeout=5).json()
        df = pd.DataFrame(opt_res['result']['list'])
        
        df['openInterest'] = df['openInterest'].astype(float)
        df['bid1Iv'] = df['bid1Iv'].astype(float)
        split_data = df['symbol'].str.split('-', expand=True)
        df[['Coin', 'Date', 'Strike', 'Type']] = split_data.iloc[:, :4]
        df['Strike'] = df['Strike'].astype(float)
        
        # Walls & Max Pain
        call_wall = df[df['Type']=='C'].sort_values('openInterest', ascending=False).iloc[0]['Strike']
        put_wall = df[df['Type']=='P'].sort_values('openInterest', ascending=False).iloc[0]['Strike']
        
        # Simple GEX Approx
        total_gex = 0
        now = datetime.now()
        for _, row in df.iterrows():
            if row['openInterest'] < 0.1 or row['bid1Iv'] <= 0: continue
            try:
                exp_date = datetime.strptime(row['Date'], "%d%b%y")
                T = (exp_date - now).days / 365.0
            except: continue
            if T < 0.001: T = 0.001
            gamma = calculate_gamma(btc_price, row['Strike'], T, row['bid1Iv'])
            gex_val = gamma * row['openInterest'] * btc_price * 100
            total_gex += gex_val if row['Type']=='P' else -gex_val
        
        # Max Pain Calculation (Fast)
        strikes = df['Strike'].unique()
        min_loss = float('inf')
        max_pain = 0
        for k in strikes:
            if k % 1000 != 0: continue # Optimization: Only check round strikes
            c_loss = df[(df['Type']=='C') & (df['Strike'] < k)]
            p_loss = df[(df['Type']=='P') & (df['Strike'] > k)]
            val = ((k - c_loss['Strike']) * c_loss['openInterest']).sum() + \
                  ((p_loss['Strike'] - k) * p_loss['openInterest']).sum()
            if val < min_loss: min_loss = val; max_pain = k

        # --- C. NSE INDIA ---
        try:
            s = requests.Session()
            s.headers.update(get_headers())
            s.get("https://www.nseindia.com", timeout=3)
            nse_res = s.get("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050", timeout=3).json()
            nse_adv = nse_res['advance']['advances']
            nse_dec = nse_res['advance']['declines']
        except: nse_adv, nse_dec = 0, 0

        data = {
            'price': btc_price, 'funding': funding, 'ls_ratio': ls_ratio,
            'coin_adv': c_adv, 'coin_dec': c_dec, 
            'nse_adv': int(nse_adv), 'nse_dec': int(nse_dec),
            'max_pain': max_pain, 'gex': total_gex,
            'call_wall': call_wall, 'put_wall': put_wall,
            'total_oi': df['openInterest'].sum()
        }
    except Exception as e:
        status = f"System Error: {str(e)}"
    
    return data, status

# --- 4. TRADINGVIEW CHART ENGINE ---
def create_tv_chart(df, y1, y2, title, color1, color2):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['Time'], y=df[y1], name='Bulls', 
        line=dict(color=color1, width=2), fill='tozeroy', fillcolor=hex_to_rgba(color1, 0.1)
    ))
    fig.add_trace(go.Scatter(
        x=df['Time'], y=df[y2], name='Bears', 
        line=dict(color=color2, width=2), fill='tozeroy', fillcolor=hex_to_rgba(color2, 0.1)
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color='#d1d4dc', size=14)),
        paper_bgcolor='#1e222d', plot_bgcolor='#131722',
        height=250, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showgrid=True, gridcolor='#2a2e39', tickfont=dict(color='#787b86')),
        yaxis=dict(showgrid=True, gridcolor='#2a2e39', tickfont=dict(color='#787b86')),
        legend=dict(orientation="h", y=1, x=1, font=dict(color='#d1d4dc'))
    )
    return fig

# --- 5. MAIN DASHBOARD ---
st.title("🦅 GOD MODE TERMINAL")

# FETCH
with st.spinner('Syncing...'):
    d, status = fetch_data_snapshot()

if status != "OK":
    st.error(f"⚠️ {status}")
    if st.button("Retry"): st.rerun()
else:
    # HISTORY
    curr_time = datetime.now().strftime("%H:%M")
    new_row = {
        'Time': curr_time, 
        'NSE_Adv': d['nse_adv'], 'NSE_Dec': d['nse_dec'], 
        'Coin_Adv': d['coin_adv'], 'Coin_Dec': d['coin_dec'],
        'BTC_Price': d['price'], 'BTC_Funding': d['funding'], 'Net_GEX': d['gex']
    }
    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_row])], ignore_index=True)
    if len(st.session_state.history) > 60: st.session_state.history = st.session_state.history.iloc[1:]

    if st.session_state.start_oi == 0: st.session_state.start_oi = d['total_oi']
    oi_change = d['total_oi'] - st.session_state.start_oi

    # METRICS
    m1, m2 = st.columns(2)
    with m1: st.metric("BTC PRICE", f"${d['price']:,.0f}", delta=f"{oi_change:,.2f} OI")
    with m2: st.metric("MAX PAIN", f"${d['max_pain']:,.0f}", delta="Magnet")
    
    m3, m4 = st.columns(2)
    with m3: 
        gex_txt = "VOLATILE" if d['gex'] < 0 else "STABLE"
        st.metric("NET GEX", f"${d['gex']/1_000_000:.1f}M", delta=gex_txt, delta_color="normal" if d['gex']>0 else "inverse")
    with m4: st.metric("NSE BREADTH", f"{d['nse_adv']} / {d['nse_dec']}", delta="Bullish" if d['nse_adv']>d['nse_dec'] else "Bearish")

    # SIGNALS
    st.write("---")
    st.markdown("##### 🧱 WALLS & SIGNALS")
    c1, c2 = st.columns(2)
    with c1:
        st.error(f"RESISTANCE: ${d['call_wall']:,.0f}")
        st.success(f"SUPPORT: ${d['put_wall']:,.0f}")
    with c2:
        sig_text, sig_color = "WAITING", "gray"
        if d['price'] < d['max_pain'] and d['ls_ratio'] < 0.9: sig_text, sig_color = "BUY", "green"
        elif d['price'] > d['max_pain'] and d['funding'] > 0.02: sig_text, sig_color = "SELL", "red"
        st.markdown(f"### :{sig_color}[{sig_text}]")

    # CHARTS
    st.write("---")
    st.plotly_chart(create_tv_chart(st.session_state.history, 'Coin_Adv', 'Coin_Dec', "Crypto Market Breadth", '#2962FF', '#FF9800'), use_container_width=True)

    time.sleep(10)
    st.rerun()
          
