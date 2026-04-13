import streamlit as st
import pandas as pd
import requests
import pytz
import datetime
import time
from openai import OpenAI
import mojito


import os
from dotenv import load_dotenv

# Load environment variables
env_loaded = load_dotenv()

# 한국투자증권 Open API 모의투자 URL
KIS_MOCK_URL = "https://openapivts.koreainvestment.com:29443"

# Load settings from environment variables
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
LLM_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
LLM_MODEL = os.getenv("LM_STUDIO_MODEL", "meta-llama-3.1-8b-instruct")
KIS_CANO = os.getenv("KIS_CANO", "")
KIS_ACRP = os.getenv("KIS_ACRP", "01")
KIS_MOCK = os.getenv("KIS_MOCK", "True") == "True"


def get_access_token(app_key, app_secret):
    if not app_key or not app_secret:
        return None
    url = f"{KIS_MOCK_URL}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    try:
        res = requests.post(url, headers=headers, json=body, timeout=15)
        if res.status_code == 200:
            return res.json().get("access_token")
        else:
            st.error(f"토큰 발급 실패: {res.text}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"🌐 KIS API 연결 오류: {e}")
        return None

def get_mojito_instance():
    """mojito2 인스턴스 생성"""
    if not all([KIS_APP_KEY, KIS_APP_SECRET, KIS_CANO]):
        return None
    
    # mojito2는 '앞8자리-뒤2자리' 형식을 기대함
    acc_no_combined = f"{KIS_CANO}-{KIS_ACRP}"
    
    return mojito.KoreaInvestment(
        api_key=KIS_APP_KEY,
        api_secret=KIS_APP_SECRET,
        acc_no=acc_no_combined,
        mock=KIS_MOCK
    )

def check_us_market_status():
    us_tz = pytz.timezone('US/Eastern')
    now = datetime.datetime.now(us_tz)
    if now.weekday() >= 5: return False, now
    start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    end_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return start_time <= now <= end_time, now

def check_kr_market_status():
    kr_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kr_tz)
    if now.weekday() >= 5: return False, now
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time, now

    return start_time <= now <= end_time, now

def get_tick_size(price):
    """한국 주식 호가 단위 계산"""
    if price < 2000: return 1
    elif price < 5000: return 5
    elif price < 20000: return 10
    elif price < 50000: return 50
    elif price < 200000: return 100
    elif price < 500000: return 500
    else: return 1000

@st.cache_data
def get_krx_ticker_list():
    """KRX 종목 리스트를 가져와서 이름-코드 매핑 생성"""
    try:
        # FinanceDataReader와 유사하게 KIND에서 제공하는 리스트를 활용하거나 공공 데이터 활용
        # 여기서는 안정적인 동작을 위해 상위 시총 종목 위주로 매핑하거나, 실시간 조회를 시도
        # (임시) 자주 쓰이는 주요 종목 매핑
        common_stocks = {
            "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
            "삼성바이오로직스": "207940", "현대차": "005380", "기아": "000270",
            "셀트리온": "068270", "KB금융": "105560", "NAVER": "035420", "네이버": "035420",
            "카카오": "035720", "신한지주": "055550", "포스코홀딩스": "005490", "POSCO홀딩스": "005490",
            "에코프로비엠": "247540", "에코프로": "086520", "HLB": "028300"
        }
        return common_stocks
    except:
        return {}

def get_kr_stock_code(search_term):
    search_term = search_term.strip()
    if search_term.isdigit() and len(search_term) == 6:
        return search_term
    
    mapping = get_krx_ticker_list()
    # 부분 일치 검색
    for name, code in mapping.items():
        if search_term == name:
            return code
    return None

def fetch_kr_daily_data(token, app_key, app_secret, ticker, debug_container=None):
    """
    국내주식 일봉 차트 조회 (FHKST03010100)
    """
    url = f"{KIS_MOCK_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    end_dt = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(days=100)
    
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST03010100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": start_dt.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end_dt.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=15)
        data = res.json()
        rt_cd = data.get("rt_cd", "N/A")
        msg1 = data.get("msg1", "")
        rows_data = data.get("output2", [])
        
        if res.status_code == 200 and rt_cd == "0" and len(rows_data) > 0:
            df = pd.DataFrame(rows_data).head(60)
            # 국내 주식 필드명: stck_bsop_date(날짜), stck_clpr(종가), acml_vol(거래량)
            df = df[['stck_bsop_date', 'stck_clpr', 'acml_vol']].copy()
            df.columns = ['Date', 'Close', 'Volume']
            df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df = df.dropna().sort_values('Date').reset_index(drop=True)
            return df, data.get("output1", {})
    except Exception as e:
        if debug_container:
            debug_container.error(f"국내 데이터 수집 예외: {e}")
    return None, None

