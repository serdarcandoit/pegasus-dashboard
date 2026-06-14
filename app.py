import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import time
import json
from pathlib import Path
from datetime import datetime

# Sayfa ayarları
st.set_page_config(page_title="Pegasus (PGSUS) Dashboard", page_icon="✈️", layout="wide")

# ─── Yerel Önbellek (Cache) Altyapısı ───
CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _json_serializer(obj):
    """JSON'a çevrilemeyen nesneler için özel serializer."""
    if hasattr(obj, 'item'):  # numpy scalar → Python scalar
        val = obj.item()
        if isinstance(val, float) and val != val:  # NaN
            return None
        return val
    if hasattr(obj, 'isoformat'):  # datetime → string
        return obj.isoformat()
    if isinstance(obj, float) and obj != obj:  # NaN → None
        return None
    return str(obj)


def save_cache(filename, data):
    """Veriyi yerel JSON dosyasına kaydeder."""
    try:
        filepath = CACHE_DIR / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=_json_serializer)
        meta_path = CACHE_DIR / "last_update.txt"
        meta_path.write_text(datetime.now().strftime("%d/%m/%Y %H:%M"), encoding='utf-8')
    except Exception as e:
        print(f"Önbellek kaydetme hatası: {e}")


def load_cache(filename):
    """Yerel JSON önbellek dosyasından veri yükler."""
    try:
        filepath = CACHE_DIR / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ─── Sidebar: Mod Seçimi ───
