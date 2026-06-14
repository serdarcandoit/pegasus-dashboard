"""
Pegasus Dashboard — Yerel Önbellek (Cache) Oluşturucu
=====================================================
Bu script, tüm API'lerden güncel verileri çekip data/cache/ klasörüne
JSON dosyaları olarak kaydeder.

Kullanım:
    python generate_cache.py

Sonrasında GitHub'a push ederek bulut ortamında bu verilerle çalışabilirsiniz.
"""

import yfinance as yf
import json
import time
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TICKER = "PGSUS.IS"
CURRENCY_TICKERS = {
    "USD/TRY": {"symbol": "USDTRY=X", "flag": "🇺🇸", "label": "Dolar ($)"},
    "EUR/TRY": {"symbol": "EURTRY=X", "flag": "🇪🇺", "label": "Euro (€)"},
    "GBP/TRY": {"symbol": "GBPTRY=X", "flag": "🇬🇧", "label": "Sterlin (£)"},
    "BIST100": {"symbol": "XU100.IS", "flag": "XU100", "label": "BIST 100"},
    "BIST30": {"symbol": "XU030.IS", "flag": "XU030", "label": "BIST 30"},
}
GOLD_TICKER = "GC=F"
TROY_OUNCE_GRAM = 31.1035


def _json_serializer(obj):
    if hasattr(obj, 'item'):
        val = obj.item()
        if isinstance(val, float) and val != val:
            return None
        return val
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if isinstance(obj, float) and obj != obj:
        return None
    return str(obj)


def save(filename, data):
    filepath = CACHE_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, default=_json_serializer)
    print(f"  ✅ {filename} kaydedildi")


def generate_currency_cache():
    print("\n📌 Döviz & Altın verileri çekiliyor...")
    results = {}
    for key, meta in CURRENCY_TICKERS.items():
        try:
            t = yf.Ticker(meta["symbol"])
            h = t.history(period="5d", interval="1d")
            if not h.empty and len(h) >= 2:
                current = float(h['Close'].iloc[-1])
                previous = float(h['Close'].iloc[-2])
                change_pct = ((current - previous) / previous) * 100
                results[key] = {"price": current, "change": float(change_pct), **meta}
            elif not h.empty:
                current = float(h['Close'].iloc[-1])
                results[key] = {"price": current, "change": 0.0, **meta}
            print(f"    {key}: {results.get(key, {}).get('price', 'HATA')}")
        except Exception as e:
            print(f"    ⚠️ {key}: {e}")
        time.sleep(1)  # Rate limit koruması

    # Altın
    try:
        t = yf.Ticker(GOLD_TICKER)
        h_gold = t.history(period="5d", interval="1d")
        usd_try_price = results.get("USD/TRY", {}).get("price")
        if not h_gold.empty and usd_try_price:
            gold_usd_current = float(h_gold['Close'].iloc[-1])
            gold_usd_previous = float(h_gold['Close'].iloc[-2]) if len(h_gold) >= 2 else gold_usd_current
            gram_try_current = (gold_usd_current * usd_try_price) / TROY_OUNCE_GRAM
            gram_try_previous = (gold_usd_previous * usd_try_price) / TROY_OUNCE_GRAM
            change_pct = ((gram_try_current - gram_try_previous) / gram_try_previous) * 100
            results["GOLD"] = {"price": float(gram_try_current), "change": float(change_pct), "flag": "🥇", "label": "Gram Altın (g)"}
            print(f"    GOLD: {gram_try_current:.2f} ₺")
    except Exception as e:
        print(f"    ⚠️ GOLD: {e}")

    if results:
        save("currency_data.json", results)
    return results


def generate_stock_history_cache():
    print("\n📌 PGSUS hisse fiyat geçmişi çekiliyor...")
    stock = yf.Ticker(TICKER)
    intervals = {
        "1d": {"period": "max", "interval": "1d"},
        "1wk": {"period": "max", "interval": "1wk"},
        "1mo": {"period": "max", "interval": "1mo"},
        "3mo": {"period": "max", "interval": "3mo"},
    }

    for interval_key, params in intervals.items():
        try:
            hist = stock.history(period=params["period"], interval=params["interval"])
            if not hist.empty:
                cache_data = {
                    'index': [str(d) for d in hist.index.tolist()],
                    'open': [float(x) for x in hist['Open'].tolist()],
                    'high': [float(x) for x in hist['High'].tolist()],
                    'low': [float(x) for x in hist['Low'].tolist()],
                    'close': [float(x) for x in hist['Close'].tolist()],
                    'calc_50_ma': None,
                    'calc_200_ma': None
                }
                # Günlük veri için MA hesapla
                if interval_key == "1d":
                    if len(hist) >= 50:
                        cache_data['calc_50_ma'] = float(hist['Close'].rolling(window=50).mean().iloc[-1])
                    if len(hist) >= 200:
                        cache_data['calc_200_ma'] = float(hist['Close'].rolling(window=200).mean().iloc[-1])
                save(f"stock_history_{interval_key}.json", cache_data)
                print(f"    {interval_key}: {len(hist)} veri noktası")
            time.sleep(2)
        except Exception as e:
            print(f"    ⚠️ {interval_key}: {e}")

    # Yıllık (özel resample)
    try:
        hist = stock.history(period="max", interval="1mo")
        if not hist.empty:
            h = hist.resample('YE').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'
            }).dropna()
            cache_data = {
                'index': [str(d) for d in h.index.tolist()],
                'open': [float(x) for x in h['Open'].tolist()],
                'high': [float(x) for x in h['High'].tolist()],
                'low': [float(x) for x in h['Low'].tolist()],
                'close': [float(x) for x in h['Close'].tolist()],
                'calc_50_ma': None,
                'calc_200_ma': None
            }
            save("stock_history_1y.json", cache_data)
            print(f"    1y: {len(h)} veri noktası")
    except Exception as e:
        print(f"    ⚠️ 1y: {e}")