def fetch_daily_data(token, app_key, app_secret, ticker, debug_container=None):
    """
    해외주식 일자별 종가 조회 (FID 계열 파라미터 사용)
    """
    url = f"{KIS_MOCK_URL}/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
    end_dt = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(days=90)
    debug_lines = []
    exchanges = ["NAS", "NYS", "AMX"]

    for excd in exchanges:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "HHDFS76240000",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "N",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_dt.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_dt.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "AUTH": "",
            "EXCD": excd,
            "SYMB": ticker,
            "GUBN": "0",
            "BYMD": "",
            "MODP": "1",
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=15)
            data = res.json()
            rt_cd = data.get("rt_cd", "N/A")
            msg1 = data.get("msg1", "")
            rows_data = data.get("output2") or data.get("output") or []
            rows = len(rows_data)

            debug_lines.append(f"**{ticker} [{excd}]** | HTTP `{res.status_code}` | rt_cd: `{rt_cd}` | msg1: `{msg1}` | rows: `{rows}`")

            if res.status_code == 200 and rt_cd == "0" and rows > 0:
                df = pd.DataFrame(rows_data).head(60)
                # 컬럼 자동 감지
                date_col  = next((c for c in df.columns if c.lower() in ('xymd', 'stck_bsop_date') or 'date' in c.lower() or 'bsop' in c.lower()), None)
                close_col = next((c for c in df.columns if c.lower() in ('clos',) or 'prpr' in c.lower() or 'last' in c.lower()), None)
                vol_col   = next((c for c in df.columns if c.lower() in ('tvol',) or ('vol' in c.lower() and 'tvol' in c.lower())), None)

                if date_col and close_col:
                    df = df[[date_col, close_col] + ([vol_col] if vol_col else [])].copy()
                    df.columns = ['Date', 'Close'] + (['Volume'] if vol_col else [])
                    df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
                    df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
                    df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce') if 'Volume' in df.columns else 0
                    df = df.dropna(subset=['Date', 'Close']).sort_values('Date').reset_index(drop=True)

                    if debug_container:
                        with debug_container.expander(f"✅ {ticker} [{excd}] 수집 성공", expanded=False):
                            for line in debug_lines: st.markdown(line)
                    return df
        except Exception as e:
            debug_lines.append(f"**{ticker} [{excd}]** 예외: {e}")

        # Rate limit 방지
        sleep_time = 1.5 if (res is not None and res.status_code == 500) else 0.8
        time.sleep(sleep_time)

    if debug_container:
        with debug_container.expander(f"⚠️ {ticker} 수집 실패", expanded=True):
            for line in debug_lines: st.markdown(line)
    return None

# --- Technical Indicators ---
def calculate_indicators(df):
    """
    Calculate technical indicators for auto-trading strategy.
    """
    if df is None or len(df) < 20:
        return df
    
    # Simple Moving Averages
    df['SMA5'] = df['Close'].rolling(window=5).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA60'] = df['Close'].rolling(window=60).mean()
    
    # RSI (Relative Strength Index) - 14 days
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# --- Auto-Trading Utilities ---
def log_trade(action, ticker, price, quantity, reason):
    """
    Log trading activities to a CSV file.
    """
    log_file = "trade_log.csv"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = pd.DataFrame([{
        "Timestamp": now,
        "Action": action,
        "Ticker": ticker,
        "Price": price,
        "Quantity": quantity,
        "Reason": reason
    }])
    
    if not os.path.exists(log_file):
        log_entry.to_csv(log_file, index=False)
    else:
        log_entry.to_csv(log_file, mode='a', header=False, index=False)

def check_risk_management(holdings_item, stop_loss_pct=5.0, take_profit_pct=10.0):
    """
    Check if a stock should be sold based on Stop-Loss or Take-Profit.
    Returns: (should_sell: bool, reason: str)
    """
    profit_rt = float(holdings_item.get('evlu_pfls_rt', 0))
    
    if profit_rt <= -stop_loss_pct:
        return True, f"Stop-Loss reached ({profit_rt:.2f}%)"
    if profit_rt >= take_profit_pct:
        return True, f"Take-Profit reached ({profit_rt:.2f}%)"
    
    return False, ""

