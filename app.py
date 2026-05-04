import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import time

# Sayfa ayarları
st.set_page_config(page_title="Pegasus (PGSUS) Dashboard", page_icon="✈️", layout="wide")

# Borsa İstanbul için hisse sembolü (Yahoo Finance formatı)
TICKER = "PGSUS.IS"

# TradingView Tarzı Kompakt Araç Çubuğu
st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
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


def fetch_with_retry(func, max_retries=3, initial_wait=5):
    """Yahoo Finance API çağrılarını rate limit hatalarına karşı retry mekanizması ile yapar."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e).lower()
            # Rate limit veya Too Many Requests hatası kontrolü
            if "too many requests" in error_msg or "rate limit" in error_msg or "429" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = initial_wait * (2 ** attempt)  # Exponential backoff: 5s, 10s, 20s
                    time.sleep(wait_time)
                else:
                    raise  # Son denemede de başarısızsa hatayı fırlat
            else:
                raise  # Rate limit dışı hatalar direkt fırlatılır


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
        return stock.info
    
    return fetch_with_retry(_fetch_info)


try:
    # Cached fonksiyonları spinner dışında çağır (Streamlit Cloud uyumluluğu)
    hist, calc_50_ma, calc_200_ma = load_all_data(TICKER, selected_interval)
    info = load_info(TICKER)
    
    if not hist.empty:
        # Son gün kapanış ve bir önceki gün kapanış fiyatlarını al
        current_price = hist['Close'].iloc[-1]
        previous_price = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        
        # Değişimleri hesapla
        price_change = current_price - previous_price
        pct_change = (price_change / previous_price) * 100
        
        # Güncel fiyatı TradingView tarzı, tek satırda şık bir başlık olarak gösterelim
        price_color = "#26a69a" if price_change >= 0 else "#ef5350"
        sign = "+" if price_change >= 0 else ""
        
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
                height=600, # Chart yüksekliğini orijinaline çektik
                dragmode='pan' # Tıklayıp sürükleyince grafiği kaydırma (pan) özelliğini açar
            )
            st.plotly_chart(fig, width='stretch', config={'scrollZoom': True})
            
        with col_fundamentals:
            def format_val(val, format_str="{:.2f}"):
                return format_str.format(val) if val is not None else "Veri Yok"
                
            mcap = info.get('marketCap')
            mcap_str = f"{mcap / 1_000_000_000:.2f} Milyar ₺" if mcap else "Veri Yok"
            
            # Kendi hesapladığımız kesin MA değerlerini kullanıyoruz, yoksa API'nin verdiğini fallback olarak al
            ma50 = calc_50_ma or info.get('fiftyDayAverage')
            ma200 = calc_200_ma or info.get('twoHundredDayAverage')
            
            # HTML ve CSS ile çok daha şık, kompakt ve hizalı bir tablo (TradingView sidebar benzeri)
            html_content = f"""
<div style="font-family: sans-serif; margin-top: 0px;">
<h4 style="color: #90a4ae; font-size: 14px; margin-bottom: 10px; border-bottom: 1px solid #37474f; padding-bottom: 5px;">DEĞERLEMELER</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">PD/DD Oranı</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{format_val(info.get('priceToBook'))}</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">F/K (Fiyat/Kazanç)</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{format_val(info.get('trailingPE'))}</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 25px;">
<span style="color: #b0bec5; font-size: 14px;">Beta (Volatilite)</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{format_val(info.get('beta'))}</span>
</div>

<h4 style="color: #90a4ae; font-size: 14px; margin-bottom: 10px; border-bottom: 1px solid #37474f; padding-bottom: 5px;">ORTALAMALAR</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">50 Günlük Ort.</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{format_val(ma50)} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 25px;">
<span style="color: #b0bec5; font-size: 14px;">200 Günlük Ort.</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{format_val(ma200)} ₺</span>
</div>

<h4 style="color: #90a4ae; font-size: 14px; margin-bottom: 10px; border-bottom: 1px solid #37474f; padding-bottom: 5px;">PERFORMANS</h4>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">52 Hafta Zirve</span>
<span style="font-weight: bold; color: #26a69a; font-size: 14px;">{format_val(info.get('fiftyTwoWeekHigh'))} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">52 Hafta Dip</span>
<span style="font-weight: bold; color: #ef5350; font-size: 14px;">{format_val(info.get('fiftyTwoWeekLow'))} ₺</span>
</div>
<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
<span style="color: #b0bec5; font-size: 14px;">Piyasa Değeri</span>
<span style="font-weight: bold; color: white; font-size: 14px;">{mcap_str}</span>
</div>

<div style="margin-top: 40px; display: flex; gap: 10px; align-items: flex-start; text-align: left; color: #78909c; font-size: 13px; font-style: italic; border-top: 1px dashed #37474f; padding-top: 15px; line-height: 1.5;">
<span style="font-size: 16px; margin-top: 1px;">ℹ️</span>
<div>
Veriler <b>Yahoo Finance</b> üzerinden sağlanmakta olup <b>5 dakikada bir</b> önbelleğe alınmaktadır.<br>
Güncel fiyatı görmek için 5 dakikanın ardından <b>sayfayı yenileyebilirsiniz.</b>
</div>
</div>
</div>
"""
            st.markdown(html_content, unsafe_allow_html=True)

    else:
        st.warning("Hisse verisi çekilemedi. Lütfen piyasa durumunu ve internet bağlantınızı kontrol edin.")

except Exception as e:
    error_msg = str(e)
    if "too many requests" in error_msg.lower() or "rate limit" in error_msg.lower() or "429" in error_msg.lower():
        st.error("⚠️ Yahoo Finance rate limit'e ulaşıldı. Lütfen 1-2 dakika bekleyip sayfayı yenileyin.")
        st.info("💡 **İpucu:** Sayfayı çok sık yenilememek bu hatayı önler. Veriler otomatik olarak 5 dakika önbelleğe alınmaktadır.")
    else:
        st.error(f"Veri çekilirken bir hata oluştu: {e}")
