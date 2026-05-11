import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import time

# Sayfa ayarları
st.set_page_config(page_title="Pegasus (PGSUS) Dashboard", page_icon="✈️", layout="wide")

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
def load_currency_data():
    """Döviz kurları (USD, EUR, GBP → TRY) ve gram altın fiyatını çeker."""
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
    currency_data = load_currency_data()
    render_ticker_bar(currency_data)
except Exception:
    render_ticker_bar({{}})  # Hata durumunda boş göster

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
def load_all_data(ticker, interval):
    """Tek bir fonksiyonla hem grafik verisini hem hareketli ortalamaları çeker.
    Bu sayede Yahoo Finance'e giden istek sayısı minimuma iner."""
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

    return hist, calc_50_ma, calc_200_ma


@st.cache_data(ttl=21600)  # Temel analiz verileri yavaş değiştiği için 6 saat önbellek
def load_info(ticker):
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
                for y in [year, year-1, year-2]:
                    url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={code}&exchange=TRY&financialGroup=XI_29&year1={y}&period1=12&year2={y}&period2=9&year3={y}&period3=6&year4={y}&period4=3"
                    res = requests.get(url, timeout=5).json()
                    if 'value' in res and len(res['value']) > 0:
                        ni_item = next((item for item in res['value'] if item['itemCode'] == '3L'), None)
                        rev_item = next((item for item in res['value'] if item['itemCode'] == '3C'), None)
                        if ni_item and rev_item and str(ni_item.get('value4') or '') != '':
                            ni_c = [
                                float(ni_item.get('value4') or 0),
                                float(ni_item.get('value3') or 0),
                                float(ni_item.get('value2') or 0),
                                float(ni_item.get('value1') or 0)
                            ]
                            rev_c = [
                                float(rev_item.get('value4') or 0),
                                float(rev_item.get('value3') or 0),
                                float(rev_item.get('value2') or 0),
                                float(rev_item.get('value1') or 0)
                            ]
                            
                            # Kullanıcı Seçenek 1'i (İş Yatırım Kümülatif formatı) seçtiği için doğrudan kümülatif veriyi kullanıyoruz
                            ni_s = ni_c
                            rev_s = rev_c
                            
                            q_dates = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"]
                            new_series = {}
                            for i in range(4):
                                if ni_c[i] != 0:
                                    new_series[q_dates[i]] = {'net_income': ni_s[i], 'revenue': rev_s[i]}
                            
                            if new_series:
                                data['quarterly_financials_series'] = new_series
                                last_key = sorted(list(new_series.keys()))[-1]
                                data['quarterly_net_income'] = new_series[last_key]['net_income']
                                
                                # Y/Y Büyümeyi Hesapla (Önceki yılın aynı dönemiyle)
                                try:
                                    last_month = last_key.split('-')[1]
                                    period = int(last_month)
                                    prev_y = y - 1
                                    prev_url = f"https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo?companyCode={code}&exchange=TRY&financialGroup=XI_29&year1={prev_y}&period1={period}&year2={prev_y}&period2=9&year3={prev_y}&period3=6&year4={prev_y}&period4=3"
                                    prev_res = requests.get(prev_url, timeout=5).json()
                                    if 'value' in prev_res and len(prev_res['value']) > 0:
                                        prev_ni_item = next((item for item in prev_res['value'] if item['itemCode'] == '3L'), None)
                                        if prev_ni_item:
                                            prev_val = float(prev_ni_item.get('value1') or 0)
                                            if prev_val != 0:
                                                growth = (data['quarterly_net_income'] - prev_val) / abs(prev_val)
                                                data['earningsQuarterlyGrowth'] = growth
                                except Exception:
                                    pass
                            break
            except Exception:
                pass

        return data
    
    return fetch_with_retry(_fetch_info)


try:
    with st.spinner("Veriler yükleniyor..."):
        hist, calc_50_ma, calc_200_ma = load_all_data(TICKER, selected_interval)
        info = load_info(TICKER)
    
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
                    xaxis=dict(showgrid=False, title='', type='category', tickfont=dict(size=9, color="#90a4ae")),
                    yaxis=dict(showgrid=True, gridcolor='#2a2e39', title='', showticklabels=False, zerolinecolor='#37474f'),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                
                st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': False})
                
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

    else:
        st.warning("Hisse verisi çekilemedi. Lütfen piyasa durumunu ve internet bağlantınızı kontrol edin.")

except Exception as e:
    error_msg = str(e)
    if "too many requests" in error_msg.lower() or "rate limit" in error_msg.lower() or "429" in error_msg.lower():
        st.error("⚠️ Yahoo Finance rate limit'e ulaşıldı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin.")
        st.info("💡 **İpucu:** Sayfayı çok sık yenilememek bu hatayı önler. Veriler otomatik olarak 5 dakika önbelleğe alınmaktadır.")
    else:
        st.error(f"Veri çekilirken bir hata oluştu: {e}")