def parse_ai_decision(report_text):
    """
    Parse AI recommendation from the report text.
    Returns: (action: str, confidence: int)
    """
    action = "관망" # Default
    confidence = 0
    
    try:
        # Action parsing
        if "매수" in report_text.split("추천 행동:")[1].split("\n")[0]:
            action = "매수"
        elif "매도" in report_text.split("추천 행동:")[1].split("\n")[0]:
            action = "매도"
            
        # Confidence parsing
        conf_match = re.search(r"신뢰도 점수:\s*\[?(\d+)\]?", report_text)
        if conf_match:
            confidence = int(conf_match.group(1))
    except:
        pass
        
    return action, confidence

def summarize_for_ai(charts_data: dict) -> str:
    lines = []
    for ticker, df in charts_data.items():
        if df is None or len(df) < 20: continue
        # Calculate indicators first
        df = calculate_indicators(df)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        cur = last['Close']
        rsi = last['RSI']
        ma5 = last['SMA5']
        ma20 = last['SMA20']
        
        # Signals
        ma_cross = "Golden Cross" if prev['SMA5'] <= prev['SMA20'] and ma5 > ma20 else \
                   "Dead Cross" if prev['SMA5'] >= prev['SMA20'] and ma5 < ma20 else "Neutral"
        
        chg5 = (cur / df.iloc[-5]['Close'] - 1) * 100 if len(df) >= 5 else 0
        vol_spike = last['Volume'] / df['Volume'].rolling(20).mean().iloc[-1] if not df['Volume'].isnull().all() else 1
        
        lines.append(f"{ticker}: price={cur:,.0f}, RSI={rsi:.1f}, MA5={ma5:,.0f}, MA20={ma20:,.0f}, MA_Status={ma_cross}, 5d_chg={chg5:+.1f}%, Vol_Spike={vol_spike:.1f}x")
    return "\n".join(lines)

def analyze_with_ai(market_status_text, summary_text, base_url, model_name, market_type="US"):
    try:
        client = OpenAI(base_url=base_url, api_key="lm-studio")
        market_name = "미국" if market_type == "US" else "한국"
        
        style = st.session_state.get('trading_style', '보통')
        style_instruction = ""
        if style == "공격적":
            style_instruction = f"- 당신의 투자 성향은 '공격적'입니다. 약간의 리스크가 있더라도 높은 수익이 기대된다면 적극적으로 매수를 추천하세요. 기준을 평소보다 완화하여 성장을 우선시하십시오."
        elif style == "보수적":
            style_instruction = f"- 당신의 투자 성향은 '보수적'입니다. 매우 확실한 근거가 있을 때만 매수를 추천하고, 원금 보존을 최우선으로 하십시오."
        else:
            style_instruction = f"- 당신의 투자 성향은 '중립적/보통'입니다. 균형 잡힌 시각으로 리스크와 수익을 저울질하세요."

        prompt = f"""{market_name} 주식 전문가로서 아래 데이터를 요약 분석하고 투자 의견을 내세요. 
데이터에는 가격, RSI, 이동평균선 상태 등이 포함되어 있습니다.
{style_instruction}

시장상태: {market_status_text}
종목데이터:
{summary_text}

형식:
## 🤖 AI 분석 리포트
### 📊 시장 요약 및 추천
(핵심 요약)

### 🎯 자동 매매 판단
- 추천 행동: [매수 / 매도 / 관망]
- 신뢰도 점수: [0-100]
- 근거 요약: (짧은 한 문장)
"""
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=600 # Limit output for speed
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 분석 중 오류 발생: {e}"

# --- Streamlit UI ---
st.set_page_config(page_title="Stock AI Analyst", layout="wide")
st.title("📈 실시간 주식 AI 분석 추천 서비스 (Local LLM)")

# --- Sidebar: Account & Balance ---
st.sidebar.header("💰 내 계좌 관리")

# Initialize session state
if "balance_data" not in st.session_state:
    st.session_state.balance_data = None
if "kr_analysis_result" not in st.session_state:
    st.session_state.kr_analysis_result = None
if "auto_buy_tickers" not in st.session_state:
    st.session_state.auto_buy_tickers = "005930, 000660" # Samsung, SK Hynix
if "periodic_active" not in st.session_state:
    st.session_state.periodic_active = False
if "last_auto_scan_time" not in st.session_state:
    st.session_state.last_auto_scan_time = 0