def generate_stock_info_cache():
    print("\n📌 PGSUS temel bilgileri çekiliyor...")
    try:
        stock = yf.Ticker(TICKER)
        info_data = stock.info
        data = dict(info_data) if isinstance(info_data, dict) else {}

        # Çeyreklik gelir/kar
        try:
            net_incomes = stock.quarterly_income_stmt.loc['Net Income']
            revenues = stock.quarterly_income_stmt.loc['Total Revenue']
            data['quarterly_net_income'] = float(net_incomes.iloc[0])
            series_dict = {}
            for date, val in net_incomes.items():
                if val == val:
                    rev = revenues.get(date, None)
                    if rev == rev and rev is not None:
                        series_dict[str(date)[:10]] = {'net_income': float(val), 'revenue': float(rev)}
            data['quarterly_financials_series'] = series_dict
        except Exception:
            data['quarterly_net_income'] = None
            data['quarterly_financials_series'] = {}

        # İş Yatırım verileri
        try:
            import requests
            code = TICKER.replace('.IS', '')
            year = datetime.now().year
            all_series = {}
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
                ni_vals = [float(ni_item.get('value4') or 0), float(ni_item.get('value3') or 0),
                           float(ni_item.get('value2') or 0), float(ni_item.get('value1') or 0)]
                rev_vals = [float(rev_item.get('value4') or 0), float(rev_item.get('value3') or 0),
                            float(rev_item.get('value2') or 0), float(rev_item.get('value1') or 0)]
                q_dates = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"]
                for i in range(4):
                    if ni_vals[i] != 0 or rev_vals[i] != 0:
                        all_series[q_dates[i]] = {'net_income': ni_vals[i], 'revenue': rev_vals[i]}
            if all_series:
                sorted_dates = sorted(list(all_series.keys()))
                last_4 = sorted_dates[-4:]
                data['quarterly_financials_series'] = {k: all_series[k] for k in last_4}
                data['quarterly_net_income'] = data['quarterly_financials_series'][last_4[-1]]['net_income']
            print("    İş Yatırım verileri çekildi")
        except Exception as e:
            print(f"    ⚠️ İş Yatırım: {e}")

        # Beta (TradingView)
        try:
            import requests as _req
            tv_symbol = TICKER.replace('.IS', '')
            scan_url = "https://scanner.tradingview.com/global/scan"
            scan_payload = {"symbols": {"tickers": [f"BIST:{tv_symbol}"]}, "columns": ["beta_1_year"]}
            scan_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            scan_res = _req.post(scan_url, json=scan_payload, headers=scan_headers, timeout=10)
            if scan_res.status_code == 200:
                scan_data = scan_res.json()
                if scan_data.get("data") and len(scan_data["data"]) > 0:
                    beta_val = scan_data["data"][0]["d"][0]
                    if beta_val is not None:
                        data['beta'] = round(float(beta_val), 2)
                        print(f"    Beta: {data['beta']}")
        except Exception:
            pass

        if data:
            save("stock_info.json", data)
            print(f"    Toplam {len(data)} bilgi alanı kaydedildi")
    except Exception as e:
        print(f"    ⚠️ Stock Info: {e}")


def generate_bonds_cache():
    print("\n📌 İş Bankası tahvil verileri çekiliyor...")
    try:
        import requests
        import re
        import pandas as pd
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
            save("isbank_bonds.json", {'columns': df.columns.tolist(), 'data': df.values.tolist()})
            print(f"    {len(df)} tahvil kaydedildi")
        else:
            print("    ⚠️ Tahvil verisi bulunamadı")
    except Exception as e:
        print(f"    ⚠️ Tahvil: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Pegasus Dashboard — Önbellek Oluşturucu")
    print("=" * 60)

    generate_currency_cache()
    time.sleep(3)  # Rate limit koruması
    generate_stock_history_cache()
    time.sleep(3)
    generate_stock_info_cache()
    time.sleep(1)
    generate_bonds_cache()

    # Son güncelleme zamanını kaydet
    meta_path = CACHE_DIR / "last_update.txt"
    meta_path.write_text(datetime.now().strftime("%d/%m/%Y %H:%M"), encoding='utf-8')

    print("\n" + "=" * 60)
    print("  ✅ Tüm önbellek dosyaları oluşturuldu!")
    print(f"  📂 Konum: {CACHE_DIR.resolve()}")
    print("  📤 Şimdi GitHub'a push edebilirsiniz.")
    print("=" * 60)
    print("\nOluşturulan dosyalar:")
    for f in sorted(CACHE_DIR.iterdir()):
        size = f.stat().st_size
        print(f"  📄 {f.name} ({size:,} bytes)")