with st.sidebar:
    st.markdown("""
<div style="text-align: center; margin-bottom: 15px;">
<span style="font-size: 32px;">✈️</span>
<h2 style="margin: 5px 0 0 0; font-size: 18px; color: #d1d4dc;">Pegasus Dashboard</h2>
<span style="font-size: 11px; color: #78909c;">Veri Kontrol Paneli</span>
</div>
""", unsafe_allow_html=True)
    st.markdown("---")
    offline_mode = st.toggle(
        "⚡ Hızlı / Çevrimdışı Mod",
        value=True,
        help="Aktifken hiçbir API çağrısı yapılmaz, kayıtlı veriler kullanılır. Bulut ortamında önerilir."
    )
    if offline_mode:
        st.caption("🟢 Kayıtlı veriler kullanılıyor — API çağrısı yok")
    else:
        st.caption("🔵 Canlı mod — API'lerden veri çekiliyor")
        if st.button("🔄 Verileri Güncelle ve Kaydet", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    _meta_path = CACHE_DIR / "last_update.txt"
    if _meta_path.exists():
        _last_update = _meta_path.read_text(encoding='utf-8')
        st.markdown(f"""
<div style="margin-top: 10px; padding: 8px 12px; background: #1a1e2e; border-radius: 6px; border: 1px solid #2a2e39;">
<span style="color: #78909c; font-size: 11px;">📅 Son veri güncellemesi:</span><br>
<span style="color: #d1d4dc; font-size: 12px; font-weight: 600;">{_last_update}</span>
</div>
""", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("""
<div style="padding: 10px; background: linear-gradient(135deg, #1a2035, #1e2a42); border-radius: 8px; border: 1px solid #29395a; font-size: 11px; color: #90a4ae; line-height: 1.5;">
<b style="color: #d1d4dc;">💡 Nasıl Kullanılır?</b><br><br>
<b>Bulutta:</b> Hızlı modu açık bırakın.<br>
<b>Yerelde:</b> Hızlı modu kapatıp "Güncelle" butonuna basarak en güncel verileri çekin ve GitHub'a push edin.
</div>
""", unsafe_allow_html=True)

# Borsa İstanbul için hisse sembolü (Yahoo Finance formatı)
TICKER = "PGSUS.IS"

# ─── Döviz & Altın Ticker Sembolleri ───
CURRENCY_TICKERS = {
    "USD/TRY": {"symbol": "USDTRY=X", "flag": "🇺🇸", "label": "Dolar ($)"},
    "EUR/TRY": {"symbol": "EURTRY=X", "flag": "🇪🇺", "label": "Euro (€)"},
    "GBP/TRY": {"symbol": "GBPTRY=X", "flag": "🇬🇧", "label": "Sterlin (£)"},
    "BIST100": {"symbol": "XU100.IS", "flag": "XU100", "label": "BIST 100"},
    "BIST30": {"symbol": "XU030.IS", "flag": "XU030", "label": "BIST 30"},
}
GOLD_TICKER = "GC=F"  # Altın (USD/ons) — gram TRY'ye çevrilecek
TROY_OUNCE_GRAM = 31.1035  # 1 troy ons = 31.1035 gram


def fetch_with_retry(func, max_retries=3, initial_wait=5):
    """Yahoo Finance API çağrılarını rate limit hatalarına karşı retry mekanizması ile yapar."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e).lower()
            # Rate limit veya Too Many Requests hatası kontrolü
            if "too many requests" in error_msg or "rate limit" in error_msg or "429" in error_msg or "empty data" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = initial_wait * (2 ** attempt)  # Exponential backoff: 5s, 10s, 20s
                    print(f"⏳ Yahoo Finance rate limit veya boş veri — {wait_time} saniye bekleniyor... (Deneme {attempt + 2}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    raise  # Son denemede de başarısızsa hatayı fırlat
            else:
                raise  # Rate limit dışı hatalar direkt fırlatılır


@st.cache_data(ttl=300)
def load_currency_data(offline_mode=False):
    """Döviz kurları (USD, EUR, GBP → TRY) ve gram altın fiyatını çeker."""
    # ─── Çevrimdışı Mod: Yerel önbellekten yükle ───
    if offline_mode:
        cached = load_cache("currency_data.json")
        if cached:
            return cached
    results = {}

    # Döviz kurlarını çek
    for key, meta in CURRENCY_TICKERS.items():
        try:
            def _fetch(s=meta["symbol"]):
                t = yf.Ticker(s)
                h = t.history(period="5d", interval="1d")
                return h
            h = fetch_with_retry(_fetch)
            if not h.empty and len(h) >= 2:
                current = h['Close'].iloc[-1]
                previous = h['Close'].iloc[-2]
                change_pct = ((current - previous) / previous) * 100
                results[key] = {"price": current, "change": change_pct, **meta}
            elif not h.empty:
                current = h['Close'].iloc[-1]
                results[key] = {"price": current, "change": 0.0, **meta}
        except Exception:
            pass

    # Altın (USD/ons) çek ve gram TRY'ye çevir
    try:
        def _fetch_gold():
            t = yf.Ticker(GOLD_TICKER)
            return t.history(period="5d", interval="1d")
        h_gold = fetch_with_retry(_fetch_gold)

        usd_try_price = results.get("USD/TRY", {}).get("price")

        if not h_gold.empty and usd_try_price:
            gold_usd_current = h_gold['Close'].iloc[-1]
            gold_usd_previous = h_gold['Close'].iloc[-2] if len(h_gold) >= 2 else gold_usd_current
            gram_try_current = (gold_usd_current * usd_try_price) / TROY_OUNCE_GRAM
            gram_try_previous = (gold_usd_previous * usd_try_price) / TROY_OUNCE_GRAM
            change_pct = ((gram_try_current - gram_try_previous) / gram_try_previous) * 100
            results["GOLD"] = {
                "price": gram_try_current,
                "change": change_pct,
                "flag": "🥇",
                "label": "Gram Altın (g)",
            }
    except Exception:
        pass

    # Başarılı çekim — önbelleğe kaydet
    if results:
        save_cache("currency_data.json", results)
    return results


def render_ticker_bar(currency_data):
    """Döviz ve altın fiyatlarını kayan (sliding) borsa bandı olarak render eder."""
    items_html = ""
    
    if not currency_data:
        # Veri çekilemezse varsayılan bir yazı göster
        items_html = f"""<div style="display: inline-flex; align-items: center; gap: 6px; padding: 0 20px;"><span style="color: #90a4ae; font-size: 13px; font-weight: 500;">Döviz ve altın verileri yükleniyor veya API limitine takıldı...</span></div>"""
    else:
        for key, data in currency_data.items():
            price = data["price"]
            change = data["change"]
            flag = data["flag"]
            label = data["label"]

            color = "#26a69a" if change >= 0 else "#ef5350"
            sign = "+" if change >= 0 else ""
            arrow = "▲" if change >= 0 else "▼"

            if key == "GOLD":
                price_str = f"{price:,.2f} ₺"
            else:
                price_str = f"{price:.4f} ₺"

            # Satır sonlarını kaldırarak Markdown parser'ın kod bloğu sanmasını önlüyoruz
            item = f"""<div style="display: inline-flex; align-items: center; gap: 6px; padding: 0 20px; border-right: 1px solid #333;"><span style="font-size: 14px;">{flag}</span><span style="color: #90a4ae; font-size: 12px; font-weight: 500;">{label}</span><span style="color: white; font-size: 13px; font-weight: 600;">{price_str}</span><span style="color: {color}; font-size: 11px; font-weight: bold;">{arrow} {sign}{change:.2f}%</span></div>"""
            items_html += item

    # Sonsuz kusursuz döngü (seamless loop) için içeriği 8 kez çoğaltıp -50% CSS animasyonu kullanıyoruz.
    # Sol %50 ekrandan kaydığında sağ %50 onunla tamamen aynı olduğu için başa sarmış gibi hissettirir.
    repeated_items = items_html * 8
    
    ticker_html = f"""<style>@keyframes scroll-ticker {{ 0% {{ transform: translateX(0); }} 100% {{ transform: translateX(-50%); }} }} .ticker-wrap {{ overflow: hidden; white-space: nowrap; background: #131722; border-bottom: 1px solid #2a2e39; padding: 10px 0; margin-bottom: 15px; }} .ticker-content {{ display: inline-block; white-space: nowrap; animation: scroll-ticker 60s linear infinite; }} .ticker-content:hover {{ animation-play-state: paused; }}</style><div class="ticker-wrap"><div class="ticker-content">{repeated_items}</div></div>"""
    st.markdown(ticker_html, unsafe_allow_html=True)


# ─── Döviz & Altın verisini yükle ve ticker bar'ı göster ───
try:
    currency_data = load_currency_data(offline_mode=offline_mode)
    render_ticker_bar(currency_data)
except Exception:
    # Fallback: önbellekten yükle
    _cached_currency = load_cache("currency_data.json")
    render_ticker_bar(_cached_currency if _cached_currency else {})

# TradingView Tarzı Kompakt Araç Çubuğu
col1, col2, _ = st.columns([2, 2, 6])

# Fiyat adımı (Interval) seçenekleri (TradingView formatında)
interval_options = {
    "G": "1d",
    "H": "1wk",
    "A": "1mo",
    "3A": "3mo",
    "Y": "1y"
}

with col1:
    # Segmented Control (buton görünümü) veya Radio butonu kullanma
    try:
        selected_interval_label = st.segmented_control("Adım", list(interval_options.keys()), default="G", label_visibility="collapsed")
        if not selected_interval_label: selected_interval_label = "G"
    except AttributeError:
        selected_interval_label = st.radio("Adım", list(interval_options.keys()), horizontal=True, label_visibility="collapsed")
selected_interval = interval_options[selected_interval_label]

with col2:
    try:
        chart_type = st.segmented_control("Tip", ["🕯️ Mum", "📈 Çizgi"], default="🕯️ Mum", label_visibility="collapsed")
        if not chart_type: chart_type = "🕯️ Mum"
    except AttributeError:
        chart_type = st.radio("Tip", ["🕯️ Mum", "📈 Çizgi"], horizontal=True, label_visibility="collapsed")


@st.cache_data(ttl=300)  # Fiyat verisi 5 dakika önbellek (rate limit'e takılmamak için artırıldı)
def load_all_data(ticker, interval, offline_mode=False):
    """Tek bir fonksiyonla hem grafik verisini hem hareketli ortalamaları çeker.
    Bu sayede Yahoo Finance'e giden istek sayısı minimuma iner."""
    # ─── Çevrimdışı Mod: Yerel önbellekten yükle ───
    if offline_mode:
        cached = load_cache(f"stock_history_{interval}.json")
        if cached:
            hist = pd.DataFrame({
                'Open': cached['open'],
                'High': cached['high'],
                'Low': cached['low'],
                'Close': cached['close'],
            }, index=pd.to_datetime(cached['index'], utc=True).tz_localize(None))
            return hist, cached.get('calc_50_ma'), cached.get('calc_200_ma')
    stock = yf.Ticker(ticker)

    # 1) Grafik için ana veri
    def _fetch_hist():
        if interval == "1y":
            h = stock.history(period="max", interval="1mo")
            if not h.empty:
                h = h.resample('YE').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last'
                }).dropna()
            return h
        else:
            return stock.history(period="max", interval=interval)

    hist = fetch_with_retry(_fetch_hist)

    # 2) Hareketli ortalamalar için günlük veri — sadece ana veri günlük DEĞİLSE ayrı çek
    #    Eğer zaten günlük veri çektikse, aynı veriyi kullan
    calc_50_ma = None
    calc_200_ma = None

    if interval == "1d" and not hist.empty:
        # Zaten günlük veri elimizde, ekstra istek yok
        if len(hist) >= 50:
            calc_50_ma = hist['Close'].rolling(window=50).mean().iloc[-1]
        if len(hist) >= 200:
            calc_200_ma = hist['Close'].rolling(window=200).mean().iloc[-1]
    else:
        # Farklı interval seçilmişse, günlük veriyi ayrıca çekmemiz gerekiyor
        try:
            def _fetch_daily():
                return stock.history(period="2y", interval="1d")
            
            hist_daily = fetch_with_retry(_fetch_daily)
            if not hist_daily.empty:
                if len(hist_daily) >= 50:
                    calc_50_ma = hist_daily['Close'].rolling(window=50).mean().iloc[-1]
                if len(hist_daily) >= 200:
                    calc_200_ma = hist_daily['Close'].rolling(window=200).mean().iloc[-1]
        except Exception:
            pass  # MA hesaplanamasa da grafik gösterilsin

    # Başarılı çekim — önbelleğe kaydet
    if not hist.empty:
        _cache_data = {
            'index': [str(d) for d in hist.index.tolist()],
            'open': [float(x) for x in hist['Open'].tolist()],
            'high': [float(x) for x in hist['High'].tolist()],
            'low': [float(x) for x in hist['Low'].tolist()],
            'close': [float(x) for x in hist['Close'].tolist()],
            'calc_50_ma': float(calc_50_ma) if calc_50_ma is not None else None,
            'calc_200_ma': float(calc_200_ma) if calc_200_ma is not None else None
        }
        save_cache(f"stock_history_{interval}.json", _cache_data)
    return hist, calc_50_ma, calc_200_ma


@st.cache_data(ttl=21600)  # Temel analiz verileri yavaş değiştiği için 6 saat önbellek
def load_info(ticker, offline_mode=False):
    # ─── Çevrimdışı Mod: Yerel önbellekten yükle ───
    if offline_mode:
        cached = load_cache("stock_info.json")
        if cached:
            return cached
    stock = yf.Ticker(ticker)
    
    def _fetch_info():
        info_data = stock.info
        data = dict(info_data) if isinstance(info_data, dict) else {}
        
        # Eğer veri boş dönerse (rate limit vb. sebeple), retry mekanizmasını tetiklemek için hata fırlat
        if not data or len(data) < 5:
            raise Exception("Rate limit or empty data from yfinance info")
            
        try:
            net_incomes = stock.quarterly_income_stmt.loc['Net Income']
            revenues = stock.quarterly_income_stmt.loc['Total Revenue']
            data['quarterly_net_income'] = float(net_incomes.iloc[0])
            series_dict = {}
            for date, val in net_incomes.items():
                if val == val: # NaN check
                    rev = revenues.get(date, None)
                    if rev == rev and rev is not None:
                        series_dict[str(date)[:10]] = {'net_income': float(val), 'revenue': float(rev)}
            data['quarterly_financials_series'] = series_dict
        except Exception:
            data['quarterly_net_income'] = None
            data['quarterly_financials_series'] = {}
            
        # İş Yatırım UFRS 29 Kümülatif Verilerinden İzole Çeyreklik Hesaplama (Yahoo Hata Düzeltmesi)
        if ticker.endswith('.IS'):
            try:
                import requests
                from datetime import datetime
                code = ticker.replace('.IS', '')
                year = datetime.now().year
                
                all_series = {}  # Tüm yılların verilerini topla
                
                for y in [year, year-1, year-2]:
                    url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={code}&exchange=TRY&financialGroup=XI_29&year1={y}&period1=12&year2={y}&period2=9&year3={y}&period3=6&year4={y}&period4=3"
                    try:
                        res = requests.get(url, timeout=5).json()
                    except Exception:
                        continue
                    if 'value' not in res or len(res['value']) == 0:
                        continue
                    ni_item = next((item for item in res['value'] if item['itemCode'] == '3L'), None)
                    rev_item = next((item for item in res['value'] if item['itemCode'] == '3C'), None)
                    if not ni_item or not rev_item:
                        continue

                    # value1=Q1(Mar), value2=Q2(Jun), value3=Q3(Sep), value4=Q4(Dec) — İş yatırım Kümülatif 
                    ni_vals = [
                        float(ni_item.get('value4') or 0),
                        float(ni_item.get('value3') or 0),
                        float(ni_item.get('value2') or 0),
                        float(ni_item.get('value1') or 0),
                    ]
                    rev_vals = [
                        float(rev_item.get('value4') or 0),
                        float(rev_item.get('value3') or 0),
                        float(rev_item.get('value2') or 0),
                        float(rev_item.get('value1') or 0),
                    ]
                    
                    q_dates = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"]
                    for i in range(4):
                        if ni_vals[i] != 0 or rev_vals[i] != 0:
                            all_series[q_dates[i]] = {'net_income': ni_vals[i], 'revenue': rev_vals[i]}

                if all_series:
                    sorted_dates = sorted(list(all_series.keys()))
                    last_4_dates = sorted_dates[-4:]
                    filtered_series = {k: all_series[k] for k in last_4_dates}
                    
                    data['quarterly_financials_series'] = filtered_series
                    last_key = last_4_dates[-1]
                    data['quarterly_net_income'] = filtered_series[last_key]['net_income']

                    # Y/Y Büyümeyi Hesapla (Önceki yılın aynı dönemiyle)
                    try:
                        last_month = last_key.split('-')[1]
                        period = int(last_month)
                        prev_y = int(last_key[:4]) - 1
                        prev_url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={code}&exchange=TRY&financialGroup=XI_29&year1={prev_y}&period1={period}&year2={prev_y}&period2=9&year3={prev_y}&period3=6&year4={prev_y}&period4=3"
                        prev_res = requests.get(prev_url, timeout=5).json()
                        if 'value' in prev_res and len(prev_res['value']) > 0:
                            prev_ni_item = next((item for item in prev_res['value'] if item['itemCode'] == '3L'), None)
                            if prev_ni_item:
                                period_key = {3: 'value1', 6: 'value2', 9: 'value3', 12: 'value4'}.get(period, 'value4')
                                prev_val = float(prev_ni_item.get(period_key) or 0)
                                if prev_val != 0:
                                    growth = (data['quarterly_net_income'] - prev_val) / abs(prev_val)
                                    data['earningsQuarterlyGrowth'] = growth
                    except Exception:
                        pass
            except Exception:
                pass

        # Beta değerini TradingView Scanner API'sinden çek (yfinance'den daha güvenilir)
        try:
            import requests as _req
            tv_symbol = ticker.replace('.IS', '')
            scan_url = "https://scanner.tradingview.com/global/scan"
            scan_payload = {
                "symbols": {"tickers": [f"BIST:{tv_symbol}"]},
                "columns": ["beta_1_year"]
            }
            scan_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            scan_res = _req.post(scan_url, json=scan_payload, headers=scan_headers, timeout=10)
            if scan_res.status_code == 200:
                scan_data = scan_res.json()
                if scan_data.get("data") and len(scan_data["data"]) > 0:
                    beta_val = scan_data["data"][0]["d"][0]
                    if beta_val is not None:
                        data['beta'] = round(float(beta_val), 2)
        except Exception:
            pass

        return data
    
    result = fetch_with_retry(_fetch_info)
    # Başarılı çekim — önbelleğe kaydet
    if result:
        save_cache("stock_info.json", result)
    return result


try:
    with st.spinner("Veriler yükleniyor..."):
        try:
            hist, calc_50_ma, calc_200_ma = load_all_data(TICKER, selected_interval, offline_mode=offline_mode)
        except Exception:
            _cached_hist = load_cache(f"stock_history_{selected_interval}.json")
            if _cached_hist:
                hist = pd.DataFrame({
                    'Open': _cached_hist['open'], 'High': _cached_hist['high'],
                    'Low': _cached_hist['low'], 'Close': _cached_hist['close'],
                }, index=pd.to_datetime(_cached_hist['index'], utc=True).tz_localize(None))
                calc_50_ma, calc_200_ma = _cached_hist.get('calc_50_ma'), _cached_hist.get('calc_200_ma')
            else:
                raise
        try:
            info = load_info(TICKER, offline_mode=offline_mode)
        except Exception:
            info = load_cache("stock_info.json") or {}
    
    if not hist.empty:
        # Son gün kapanış ve bir önceki gün kapanış fiyatlarını al
        current_price = hist['Close'].iloc[-1]
        previous_price = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        
        # Değişimleri hesapla
        price_change = current_price - previous_price
        pct_change = (price_change / previous_price) * 100
        
        sign = "+" if price_change >= 0 else ""
        
        # Güncel fiyatı TradingView tarzı, tek satırda şık bir başlık olarak gösterelim
        price_color = "#26a69a" if price_change >= 0 else "#ef5350"
        
        header_html = f"""
<div style="display: flex; align-items: baseline; gap: 15px; margin-bottom: 20px; border-bottom: 1px solid #333; padding-bottom: 15px;">
    <h1 style="margin: 0; font-size: 26px; font-weight: 600; color: white;">✈️ Pegasus (PGSUS)</h1>
    <h2 style="margin: 0; font-size: 26px; font-weight: bold; color: white;">{current_price:.2f} ₺</h2>
    <span style="color: {price_color}; font-size: 18px; font-weight: 500;">{sign}{price_change:.2f} ₺ ({sign}{pct_change:.2f}%)</span>
</div>
"""
        st.markdown(header_html, unsafe_allow_html=True)
        
        # Ekranı 2'ye bölelim: %75 Grafik, %25 Temel Analiz
        col_chart, col_fundamentals = st.columns([3, 1], gap="large")
        
        with col_chart:
            # Grafiği çiz (Seçime göre Mum veya Çizgi)
            if chart_type == "🕯️ Mum":
                fig = go.Figure(data=[go.Candlestick(
                    x=hist.index,
                    open=hist['Open'],
                    high=hist['High'],
                    low=hist['Low'],
                    close=hist['Close'],
                    increasing_line_color='#26a69a', # TradingView yeşili
                    decreasing_line_color='#ef5350'  # TradingView kırmızısı
                )])
            else:
                # TradingView tarzı Area/Line chart
                fig = go.Figure(data=[go.Scatter(
                    x=hist.index,
                    y=hist['Close'],
                    mode='lines',
                    line=dict(color='#2962FF', width=2), # TradingView mavisi
                    fill='tozeroy',
                    fillcolor='rgba(41, 98, 255, 0.1)' # Şeffaf mavi dolgu
                )])
                
            # Güncel fiyatı grafikte vurgulama (Highlight)
            hl_color = '#26a69a' if price_change >= 0 else '#ef5350'
            fig.add_hline(
                y=current_price, 
                line_dash="dot", 
                line_color=hl_color, 
                line_width=1.5,
                annotation_text=f" {current_price:.2f} ", 
                annotation_position="right",
                annotation_font=dict(color="white", size=11, family="Arial"),
                annotation_bgcolor=hl_color
            )
                
            fig.update_layout(
                template='plotly_dark',
                xaxis_title='',
                yaxis=dict(title='Fiyat (TRY)', side='right', minallowed=0), # minallowed=0 aşağı kaydırıldığında 0'ın altına inilmesini KESİN engeller
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=40, t=10, b=0), # Etiketin sağda sığması için r=40 yaptık
                height=660, # Chart yüksekliğini büyüterek eşitledik
                dragmode='pan' # Tıklayıp sürükleyince grafiği kaydırma (pan) özelliğini açar
            )
            st.plotly_chart(fig, width='stretch', config={'scrollZoom': True})
            
        with col_fundamentals:
            def format_val(val, format_str="{:.2f}"):
                return format_str.format(val) if val is not None else "Veri Yok"
                
            mcap = info.get('marketCap')
            mcap_str = f"{mcap / 1_000_000_000:.2f} Milyar ₺" if mcap else "Veri Yok"
            
            # Karlılık verilerini hazırla
            q_income = info.get('quarterly_net_income')
            if q_income is not None:
                q_income_color = "#26a69a" if q_income > 0 else "#ef5350"
                q_income_str = f"{q_income / 1_000_000_000:.2f} Milyar ₺" if abs(q_income) >= 1_000_000_000 else f"{q_income / 1_000_000:.2f} Milyon ₺"
            else:
                q_income_color = "white"
                q_income_str = "Veri Yok"
                
            growth = info.get('earningsQuarterlyGrowth')
            if growth is not None:
                growth_pct = growth * 100
                growth_color = "#26a69a" if growth > 0 else "#ef5350"
                growth_sign = "+" if growth > 0 else ""
                growth_str = f"{growth_sign}{growth_pct:.2f}%"
            else:
                growth_color = "white"
                growth_str = "Veri Yok"
            
            # Kendi hesapladığımız kesin MA değerlerini kullanıyoruz, yoksa API'nin verdiğini fallback olarak al
            ma50 = calc_50_ma or info.get('fiftyDayAverage')
            ma200 = calc_200_ma or info.get('twoHundredDayAverage')
            
            # HTML ve CSS ile çok daha şık, kompakt ve hizalı bir tablo (TradingView sidebar benzeri)
            # Markdown block parsing hatalarını önlemek için HTML'de boşluk/indent bırakılmadı
            html_content = f"""
<div style="font-family: sans-serif; margin-top: 0px;">
<h4 style="color: #90a4ae; font-size: 12px; margin-bottom: 5px; border-bottom: 1px solid #37474f; padding-bottom: 3px;">DEĞERLEMELER</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">PD/DD Oranı</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{format_val(info.get('priceToBook'))}</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">F/K (Fiyat/Kazanç)</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{format_val(info.get('trailingPE'))}</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
<span style="color: #b0bec5; font-size: 12px;">Beta (Volatilite)</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{format_val(info.get('beta'))}</span>
</div>

<h4 style="color: #90a4ae; font-size: 12px; margin-bottom: 5px; border-bottom: 1px solid #37474f; padding-bottom: 3px;">ORTALAMALAR</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">50 Günlük Ort.</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{format_val(ma50)} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
<span style="color: #b0bec5; font-size: 12px;">200 Günlük Ort.</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{format_val(ma200)} ₺</span>
</div>

<h4 style="color: #90a4ae; font-size: 12px; margin-bottom: 5px; border-bottom: 1px solid #37474f; padding-bottom: 3px;">PERFORMANS</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">52 Hafta Zirve</span>
<span style="font-weight: bold; color: #26a69a; font-size: 12px;">{format_val(info.get('fiftyTwoWeekHigh'))} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">52 Hafta Dip</span>
<span style="font-weight: bold; color: #ef5350; font-size: 12px;">{format_val(info.get('fiftyTwoWeekLow'))} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
<span style="color: #b0bec5; font-size: 12px;">Piyasa Değeri</span>
<span style="font-weight: bold; color: white; font-size: 12px;">{mcap_str}</span>
</div>

<h4 style="color: #90a4ae; font-size: 12px; margin-bottom: 5px; border-bottom: 1px solid #37474f; padding-bottom: 3px;">KARLILIK (ÇEYREKLİK)</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">Net Kar</span>
<span style="font-weight: bold; color: {q_income_color}; font-size: 12px;">{q_income_str}</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
<span style="color: #b0bec5; font-size: 12px;">Kar Büyümesi (Y/Y)</span>
<span style="font-weight: bold; color: {growth_color}; font-size: 12px;">{growth_str}</span>
</div>
</div>
"""
            st.markdown(html_content, unsafe_allow_html=True)

            # --- Çeyreklik Gelir ve Kar Çubuğu (Grouped Bar Chart) ---
            q_series = info.get('quarterly_financials_series', {})
            if q_series:
                st.markdown("""
<div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 15px; margin-bottom: 5px; border-bottom: 1px solid #37474f; padding-bottom: 3px;">
    <h4 style="color: #90a4ae; font-size: 14px; font-weight: bold; margin: 0; padding: 0;">GELİR VE KAR (ÇEYREKLİK)</h4>
    <div style="font-size: 12px; color: #b0bec5; margin-bottom: 1px;">
        <span style="color: #1E88E5;">■</span> Gelir &nbsp;&nbsp;
        <span style="color: #26a69a;">■</span> Kar &nbsp;&nbsp;
        <span style="color: #ef5350;">■</span> Zarar
    </div>
</div>
""", unsafe_allow_html=True)
                
                dates = list(q_series.keys()) # Kronolojik sıra (Soldan sağa Q1 -> Q4)
                net_incomes = [q_series[d]['net_income'] for d in dates]
                revenues = [q_series[d]['revenue'] for d in dates]
                
                # Tarihleri Q formatına çevir (Örn: Q1 '25)
                formatted_dates = []
                for d in dates:
                    year = d[:4]
                    month = d[5:7]
                    if month == '03': q = 'Q1'
                    elif month == '06': q = 'Q2'
                    elif month == '09': q = 'Q3'
                    elif month == '12': q = 'Q4'
                    else: q = 'Q?'
                    formatted_dates.append(f"{q} '{year[-2:]}")
                
                def fmt(v):
                    return f"{v / 1_000_000_000:.2f} Milyar ₺" if abs(v) >= 1_000_000_000 else f"{v / 1_000_000:.2f} Milyon ₺"
                
                rev_hover = [f"<b>{d}</b><br>Gelir: {fmt(v)}" for d, v in zip(formatted_dates, revenues)]
                ni_hover = [f"<b>{d}</b><br>Net Kar: {fmt(v)}" for d, v in zip(formatted_dates, net_incomes)]
                
                # Kar durumuna göre dinamik renk (Kardaysa Yeşil, Zarardaysa Kırmızı)
                ni_colors = ['#26a69a' if val >= 0 else '#ef5350' for val in net_incomes]
                
                fig_bar = go.Figure()
                
                fig_bar.add_trace(go.Bar(
                    x=formatted_dates,
                    y=revenues,
                    name='Gelir',
                    marker_color='#1E88E5', # Daha canlı, profesyonel bir mavi
                    hoverinfo='text',
                    hovertext=rev_hover,
                    marker_line_width=0,
                ))
                
                fig_bar.add_trace(go.Bar(
                    x=formatted_dates,
                    y=net_incomes,
                    name='Net Kar',
                    marker_color=ni_colors, # Dinamik Yeşil/Kırmızı
                    hoverinfo='text',
                    hovertext=ni_hover,
                    marker_line_width=0,
                ))
                
                fig_bar.update_layout(
                    barmode='group',
                    bargap=0.35, # Sütunları inceltir
                    bargroupgap=0.05,
                    template='plotly_dark',
                    height=240, # Yüksekliği büyüterek daha belirgin hale getirdik
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                    dragmode=False, # Grafiğin kaydırılmasını engeller
                    xaxis=dict(showgrid=False, title='', type='category', tickfont=dict(size=9, color="#90a4ae"), fixedrange=True),
                    yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='', showticklabels=False, zerolinecolor='#37474f', fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                
                # Sadece tıklama ile etkileşimi aç, zoom/pan modlarını kapat
                st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
                
                info_html = """
<div style="margin-top: 15px; display: flex; gap: 8px; align-items: flex-start; text-align: left; color: #78909c; font-size: 11px; font-style: italic; border-top: 1px dashed #37474f; padding-top: 10px; line-height: 1.4;">
<span style="font-size: 14px; margin-top: 1px;">ℹ️</span>
<div>
Fiyat ve temel veriler <b>Yahoo Finance</b> üzerinden sağlanmakta olup <b>5 dakikada bir</b> önbelleğe alınmaktadır.<br>
Çeyreklik Gelir ve Kar tablosu (UFRS 29 Uyumlu Kümülatif Veriler) doğrudan <b>İş Yatırım</b>'dan çekilmektedir.<br>
Güncel fiyatı görmek için 5 dakikanın ardından sayfayı yenileyebilirsiniz.
</div>
</div>
"""
                st.markdown(info_html, unsafe_allow_html=True)
                
        # ─── DHMI Havacılık İstatistikleri ───
        st.markdown("""
<div style="margin-top: 35px; margin-bottom: 15px; border-bottom: 1px solid #37474f; padding-bottom: 8px; display: flex; align-items: center; gap: 12px;">
<span style="font-size: 26px;">✈️</span>
<div>
<h3 style="color: #e0e0e0; font-size: 17px; font-weight: bold; margin: 0;">DHMİ Havalimanı Trafik İstatistikleri</h3>
<span style="color: #78909c; font-size: 12px;">Nisan 2026 Ayı Sonu — Kesin Olmayan Veriler (Kaynak: DHMİ)</span>
</div>
</div>
""", unsafe_allow_html=True)

        @st.cache_data
        def load_dhmi_data():
            import pandas as pd
            try:
                xl = pd.ExcelFile('data/dhmi_nisan_ayı_sonu.xlsx')

                def parse_sheet(sheet_name):
                    df = pd.read_excel(xl, sheet_name, header=None)
                    rows = []
                    for i, row in df.iterrows():
                        if i < 3:
                            continue
                        name = str(row.iloc[0]).strip()
                        if not name or name == 'nan':
                            continue
                        # Skip footer rows
                        skip_keywords = ['GENEL', 'TOPLAM', 'OVERFLIGHT', 'TRANS', 'aretli', '(**)', 'denetimli', 'Havalimanlar']
                        if any(k in name for k in skip_keywords):
                            continue
                        try:
                            total_2025 = float(row.iloc[3])
                            ic_2026    = float(row.iloc[4])
                            dis_2026   = float(row.iloc[5])
                            total_2026 = float(row.iloc[6])
                            change_pct = float(row.iloc[9])
                            rows.append({
                                'Havalimanı': name.replace('(*)', '').strip(),
                                'İç 2026':    ic_2026,
                                'Dış 2026':   dis_2026,
                                'Toplam 2026': total_2026,
                                'Toplam 2025': total_2025,
                                'Değişim (%)': change_pct,
                            })
                        except Exception:
                            pass
                    return pd.DataFrame(rows).sort_values('Toplam 2026', ascending=False)

                def get_totals(sheet_name, total_col=6, change_col=9):
                    df = pd.read_excel(xl, sheet_name, header=None)
                    dhmi_row = df[df.iloc[:, 0].astype(str).str.contains('DHMİ TOPLAMI|DHMI TOPLAMI', case=False, na=False)]
                    tr_row   = df[df.iloc[:, 0].astype(str).str.contains('TÜRKİYE GENELİ|TURKIYE GENEL', case=False, na=False)]
                    result = {}
                    if not dhmi_row.empty:
                        r = dhmi_row.iloc[0]
                        try:
                            result['dhmi_2025']   = float(r.iloc[3])
                            result['dhmi_2026']   = float(r.iloc[total_col])
                            result['dhmi_change'] = float(r.iloc[change_col])
                        except Exception:
                            pass
                    if not tr_row.empty:
                        r = tr_row.iloc[0]
                        try:
                            result['tr_2025']   = float(r.iloc[3])
                            result['tr_2026']   = float(r.iloc[total_col])
                            result['tr_change'] = float(r.iloc[change_col])
                        except Exception:
                            pass
                    return result

                df_yolcu  = parse_sheet('YOLCU')
                df_ucak   = parse_sheet('TİM UCAK') if 'TİM UCAK' in xl.sheet_names else parse_sheet(xl.sheet_names[0])
                df_kargo  = parse_sheet('KARGO')

                totals_yolcu = get_totals('YOLCU')
                totals_ucak  = get_totals(xl.sheet_names[0])
                totals_kargo = get_totals('KARGO')

                return df_yolcu, df_ucak, df_kargo, totals_yolcu, totals_ucak, totals_kargo
            except Exception as ex:
                import traceback
                print(f"DHMI veri okuma hatası: {ex}\n{traceback.format_exc()}")
                return None, None, None, {}, {}, {}

        df_yolcu, df_ucak, df_kargo, tot_yolcu, tot_ucak, tot_kargo = load_dhmi_data()

        # ── KPI Kartları ──────────────────────────────────────────────────────────
        def _fmt_big(v):
            if v is None:
                return "—"
            if abs(v) >= 1_000_000:
                return f"{v / 1_000_000:.2f} M"
            if abs(v) >= 1_000:
                return f"{v / 1_000:.1f} K"
            return f"{v:,.0f}"

        def _chg_color(v):
            return "#26a69a" if v >= 0 else "#ef5350"

        def _chg_arrow(v):
            return "▲" if v >= 0 else "▼"

        dhmi_kpi_html = f"""
<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px;">

  <div style="background: linear-gradient(135deg, #1a2035 0%, #1e2a42 100%); border: 1px solid #29395a; border-radius: 12px; padding: 18px 20px;">
    <div style="color: #78909c; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 6px;">🧳 DHMİ Yolcu (Nisan 2026)</div>
    <div style="color: white; font-size: 26px; font-weight: 700; margin-bottom: 4px;">{_fmt_big(tot_yolcu.get('dhmi_2026'))}</div>
    <div style="color: {_chg_color(tot_yolcu.get('dhmi_change', 0))}; font-size: 13px; font-weight: 600;">
      {_chg_arrow(tot_yolcu.get('dhmi_change', 0))} {abs(tot_yolcu.get('dhmi_change', 0)):.2f}% &nbsp;<span style="color:#546e7a; font-weight:400;">geçen yıla göre</span>
    </div>
    <div style="color:#546e7a; font-size: 11px; margin-top: 6px;">2025: {_fmt_big(tot_yolcu.get('dhmi_2025'))}</div>
  </div>

  <div style="background: linear-gradient(135deg, #1a2035 0%, #1e2a42 100%); border: 1px solid #29395a; border-radius: 12px; padding: 18px 20px;">
    <div style="color: #78909c; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 6px;">✈️ DHMİ Toplam Uçak (Nisan 2026)</div>
    <div style="color: white; font-size: 26px; font-weight: 700; margin-bottom: 4px;">{_fmt_big(tot_ucak.get('dhmi_2026'))}</div>
    <div style="color: {_chg_color(tot_ucak.get('dhmi_change', 0))}; font-size: 13px; font-weight: 600;">
      {_chg_arrow(tot_ucak.get('dhmi_change', 0))} {abs(tot_ucak.get('dhmi_change', 0)):.2f}% &nbsp;<span style="color:#546e7a; font-weight:400;">geçen yıla göre</span>
    </div>
    <div style="color:#546e7a; font-size: 11px; margin-top: 6px;">2025: {_fmt_big(tot_ucak.get('dhmi_2025'))}</div>
  </div>

  <div style="background: linear-gradient(135deg, #1a2035 0%, #1e2a42 100%); border: 1px solid #29395a; border-radius: 12px; padding: 18px 20px;">
    <div style="color: #78909c; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 6px;">📦 DHMİ Kargo / ton (Nisan 2026)</div>
    <div style="color: white; font-size: 26px; font-weight: 700; margin-bottom: 4px;">{_fmt_big(tot_kargo.get('dhmi_2026'))}</div>
    <div style="color: {_chg_color(tot_kargo.get('dhmi_change', 0))}; font-size: 13px; font-weight: 600;">
      {_chg_arrow(tot_kargo.get('dhmi_change', 0))} {abs(tot_kargo.get('dhmi_change', 0)):.2f}% &nbsp;<span style="color:#546e7a; font-weight:400;">geçen yıla göre</span>
    </div>
    <div style="color:#546e7a; font-size: 11px; margin-top: 6px;">2025: {_fmt_big(tot_kargo.get('dhmi_2025'))}</div>
  </div>

</div>
"""
        st.markdown(dhmi_kpi_html, unsafe_allow_html=True)

        # ── Grafikler ─────────────────────────────────────────────────────────────
        col_dhmi1, col_dhmi2 = st.columns(2, gap="large")

        with col_dhmi1:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 8px;'>🏆 En Yoğun 10 Havalimanı — Yolcu (Nisan 2026)</h4>", unsafe_allow_html=True)
            if df_yolcu is not None and not df_yolcu.empty:
                top10 = df_yolcu.head(10).iloc[::-1]  # Reverse for horizontal bar (en büyük üstte)

                fig_dhmi1 = go.Figure()
                fig_dhmi1.add_trace(go.Bar(
                    y=top10['Havalimanı'],
                    x=top10['İç 2026'],
                    name='İç Hat',
                    orientation='h',
                    marker_color='#1E88E5',
                    marker_line_width=0,
                    hovertemplate='<b>%{y}</b><br>İç Hat: %{x:,.0f}<extra></extra>',
                ))
                fig_dhmi1.add_trace(go.Bar(
                    y=top10['Havalimanı'],
                    x=top10['Dış 2026'],
                    name='Dış Hat',
                    orientation='h',
                    marker_color='#E040FB',
                    marker_line_width=0,
                    hovertemplate='<b>%{y}</b><br>Dış Hat: %{x:,.0f}<extra></extra>',
                ))
                fig_dhmi1.update_layout(
                    barmode='stack',
                    template='plotly_dark',
                    height=380,
                    margin=dict(l=0, r=20, t=10, b=0),
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1, font=dict(size=11)),
                    xaxis=dict(showgrid=True, gridcolor='#2a2e39', title='', tickformat=',.0f', fixedrange=True),
                    yaxis=dict(showgrid=False, title='', tickfont=dict(size=10), fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False,
                )
                st.plotly_chart(fig_dhmi1, use_container_width=True, config={'displayModeBar': False})
            else:
                st.info("Yolcu verisi okunamadı.")

        with col_dhmi2:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 8px;'>📈 Yıllık Değişim (%) — Top 15 Havalimanı Yolcu</h4>", unsafe_allow_html=True)
            if df_yolcu is not None and not df_yolcu.empty:
                top15_chg = df_yolcu.head(15).sort_values('Değişim (%)')
                bar_colors = ['#ef5350' if v < 0 else '#26a69a' for v in top15_chg['Değişim (%)']]

                fig_dhmi2 = go.Figure()
                fig_dhmi2.add_trace(go.Bar(
                    y=top15_chg['Havalimanı'],
                    x=top15_chg['Değişim (%)'],
                    orientation='h',
                    marker_color=bar_colors,
                    marker_line_width=0,
                    hovertemplate='<b>%{y}</b><br>Değişim: %{x:.2f}%<extra></extra>',
                ))
                fig_dhmi2.add_vline(x=0, line_color='#546e7a', line_width=1.2)
                fig_dhmi2.update_layout(
                    template='plotly_dark',
                    height=380,
                    margin=dict(l=0, r=20, t=10, b=0),
                    xaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Değişim (%)', fixedrange=True),
                    yaxis=dict(showgrid=False, title='', tickfont=dict(size=10), fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False,
                    showlegend=False,
                )
                st.plotly_chart(fig_dhmi2, use_container_width=True, config={'displayModeBar': False})
            else:
                st.info("Değişim verisi okunamadı.")

        # ── Kargo değişim grafiği + Yolcu detay tablosu ──────────────────────────
        col_dhmi3, col_dhmi4 = st.columns(2, gap="large")

        with col_dhmi3:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 8px;'>📦 Kargo Değişimi (%) — Top 12 Havalimanı</h4>", unsafe_allow_html=True)
            if df_kargo is not None and not df_kargo.empty:
                top12_kargo = df_kargo[df_kargo['Toplam 2026'] > 0].head(12).sort_values('Değişim (%)')
                kargo_colors = ['#ef5350' if v < 0 else '#26a69a' for v in top12_kargo['Değişim (%)']]

                fig_dhmi3 = go.Figure()
                fig_dhmi3.add_trace(go.Bar(
                    y=top12_kargo['Havalimanı'],
                    x=top12_kargo['Değişim (%)'],
                    orientation='h',
                    marker_color=kargo_colors,
                    marker_line_width=0,
                    hovertemplate='<b>%{y}</b><br>Kargo Değişim: %{x:.2f}%<extra></extra>',
                ))
                fig_dhmi3.add_vline(x=0, line_color='#546e7a', line_width=1.2)
                fig_dhmi3.update_layout(
                    template='plotly_dark',
                    height=350,
                    margin=dict(l=0, r=20, t=10, b=0),
                    xaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Değişim (%)', fixedrange=True),
                    yaxis=dict(showgrid=False, title='', tickfont=dict(size=10), fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False,
                    showlegend=False,
                )
                st.plotly_chart(fig_dhmi3, use_container_width=True, config={'displayModeBar': False})
            else:
                st.info("Kargo verisi okunamadı.")

        with col_dhmi4:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 8px;'>📋 Havalimanı Yolcu Detay Tablosu (Top 20)</h4>", unsafe_allow_html=True)
            if df_yolcu is not None and not df_yolcu.empty:
                import pandas as pd
                display_df = df_yolcu.head(20)[['Havalimanı', 'İç 2026', 'Dış 2026', 'Toplam 2026', 'Değişim (%)']].copy()
                display_df['İç 2026']     = display_df['İç 2026'].apply(lambda x: f"{x:,.0f}")
                display_df['Dış 2026']    = display_df['Dış 2026'].apply(lambda x: f"{x:,.0f}")
                display_df['Toplam 2026'] = display_df['Toplam 2026'].apply(lambda x: f"{x:,.0f}")
                display_df['Değişim (%)'] = display_df['Değişim (%)'].apply(lambda x: f"{'▲' if x >= 0 else '▼'} {abs(x):.2f}%")
                st.dataframe(display_df, hide_index=True, height=350, use_container_width=True)
            else:
                st.info("Tablo verisi okunamadı.")

        st.markdown("""
<div style="margin-top: 8px; margin-bottom: 25px; display: flex; gap: 8px; align-items: flex-start; color: #78909c; font-size: 11px; font-style: italic; border-top: 1px dashed #37474f; padding-top: 10px;">
<span style="font-size: 14px; margin-top: 1px;">ℹ️</span>
<div>Veriler <b>DHMİ (Devlet Hava Meydanları İşletmesi)</b> tarafından yayımlanan <b>Nisan 2026 ayı sonu</b> trafik istatistiklerine dayanmaktadır.
(*) işaretli havalimanları DHMİ denetimli özel şirket tarafından işletilmekte olup DHMİ toplamına dahil edilmemektedir. Veriler kesin olmayıp revizeye tabidir.</div>
</div>
""", unsafe_allow_html=True)

        # ─── Makroekonomik Veriler (TCMB Excel Dosyaları) ───
        st.markdown("""
<div style="margin-top: 25px; margin-bottom: 10px; border-bottom: 1px solid #37474f; padding-bottom: 5px;">
<h3 style="color: #90a4ae; font-size: 16px; font-weight: bold; margin: 0;">🌍 Makroekonomik Göstergeler (Türkiye)</h3>
</div>
""", unsafe_allow_html=True)

        col_inf, col_int, col_gdp = st.columns(3, gap="large")
        
        with col_inf:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>📈 Enflasyon Oranı (Yıllık, YoY)</h4>", unsafe_allow_html=True)
            @st.cache_data
            def load_local_inflation_data():
                try:
                    import pandas as pd
                    import re
                    dates = []
                    values = []
                    df = pd.read_excel('data/inflation_tcmb.xlsx', header=None)
                    for i, row in df.iterrows():
                        val = row.iloc[1]
                        if pd.notna(val) and isinstance(val, (int, float)):
                            s_date = str(row.iloc[0]).strip().replace('\xad', '-').replace('\u00ad', '-')
                            if '-' not in s_date and ' ' in s_date: s_date = s_date.replace(' ', '-')
                            
                            # Tarihi YYYY-MM-01 formatına çevir
                            m = re.search(r'(\d{2})[- ]?(\d{4})', s_date)
                            if m:
                                clean_date = f"{m.group(2)}-{m.group(1)}-01"
                                dates.append(clean_date)
                                values.append(float(val))
                                
                    # Veri en yeniden eskiye dönüyorsa tersine çevirelim
                    dates.reverse()
                    values.reverse()
                    return dates, values
                except Exception as e:
                    print(f"Lokal Excel okuma hatası: {e}")
                    return [], []

            inf_years, inf_values = load_local_inflation_data()

            if inf_years and inf_values:
                fig_inf = go.Figure()
                fig_inf.add_trace(go.Scatter(
                    x=inf_years,
                    y=inf_values,
                    mode='lines+markers',
                    name='Enflasyon (%)',
                    line=dict(color='#00D2FF', width=3), # Modern Neon Cam Göbeği
                    marker=dict(size=7, color='#00D2FF', line=dict(width=1.5, color='#11151C')),
                    fill='tozeroy',
                    fillcolor='rgba(0, 210, 255, 0.15)',
                    hovertemplate='<b>%{x}</b><br>Enflasyon: %{y:.2f}%<extra></extra>'
                ))
                
                last_year = inf_years[-1]
                last_val = inf_values[-1]
                
                fig_inf.add_annotation(
                    x=last_year,
                    y=last_val,
                    text=f"<b>{last_val:.1f}%</b>",
                    showarrow=True,
                    arrowhead=1,
                    arrowcolor="rgba(255, 255, 255, 0.5)",
                    arrowsize=1.2,
                    arrowwidth=1.5,
                    ax=0,
                    ay=-40,
                    font=dict(color="#11151C", size=12, family="Inter, Arial, sans-serif", weight="bold"),
                    bgcolor="#00D2FF",
                    bordercolor="rgba(0,0,0,0)",
                    borderwidth=0,
                    borderpad=5
                )
                
                fig_inf.update_layout(
                    template='plotly_dark',
                    height=320,
                    margin=dict(l=10, r=50, t=20, b=30),
                    xaxis=dict(showgrid=False, title='', fixedrange=True),
                    yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Enflasyon (%)', side='right', fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False
                )
                st.plotly_chart(fig_inf, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
            else:
                st.warning("Veri klasöründeki Excel dosyası okunamadı veya Türkiye verisi bulunamadı.")

        with col_int:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>🏦 TCMB Politika Faizi</h4>", unsafe_allow_html=True)
            
            @st.cache_data
            def load_local_interest_rate():
                try:
                    import pandas as pd
                    dates = []
                    values = []
                    xl = pd.ExcelFile('data/interest_rate_tcmb.xlsx')
                    for s in xl.sheet_names:
                        df = pd.read_excel(xl, s, header=None)
                        for i, row in df.iterrows():
                            # PDF kaynaklı çok satırlı hücreleri ayır
                            c0 = str(row.iloc[0]).split('\n')
                            c1 = str(row.iloc[1]).split('\n') if len(row) > 1 else []
                            c2 = str(row.iloc[2]).split('\n') if len(row) > 2 else []
                            for idx in range(len(c0)):
                                cell = c0[idx].strip().split()[0]
                                if ('-' in cell or '.' in cell) and len(cell) >= 8 and cell[0].isdigit():
                                    try:
                                        val1 = float(c1[idx].strip()) if idx < len(c1) and c1[idx].strip() not in ('NaN', 'nan', '') else 0
                                        val2 = float(c2[idx].strip()) if idx < len(c2) and c2[idx].strip() not in ('NaN', 'nan', '') else 0
                                        val = max(val1, val2)
                                        if val > 0:
                                            if '.' in cell:
                                                parts = cell.split('.')
                                                if len(parts)==3:
                                                    if len(parts[2]) == 2: parts[2] = '20'+parts[2]
                                                    cell = f'{parts[2]}-{parts[1]}-{parts[0]}'
                                            dates.append(cell[:10])
                                            values.append(val)
                                    except:
                                        pass
                    # Tarihe göre sırala
                    combined = sorted(list(zip(dates, values)), key=lambda x: x[0])
                    if combined:
                        dates, values = zip(*combined)
                        return list(dates), list(values)
                except Exception as e:
                    print(f"Faiz dosyası okuma hatası: {e}")
                return [], []
            
            int_dates, int_values = load_local_interest_rate()
            
            if int_dates and int_values:
                fig_int = go.Figure()
                fig_int.add_trace(go.Scatter(
                    x=int_dates,
                    y=int_values,
                    mode='lines+markers',
                    name='Politika Faizi (%)',
                    line=dict(color='#FF3A59', width=3), # Modern Neon Mercan/Kırmızı
                    marker=dict(size=7, color='#FF3A59', line=dict(width=1.5, color='#11151C')),
                    fill='tozeroy',
                    fillcolor='rgba(255, 58, 89, 0.15)',
                    hovertemplate='<b>%{x}</b><br>Faiz: %{y:.2f}%<extra></extra>'
                ))
                
                fig_int.add_annotation(
                    x=int_dates[-1],
                    y=int_values[-1],
                    text=f"<b>{int_values[-1]:.1f}%</b>",
                    showarrow=True,
                    arrowhead=1,
                    arrowcolor="rgba(255, 255, 255, 0.5)",
                    arrowsize=1.2,
                    arrowwidth=1.5,
                    ax=0,
                    ay=-40,
                    font=dict(color="white", size=12, family="Inter, Arial, sans-serif"),
                    bgcolor="#FF3A59",
                    bordercolor="rgba(0,0,0,0)",
                    borderwidth=0,
                    borderpad=5
                )
                
                fig_int.update_layout(
                    template='plotly_dark',
                    height=320,
                    margin=dict(l=10, r=50, t=20, b=30),
                    xaxis=dict(showgrid=False, title='', fixedrange=True),
                    yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Faiz (%)', side='right', fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False
                )
                st.plotly_chart(fig_int, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
            else:
                st.info("Faiz verisi Excel'den okunamadı.")

        with col_gdp:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>📊 Türkiye GSYH (World Bank)</h4>", unsafe_allow_html=True)
            
            @st.cache_data
            def load_gdp_data():
                try:
                    import pandas as pd
                    df = pd.read_excel('data/turkey_gdp_worldbank.xls', skiprows=3)
                    turkey_row = df[df['Country Name'].isin(['Turkiye', 'Turkey', 'Türkiye'])]
                    if turkey_row.empty:
                        return None, None
                    row = turkey_row.iloc[0]
                    years = []
                    values = []
                    for col in df.columns[4:]:
                        try:
                            year = int(float(col))
                            val = row[col]
                            if pd.notna(val) and val > 0:
                                years.append(year)
                                values.append(float(val) / 1e12)  # Trilyon USD
                        except (ValueError, TypeError):
                            pass
                    return years, values
                except Exception:
                    return None, None

            gdp_years, gdp_values = load_gdp_data()
            if gdp_years and gdp_values:
                # Son değer annotation
                last_year = gdp_years[-1]
                last_val = gdp_values[-1]

                fig_gdp = go.Figure()
                fig_gdp.add_trace(go.Scatter(
                    x=gdp_years,
                    y=gdp_values,
                    mode='lines',
                    line=dict(color='#FFD700', width=2.5, shape='spline'),
                    fill='tozeroy',
                    fillcolor='rgba(255, 215, 0, 0.12)',
                    hovertemplate='<b>%{x}</b>: $%{y:.3f} Trilyon<extra></extra>'
                ))
                fig_gdp.add_annotation(
                    x=last_year, y=last_val,
                    text=f"${last_val:.2f}T",
                    showarrow=True,
                    arrowhead=2,
                    arrowcolor='#FFD700',
                    font=dict(color='white', size=11, family='monospace'),
                    bgcolor='#FFD700',
                    bordercolor='rgba(0,0,0,0)',
                    borderwidth=0,
                    borderpad=5
                )
                fig_gdp.update_layout(
                    template='plotly_dark',
                    height=320,
                    margin=dict(l=10, r=50, t=20, b=30),
                    xaxis=dict(showgrid=False, title='', fixedrange=True),
                    yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Trilyon USD', side='right', fixedrange=True),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False
                )
                st.plotly_chart(fig_gdp, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
            else:
                st.info("GSYH verisi okunamadı.")

        # ─── Hazine Bonosu ve Devlet Tahvilleri ───
        st.markdown("""
<div style="margin-top: 35px; margin-bottom: 15px; border-bottom: 1px solid #37474f; padding-bottom: 5px;">
<h3 style="color: #90a4ae; font-size: 16px; font-weight: bold; margin: 0;">📜 Hazine Bonosu ve Devlet Tahvilleri (İş Bankası)</h3>
</div>
""", unsafe_allow_html=True)

        @st.cache_data(ttl=3600)
        def load_isbank_bonds():
            import requests
            import re
            import pandas as pd
            try:
                url = 'https://www.isbank.com.tr/fiyatoran/FiyatTabloGosterV2.asp?trkd=*HZD&tip=HTML'
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                r.encoding = 'windows-1254'
                
                rows = re.findall(r'<tr.*?>(.*?)</tr>', r.text, re.IGNORECASE | re.DOTALL)
                data = []
                for row in rows:
                    cols = re.findall(r'<td.*?>(.*?)</td>', row, re.IGNORECASE | re.DOTALL)
                    cleaned_cols = [re.sub(r'<[^>]+>', '', col).strip() for col in cols]
                    if cleaned_cols and len(cleaned_cols) > 5:
                        data.append(cleaned_cols)
                        
                if len(data) > 1:
                    df = pd.DataFrame(data[1:], columns=data[0])
                    return df
            except Exception:
                pass
            return None

        col_bond_table, col_yield_curve, col_bond_calc = st.columns(3, gap="large")
        if offline_mode:
            _cached_bonds = load_cache("isbank_bonds.json")
            if _cached_bonds and 'data' in _cached_bonds and 'columns' in _cached_bonds:
                df_bonds_full = pd.DataFrame(_cached_bonds['data'], columns=_cached_bonds['columns'])
            else:
                df_bonds_full = load_isbank_bonds()
                if df_bonds_full is not None and not df_bonds_full.empty:
                    save_cache("isbank_bonds.json", {'columns': df_bonds_full.columns.tolist(), 'data': df_bonds_full.values.tolist()})
        else:
            try:
                df_bonds_full = load_isbank_bonds()
                if df_bonds_full is not None and not df_bonds_full.empty:
                    save_cache("isbank_bonds.json", {'columns': df_bonds_full.columns.tolist(), 'data': df_bonds_full.values.tolist()})
            except Exception:
                _cached_bonds = load_cache("isbank_bonds.json")
                if _cached_bonds and 'data' in _cached_bonds:
                    df_bonds_full = pd.DataFrame(_cached_bonds['data'], columns=_cached_bonds['columns'])
                else:
                    df_bonds_full = None

        with col_bond_table:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>📊 Fiyat ve Oran Tablosu</h4>", unsafe_allow_html=True)
            if df_bonds_full is not None and not df_bonds_full.empty:
                keep_cols = [c for c in df_bonds_full.columns if "Kodu" in c or "Vade Tarihi" in c or "Sat" in c and "Fiyat" in c or "Sat" in c and "Bileşik" in c]
                df_bonds_display = df_bonds_full[keep_cols] if keep_cols else df_bonds_full
                st.dataframe(df_bonds_display, hide_index=True, height=345, use_container_width=True)
            else:
                st.info("Tahvil verileri şu anda çekilemedi.")

        with col_yield_curve:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>📈 Getiri Eğrisi (Yield Curve)</h4>", unsafe_allow_html=True)
            if df_bonds_full is not None and not df_bonds_full.empty:
                try:
                    import pandas as pd
                    vkg_col = next((c for c in df_bonds_full.columns if "V.K.G" in c or "Kalan" in c), None)
                    yield_col = next((c for c in df_bonds_full.columns if "Sat" in c and "Bileşik" in c and "Faiz" in c), None)
                    
                    if vkg_col and yield_col:
                        df_yc = df_bonds_full[[vkg_col, yield_col]].copy()
                        df_yc[vkg_col] = pd.to_numeric(df_yc[vkg_col], errors='coerce')
                        df_yc[yield_col] = pd.to_numeric(df_yc[yield_col], errors='coerce')
                        df_yc = df_yc.dropna().sort_values(by=vkg_col)
                        
                        fig_yc = go.Figure()
                        fig_yc.add_trace(go.Scatter(
                            x=df_yc[vkg_col],
                            y=df_yc[yield_col],
                            mode='lines+markers',
                            name='Getiri Eğrisi',
                            line=dict(color='#E040FB', width=3, shape='spline'),
                            marker=dict(size=8, color='#E040FB', line=dict(width=1.5, color='#11151C')),
                            fill='tozeroy',
                            fillcolor='rgba(224, 64, 251, 0.15)',
                            hovertemplate='<b>Vadeye Kalan:</b> %{x} Gün<br><b>Faiz:</b> %{y:.2f}%<extra></extra>'
                        ))
                        
                        fig_yc.update_layout(
                            template='plotly_dark',
                            height=380,
                            margin=dict(l=10, r=10, t=20, b=30),
                            xaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Vadeye Kalan (Gün)', fixedrange=True),
                            yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='Bileşik Faiz (%)', side='left', fixedrange=True),
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            dragmode=False
                        )
                        st.plotly_chart(fig_yc, use_container_width=True, config={'displayModeBar': False, 'staticPlot': False})
                    else:
                        st.warning("Getiri eğrisi için gerekli kolonlar bulunamadı.")
                except Exception as e:
                    st.error(f"Grafik çizilemedi: {e}")
            else:
                st.info("Veri bulunamadığı için grafik çizilemiyor.")

        with col_bond_calc:
            st.markdown("<h4 style='color: #b0bec5; font-size: 13px; margin-bottom: 5px;'>💰 Potansiyel Kar Hesaplama</h4>", unsafe_allow_html=True)
            if df_bonds_full is not None and not df_bonds_full.empty:
                vkg_col = next((c for c in df_bonds_full.columns if "V.K.G" in c or "Kalan" in c), None)
                yield_col = next((c for c in df_bonds_full.columns if "Sat" in c and "Bileşik" in c and "Faiz" in c), None)
                isin_col = next((c for c in df_bonds_full.columns if "ISIN" in c or "Kodu" in c), None)
                
                if vkg_col and yield_col and isin_col:
                    anapara = st.number_input("Yatırım Tutarı (₺)", min_value=1000, value=100000, step=1000)
                    
                    bond_options = {}
                    for _, row in df_bonds_full.iterrows():
                        isin = str(row[isin_col]).split('(')[0].strip()
                        vkg = pd.to_numeric(row[vkg_col], errors='coerce')
                        faiz = pd.to_numeric(row[yield_col], errors='coerce')
                        if pd.notna(vkg) and pd.notna(faiz):
                            bond_options[f"{isin} ({int(vkg)} Gün)"] = {"vkg": vkg, "faiz": faiz}
                            
                    if bond_options:
                        selected_bond = st.selectbox("Tahvil Seçimi", options=list(bond_options.keys()))
                        selected_data = bond_options[selected_bond]
                        
                        vkg = selected_data["vkg"]
                        faiz = selected_data["faiz"]
                        
                        # Yaklaşık faiz formülü (Bileşik): FV = PV * (1 + r/100)^(vkg/365)
                        vade_sonu_tutar = anapara * ((1 + (faiz / 100)) ** (vkg / 365))
                        net_kazanc = vade_sonu_tutar - anapara
                        
                        st.markdown(f"""
                        <div style="background-color: #131722; padding: 15px; border-radius: 8px; border: 1px solid #2a2e39; margin-top: 15px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                                <span style="color: #b0bec5; font-size: 13px;">Seçilen Faiz:</span>
                                <span style="color: #E040FB; font-weight: bold; font-size: 13px;">%{faiz:.2f}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                                <span style="color: #b0bec5; font-size: 13px;">Vadeye Kalan:</span>
                                <span style="color: white; font-weight: bold; font-size: 13px;">{int(vkg)} Gün</span>
                            </div>
                            <hr style="border: 0; height: 1px; background: #2a2e39; margin: 10px 0;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                                <span style="color: #b0bec5; font-size: 13px;">Tahmini Net Kazanç:</span>
                                <span style="color: #26a69a; font-weight: bold; font-size: 14px;">+{net_kazanc:,.2f} ₺</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: #90a4ae; font-size: 14px; font-weight: bold;">Vade Sonu Toplam:</span>
                                <span style="color: white; font-weight: bold; font-size: 16px;">{vade_sonu_tutar:,.2f} ₺</span>
                            </div>
                        </div>
                        <div style="font-size: 10px; color: #78909c; margin-top: 8px; font-style: italic;">
                            * Hesaplama brüt oranlar üzerindendir, %10 stopaj kesintisi dahil edilmemiştir.
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.warning("Hesaplama için uygun tahvil bulunamadı.")
                else:
                    st.warning("Gerekli kolonlar bulunamadı.")
            else:
                st.info("Veri yok.")


    else:
        st.warning("Hisse verisi çekilemedi. Lütfen piyasa durumunu ve internet bağlantınızı kontrol edin.")

except Exception as e:
    error_msg = str(e)
    if "too many requests" in error_msg.lower() or "rate limit" in error_msg.lower() or "429" in error_msg.lower():
        st.error("⚠️ Yahoo Finance rate limit'e ulaşıldı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin.")
        st.info("💡 **İpucu:** Sayfayı çok sık yenilememek bu hatayı önler. Veriler otomatik olarak 5 dakika önbelleğe alınmaktadır.")
    else:
        st.error(f"Veri çekilirken bir hata oluştu: {e}")