if "trading_style" not in st.session_state:
    st.session_state.trading_style = "보통"

def update_balance():
    with st.sidebar:
        with st.spinner("잔고 불러오는 중..."):
            try:
                broker = get_mojito_instance()
                if broker:
                    res = broker.fetch_balance()
                    if res and 'output2' in res:
                        st.session_state.balance_data = res
                    else:
                        st.session_state.balance_data = None
                else:
                    st.warning("계좌 설정 미비 (API 키를 확인하세요)")
            except Exception as e:
                st.warning(f"⚠️ KIS 연동 중 네트워크 오류: {e}")
                st.session_state.balance_data = None

if st.sidebar.button("🔄 실시간 잔고 조회", use_container_width=True):
    update_balance()

# Display Balance in Sidebar
if st.session_state.balance_data:
    data = st.session_state.balance_data
    out2 = data.get('output2', [{}])[0]
    
    st.sidebar.divider()
    st.sidebar.metric("총 평가금액", f"{int(out2.get('tot_evlu_amt', 0)):,}원")
    st.sidebar.metric("예수금", f"{int(out2.get('dnca_tot_amt', 0)):,}원")
    st.sidebar.metric("평가손익", f"{int(out2.get('evlu_pfls_smtl_amt', 0)):,}원")
    
    with st.sidebar.expander("보유 종목 상세보기", expanded=False):
        holdings = data.get('output1', [])
        if holdings:
            for item in holdings:
                name = item.get('prdt_name', '알 수 없음')
                qty = item.get('hldg_qty', '0')
                # Mojito fields: prpr (current price), pbuy_avg_pric (avg buy price), evlu_pfls_rt (profit rate)
                cur_p = float(item.get('prpr', 0))
                buy_avg = float(item.get('pbuy_avg_pric', 0))
                profit_rt = float(item.get('evlu_pfls_rt', 0))
                profit_amt = float(item.get('evlu_pfls_amt', 0))
                
                # Color based on profit
                color = "#ff4b4b" if profit_amt > 0 else "#31333f"
                if profit_amt < 0: color = "#1c83e1" # Nice blue for loss
                
                st.markdown(f"""
                <div style="border-bottom: 1px solid #eee; padding: 10px 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold; font-size: 0.9rem;">{name}</span>
                        <span style="color: {color}; font-weight: bold; font-size: 0.9rem;">{profit_rt:+.2f}%</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #666;">
                        <span>{int(qty):,}주</span>
                        <span>평가손익: <span style="color: {color};">{int(profit_amt):+,}원</span></span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.write("보유 종목 없음")
else:
    st.sidebar.info("버튼을 눌러 잔고를 조회하세요.")

st.sidebar.divider()
st.sidebar.caption(f"접속 모델: {LLM_MODEL}")

# Create Tabs
tab_kr, tab_global, tab_auto = st.tabs(["🇰🇷 국내 주식", "🇺🇸 해외 주식", "🤖 자동 매매 (Beta)"])

with tab_kr:
    st.header("🇰🇷 국내 주식 분석")
    
    # KR Market Status
    is_kr_open, kr_time = check_kr_market_status()
    st.subheader("실시간 장 상태")
    if is_kr_open:
        kr_market_status = f"현재 한국 증시 개장 중입니다. (KST: {kr_time.strftime('%Y-%m-%d %H:%M')})"
        st.success(f"🟢 **{kr_market_status}**")
    else:
        kr_market_status = f"현재 한국 증시는 휴장 중입니다. (KST: {kr_time.strftime('%Y-%m-%d %H:%M')})"
        st.info(f"🔴 **{kr_market_status}**")

    search_input = st.text_input("종목명 또는 종목코드 입력 (예: 삼성전자, 005930)", value="삼성전자", key="kr_search_input")
    
    if st.button("분석 시작 (데이터 수집 및 AI 예측)", type="primary", key="kr_run_analysis_btn"):
        ticker_code = get_kr_stock_code(search_input)
        
        if not ticker_code:
            st.error(f"'{search_input}'에 해당하는 종목코드를 찾을 수 없습니다. 6자리 코드를 직접 입력해보세요.")
        elif not (KIS_APP_KEY and KIS_APP_SECRET):
            st.error("KIS API 키가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        else:
            with st.spinner("데이터 조회 및 AI 분석 중..."):
                auth_token = get_access_token(KIS_APP_KEY, KIS_APP_SECRET)
                if auth_token:
                    kr_df, kr_info = fetch_kr_daily_data(auth_token, KIS_APP_KEY, KIS_APP_SECRET, ticker_code)
                    
                    if kr_df is not None:
                        summary_text = summarize_for_ai({ticker_code: kr_df})
                        ai_report = analyze_with_ai(kr_market_status, summary_text, LLM_URL, LLM_MODEL, market_type="KR")
                        
                        # Store everything in session state
                        st.session_state.kr_analysis_result = {
                            "ticker": ticker_code,
                            "name": search_input,
                            "df": kr_df,
                            "info": kr_info,
                            "report": ai_report,
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                    else:
                        st.error("데이터 수집에 실패했습니다. 종목코드나 API 설정을 확인해주세요.")

    # --- Persistent Analysis View ---
    if st.session_state.kr_analysis_result:
        res_data = st.session_state.kr_analysis_result
        t_code = res_data["ticker"]
        t_name = res_data["name"]
        t_df = res_data["df"]
        t_info = res_data["info"]
        t_report = res_data["report"]

        # 1. Price Metrics
        m_col1, m_col2, m_col3 = st.columns(3)
        p_cur = t_info.get('stck_prpr', '0')
        p_chg = t_info.get('prdy_vrss', '0')
        p_rate = t_info.get('prdy_ctrt', '0')
        
        m_col1.metric("현재가", f"{int(p_cur):,}원", f"{int(p_chg):+,}원 ({p_rate}%)")
        m_col2.metric("거래량", f"{int(t_info.get('acml_vol', 0)):,}주")
        m_col3.metric("상장주식수", f"{int(t_info.get('lstn_stcn', 0)):,}주")
        
        # 1.5 Technical Indicators (New)
        t_df_with_ind = calculate_indicators(t_df)
        last_row = t_df_with_ind.iloc[-1]
        
        st.write("---")
        ind_col1, ind_col2, ind_col3 = st.columns(3)
        ind_col1.metric("RSI (14일)", f"{last_row['RSI']:.1f}")
        ind_col2.metric("SMA 5/20", f"{int(last_row['SMA5']):,}/{int(last_row['SMA20']):,}")
        
        # Trend check
        trend = "상승세" if last_row['SMA5'] > last_row['SMA20'] else "하락세"
        ind_col3.metric("현재 추세", trend, delta="강세" if last_row['RSI'] > 50 else "약세")
        
        # 2. Chart
        st.subheader(f"📈 {t_name} ({t_code}) 주가 차트")
        st.line_chart(t_df.set_index('Date')['Close'])
        
        # 3. AI Report
        st.markdown(t_report)
        st.caption(f"분석 시점: {res_data.get('timestamp')}")
        
        # 4. Trading Section (Buy/Sell Tabs)
        st.divider()
        st.subheader(f"🔄 {t_name} 거래하기")
        
        trade_tab_buy, trade_tab_sell = st.tabs(["📈 매수", "📉 매도"])
        
        p_cur_int = int(p_cur)
        tick_val = get_tick_size(p_cur_int)
        
        with trade_tab_buy:
            buy_col1, buy_col2, buy_col3 = st.columns([2, 2, 3])
            with buy_col1:
                kr_buy_type = st.selectbox("주문 유형", ["시장가", "지정가"], key="kr_sel_buy_type")
            with buy_col2:
                kr_buy_qty = st.number_input("매수 수량", min_value=1, value=1, step=1, key="kr_num_buy_qty")
            with buy_col3:
                if kr_buy_type == "지정가":
                    kr_buy_price = st.number_input(f"매수 가격 (단위: {tick_val}원)", 
                                                     min_value=tick_val, 
                                                     value=p_cur_int, 
                                                     step=tick_val, 
                                                     key="kr_num_buy_price")
                else:
                    st.write("\n")
                    st.info("시장가로 즉시 매수합니다.")
                    kr_buy_price = p_cur_int
            
            if st.button("🔥 매수 주문 실행", type="primary", use_container_width=True, key="kr_exec_buy_btn"):
                mojito_broker = get_mojito_instance()
                if mojito_broker:
                    try:
                        with st.spinner("주문 처리 중..."):
                            if kr_buy_type == "시장가":
                                order_res = mojito_broker.create_market_buy_order(symbol=t_code, quantity=kr_buy_qty)
                            else:
                                order_res = mojito_broker.create_limit_buy_order(symbol=t_code, price=kr_buy_price, quantity=kr_buy_qty)
                            
                            if order_res.get('rt_cd') == '0':
                                st.success(f"✅ 매수 주문 성공! [주문번호: {order_res.get('output', {}).get('ODNO', 'N/A')}]")
                                st.balloons()
                                update_balance() # Sidebar refresh
                            else:
                                st.error(f"❌ 매수 실패: {order_res.get('msg1')} ({order_res.get('rt_cd')})")
                                if 'msg2' in order_res: st.info(order_res.get('msg2'))
                    except Exception as e:
                        st.error(f"주문 실행 중 오류: {e}")
                else:
                    st.error("계좌 연동 실패. 설정 확인 필요.")

        with trade_tab_sell:
            sell_col1, sell_col2, sell_col3 = st.columns([2, 2, 3])
            with sell_col1:
                kr_sell_type = st.selectbox("주문 유형", ["시장가", "지정가"], key="kr_sel_sell_type")
            with sell_col2:
                kr_sell_qty = st.number_input("매도 수량", min_value=1, value=1, step=1, key="kr_num_sell_qty")
            with sell_col3:
                if kr_sell_type == "지정가":
                    kr_sell_price = st.number_input(f"매도 가격 (단위: {tick_val}원)", 
                                                      min_value=tick_val, 
                                                      value=p_cur_int, 
                                                      step=tick_val, 
                                                      key="kr_num_sell_price")
                else:
                    st.write("\n")
                    st.info("시장가로 즉시 매도합니다.")
                    kr_sell_price = p_cur_int
            
            if st.button("🚀 매도 주문 실행", type="primary", use_container_width=True, key="kr_exec_sell_btn"):
                mojito_broker = get_mojito_instance()
                if mojito_broker:
                    try:
                        with st.spinner("매도 주문 처리 중..."):
                            if kr_sell_type == "시장가":
                                order_res = mojito_broker.create_market_sell_order(symbol=t_code, quantity=kr_sell_qty)
                            else:
                                order_res = mojito_broker.create_limit_sell_order(symbol=t_code, price=kr_sell_price, quantity=kr_sell_qty)
                            
                            if order_res.get('rt_cd') == '0':
                                st.success(f"✅ 매도 주문 성공! [주문번호: {order_res.get('output', {}).get('ODNO', 'N/A')}]")
                                st.balloons()
                                update_balance() # Sidebar refresh
                            else:
                                st.error(f"❌ 매도 실패: {order_res.get('msg1')} ({order_res.get('rt_cd')})")
                                if 'msg2' in order_res: st.info(order_res.get('msg2'))
                    except Exception as e:
                        st.error(f"매도 실행 중 오류: {e}")
                else:
                    st.error("계좌 연동 실패. 설정 확인 필요.")

with tab_global:
    st.header("해외 주식 분석 (미국)")
    
    # Market Status
    is_open, us_time = check_us_market_status()
    st.subheader("실시간 장 상태")
    if is_open:
        market_status_text = f"현재 미국 증시 개장 중입니다. (US/Eastern: {us_time.strftime('%Y-%m-%d %H:%M')})"
        st.success(f"🟢 **{market_status_text}**")
    else:
        market_status_text = f"현재 미국 증시는 휴장 중입니다. 가장 최근 종료된 장 데이터를 바탕으로 분석합니다. (US/Eastern: {us_time.strftime('%Y-%m-%d %H:%M')})"
        st.info(f"🔴 **{market_status_text}**")

    # Input Tickers
    tickers_input = st.text_input("분석할 티커 (쉼표 구분)", value="NVDA, TSLA, AAPL, MSFT, AMZN, GOOGL", key="global_tickers")

    if st.button("분석 시작 (데이터 수집 및 로컬 AI 추천)", type="primary", key="global_analyze_btn"):
        if not (KIS_APP_KEY and KIS_APP_SECRET):
            st.error("KIS API 키가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        else:
            tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
            
            with st.spinner("KIS API 토큰 발급 중..."):
                token = get_access_token(KIS_APP_KEY, KIS_APP_SECRET)
                
            if token:
                chars_data = {}
                st.markdown("#### 🔧 KIS API 디버그 로그")
                debug_container = st.container()
                
                progress = st.progress(0, text="데이터 수집 중...")
                for idx, t in enumerate(tickers):
                    progress.progress((idx+1)/len(tickers), text=f"수집 중: {t}")
                    df = fetch_daily_data(token, KIS_APP_KEY, KIS_APP_SECRET, t, debug_container=debug_container)
                    if df is not None:
                        chars_data[t] = df
                    if idx < len(tickers) - 1:
                        time.sleep(1.5)
                progress.empty()
                
                if chars_data:
                    with st.spinner("Local LLM 분석 중... (LM Studio)"):
                        summary = summarize_for_ai(chars_data)
                        report = analyze_with_ai(market_status_text, summary, LLM_URL, LLM_MODEL, market_type="US")
                        st.markdown("---")
                        st.markdown(report)
                        
                        st.markdown("---")
                        st.subheader("📊 최근 주가 추이")
                        cols = st.columns(2)
                        for i, (t, df) in enumerate(chars_data.items()):
                            with cols[i % 2]:
                                st.write(f"**{t}**")
                                st.line_chart(df.set_index('Date')['Close'])
                else:
                    st.warning("수집된 데이터가 없습니다. API 설정을 확인하세요.")

    # --- Auto-Trading Tab ---
    with tab_auto:
        st.header("🤖 자동 매매 대시보드")
        st.write("설정된 전략과 리스크 관리 로직에 따라 계좌를 모니터링합니다.")
        
        # 1. Settings
        st.subheader("⚙️ 자동 매매 설정")
        set_col1, set_col2, set_col3 = st.columns(3)
        with set_col1:
            stop_loss = st.slider("손절 라인 (%)", 1.0, 10.0, 3.0, 0.5)
            st.session_state.trading_style = st.select_slider("투자 성향 설정", options=["보수적", "보통", "공격적"], value=st.session_state.trading_style)
        with set_col2:
            take_profit = st.slider("익절 라인 (%)", 1.0, 30.0, 7.0, 0.5)
            buy_budget = st.number_input("1회 매수 예산 (원)", min_value=10000, value=100000, step=10000)
        with set_col3:
            auto_mode = st.toggle("완전 자동 매매 활성화", value=False, help="활성화 시 조건 충족 시 즉시 주문을 실행합니다.")
            periodic_active = st.toggle("🔄 2분 주기 자동 스캔 활성화", value=st.session_state.periodic_active)
            st.session_state.periodic_active = periodic_active

        st.write("📍 **감시 종목 리스트 관리**")
        target_tickers_str = st.text_area("감시 종목 (번호를 쉼표로 구분)", value=st.session_state.auto_buy_tickers, height=70)
        st.session_state.auto_buy_tickers = target_tickers_str
        
        pk20_btn = st.button("🚀 KOSPI 20 주요 종목 즉시 등록")
        if pk20_btn:
            kospi20_tickers = "005930, 000660, 373220, 207940, 005380, 000270, 068270, 105560, 035420, 055550, 005490, 000810, 012330, 028260, 032830, 000720, 003550, 033780, 011200, 010950"
            st.session_state.auto_buy_tickers = kospi20_tickers
            st.rerun()

        # 2. Monitoring
        st.divider()
        st.subheader("👀 실시간 리스크 및 기회 모니터링")
        
        # Periodic Logic Check
        should_auto_scan = False
        if st.session_state.periodic_active:
            elapsed = time.time() - st.session_state.last_auto_scan_time
            remaining = max(0, 120 - int(elapsed))
            if remaining <= 0:
                should_auto_scan = True
            st.info(f"⏳ **자동 스캔 모드 가동 중**: 다음 분석까지 약 **{remaining}초** 남음")
        
        main_scan_btn = st.button("🔍 전체 계좌 및 감시 종목 스캔 시작", type="primary", use_container_width=True)
        
        if main_scan_btn or should_auto_scan:
            st.session_state.last_auto_scan_time = time.time()
            token = get_access_token(KIS_APP_KEY, KIS_APP_SECRET)
            if not token:
                st.error("API 토큰 발급 실패")
            else:
                # --- Part A: Sell Monitoring (Risk Management) ---
                st.write("#### 🛡️ 보유 종목 리스크 점검")
                data = st.session_state.get('balance_data')
                if data and 'output1' in data:
                    holdings = data.get('output1', [])
                    found_alert = False
                    for item in holdings:
                        should_sell, reason = check_risk_management(item, stop_loss, take_profit)
                        if should_sell:
                            found_alert = True
                            name = item.get('prdt_name')
                            code = item.get('pdno')
                            qty = item.get('hldg_qty')
                            
                            st.warning(f"⚠️ **{name} ({code})** 매도 제안: {reason}")
                            
                            if auto_mode:
                                broker = get_mojito_instance()
                                if broker:
                                    with st.spinner(f"{name} 자동 매도 처리 중..."):
                                        res = broker.create_market_sell_order(symbol=code, quantity=int(qty))
                                        if res.get('rt_cd') == '0':
                                            st.success(f"✅ {name} 자동 매도 주문 성공!")
                                            log_trade("SELL (AUTO)", name, "시장가", qty, reason)
                                            update_balance()
                                        else:
                                            st.error(f"❌ {name} 매도 실패: {res.get('msg1')}")
                    if not found_alert:
                        st.info("현재 매도 조건(손절/익절)에 해당하는 보유 종목이 없습니다.")
                else:
                    st.info("보유 종목 데이터가 없습니다. 사이드바에서 조회를 먼저 수행하세요.")

                # --- Part B: Buy Monitoring (Auto-Buy) ---
                st.write("#### 🚀 감시 종목 매수 기회 포착")
                target_tickers = [t.strip() for t in target_tickers_str.split(",") if t.strip()]
                if not target_tickers:
                    st.info("감시할 종목이 등록되지 않았습니다.")
                else:
                    for t_code in target_tickers:
                        with st.status(f"'{t_code}' 분석 중...", expanded=False) as status:
                            t_df, _ = fetch_kr_daily_data(token, KIS_APP_KEY, KIS_APP_SECRET, t_code)
                            if t_df is not None:
                                t_df = calculate_indicators(t_df)
                                summary = summarize_for_ai({t_code: t_df})
                                m_status, _ = check_kr_market_status()
                                m_text = "개장 중" if m_status else "휴장 중"
                                report = analyze_with_ai(m_text, summary, LLM_URL, LLM_MODEL, market_type="KR")
                                
                                action, confidence = parse_ai_decision(report)
                                rsi_val = t_df.iloc[-1]['RSI']
                                
                                # Dynamic Thresholds based on Style
                                current_style = st.session_state.get('trading_style', '보통')
                                if current_style == "공격적":
                                    conf_min = 65
                                    rsi_max = 85
                                elif current_style == "보수적":
                                    conf_min = 85
                                    rsi_max = 65
                                else:
                                    conf_min = 75
                                    rsi_max = 75

                                st.write(f"**신호:** {action} | **신뢰도:** {confidence} (기준: {conf_min}) | **RSI:** {rsi_val:.1f} (기준: {rsi_max})")
                                
                                # Buying Logic
                                if action == "매수" and confidence >= conf_min and rsi_val <= rsi_max:
                                    st.success(f"📈 **{t_code}** 매수 조건 충족! (신뢰도: {confidence})")
                                    if auto_mode:
                                        broker = get_mojito_instance()
                                        cur_price = int(t_df.iloc[-1]['Close'])
                                        buy_qty = int(buy_budget / cur_price)
                                        if buy_qty > 0:
                                            with st.spinner(f"{t_code} 자동 매수 주문 중..."):
                                                res = broker.create_market_buy_order(symbol=t_code, quantity=buy_qty)
                                                if res.get('rt_cd') == '0':
                                                    st.success(f"✅ {t_code} 자동 매수 성공! ({buy_qty}주)")
                                                    log_trade("BUY (AUTO)", t_code, "시장가", buy_qty, f"AI 신뢰도 {confidence}, RSI {rsi_val:.1f}")
                                                    update_balance()
                                                else:
                                                    st.error(f"❌ {t_code} 매수 실패: {res.get('msg1')}")
                                        else:
                                            st.warning(f"설정된 예산({buy_budget:,}원)이 부족하여 1주도 살 수 없습니다.")
                                    else:
                                        st.info("자동 매수 시그널이 발생했지만 '완전 자동 매매'가 비활성화 상태입니다.")
                                else:
                                    st.write("관망 중...")
                            status.update(label=f"'{t_code}' 분석 완료", state="complete")
        
        # 3. Trade Logs
        st.divider()
        st.subheader("📜 거래 기록 (Logs)")
        if os.path.exists("trade_log.csv"):
            log_df = pd.read_csv("trade_log.csv")
            st.dataframe(log_df.sort_values("Timestamp", ascending=False), use_container_width=True, hide_index=True)
            if st.button("🗑️ 로그 초기화"):
                os.remove("trade_log.csv")
                st.rerun()
        else:
            st.write("아직 기록된 거래 내역이 없습니다.")
# --- Periodic Rerun for UI Timer ---
if st.session_state.periodic_active:
    time.sleep(1)
    st.rerun()
