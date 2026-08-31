import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import time
import re
import os
import datetime as dt

# ページ設定
st.set_page_config(
    page_title="商品データ取得ツール",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# セッション状態の初期化
if 'df_onlinestore' not in st.session_state:
    st.session_state.df_onlinestore = None
if 'df_rakuten' not in st.session_state:
    st.session_state.df_rakuten = None
if 'df_yahoo' not in st.session_state:
    st.session_state.df_yahoo = None
if 'sale_list' not in st.session_state:
    st.session_state.sale_list = None
if 'not_found_reasons_onlinestore' not in st.session_state:
    st.session_state.not_found_reasons_onlinestore = {}
if 'not_found_reasons_rakuten' not in st.session_state:
    st.session_state.not_found_reasons_rakuten = {}
if 'not_found_reasons_yahoo' not in st.session_state:
    st.session_state.not_found_reasons_yahoo = {}

# タイトル
st.title("📊 商品データ取得ツール")
st.markdown("---")

# CSVファイル読み込み機能
def load_csv_data_from_upload(uploaded_file):
    """アップロードされたCSVファイルを読み込む関数"""
    try:
        # ファイルを読み込み
        sale_list = pd.read_csv(uploaded_file)
        
        # 必須列のチェック
        required_cols = ['商品コード', '通販単価', '送料区分名']
        missing = [c for c in required_cols if c not in sale_list.columns]
        if missing:
            st.error(f"必須列が不足しています: {', '.join(missing)}")
            return None
        
        # データの正規化（安定動作のため）
        # 商品コード: 前後の空白を削除
        sale_list['商品コード'] = sale_list['商品コード'].astype(str).str.strip()
        # 大分類コード: 文字列"01"等を数値に変換（楽天・Yahoo APIの分類に必要）
        if '大分類コード' in sale_list.columns:
            sale_list['大分類コード'] = pd.to_numeric(
                sale_list['大分類コード'].astype(str).str.strip(),
                errors='coerce'
            ).fillna(0).astype(int)
        # 商品名: 前後の空白を削除（表示用）
        if '商品名' in sale_list.columns:
            sale_list['商品名'] = sale_list['商品名'].astype(str).str.strip()
        
        st.session_state.sale_list = sale_list
        st.success(f"CSVファイルを読み込みました: {uploaded_file.name}")
        return sale_list
    except Exception as e:
        st.error(f"CSVファイルの読み込みに失敗しました: {e}")
        return None


# 自社サイトスクレイピング関数
def scrape_own_site(sale_list):
    """自社サイトの商品情報をスクレイピングする関数"""
    st.info("自社サイトのスクレイピングを開始します...")
    
    # 商品情報を格納するリスト
    onlinestore_data = []
    # 取得できなかった商品とその理由を記録
    not_found_reasons = {}
    
    # プログレスバー
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_items = len(sale_list['商品コード'])
    
    for idx, code in enumerate(sale_list['商品コード']):
        try:
            # 商品コードの正規化（前後の空白を削除）
            code = str(code).strip()
            # 進捗更新
            progress = (idx + 1) / total_items
            progress_bar.progress(progress)
            status_text.text(f"処理中: {idx + 1}/{total_items} - 商品コード: {code}")
            
            url = f'https://www.tonya.co.jp/shop/g/g{code}'
            res = requests.get(url)
            
            # HTTPエラーチェック
            if res.status_code != 200:
                not_found_reasons[str(code)] = f"HTTPエラー: {res.status_code}"
                continue
            
            soup = BeautifulSoup(res.text, 'html.parser')

            # 各項目の初期化
            item_dict = {
                'No': None,
                'Name': None,
                'Price': None,
                'Point': None,
                'Stock': None,
                '要確認': '',
                'Icon': []
            }

            # 商品詳細ブロック取得
            detail_div = soup.find('div', class_='goodsproductdetail_')
            if detail_div is None:
                not_found_reasons[str(code)] = "商品詳細ブロックが見つかりませんでした"
                continue

            # 商品コード
            code_span = detail_div.find('span', class_='goodscode_id_number_')
            if code_span:
                item_dict['No'] = int(re.sub('商品コード：', '', code_span.text))

            # 商品名
            name_h2 = detail_div.find('h2', class_='goods_rifhtname_')
            if name_h2:
                item_dict['Name'] = name_h2.text

            # 価格
            price_span = detail_div.find('span', class_='goods_detail_saleprice_')
            if price_span:
                price_text = price_span.text.replace('円（税込）', '')
            else:
                price_h2 = detail_div.find('h2', class_='goods_price_')
                price_text = price_h2.text.replace('円（税込）', '') if price_h2 else None
            if price_text:
                # 金額はカンマ区切りの文字列として格納
                price_int = int(price_text.replace(',', ''))
                item_dict['Price'] = f"{price_int:,}"

            # アイコン
            icon_div = detail_div.find('div', class_='icon_')
            if icon_div:
                for img in icon_div.find_all('img'):
                    src = img.get('src', '')
                    if src == '/img/sys/new.gif':
                        item_dict['Icon'].append('NEW')
                    elif src == '/img/sys/onsales.gif':
                        item_dict['Icon'].append('SALE')
                    elif src == '/img/icon/10000001.png':
                        item_dict['Icon'].append('送料無料')
                    elif src == '/img/icon/10000002.png':
                        item_dict['Icon'].append('よりどり対象')
                    elif src == '/img/icon/10000003.png':
                        item_dict['Icon'].append('期間限定')
                    elif src == '/img/icon/10000004.png':
                        item_dict['Icon'].append('クーポン進呈')
                    elif src == '/img/icon/10000005.png':
                        item_dict['Icon'].append('会員限定')
                    elif src == '/img/icon/10000006.png':
                        item_dict['Icon'].append('オンライン限定')
                    elif src == '/img/icon/10000007.png':
                        item_dict['Icon'].append('NEW')

            # ポイント
            point_ul = soup.find('ul', id='point_stock')
            if point_ul:
                li_list = point_ul.find_all('li')
                if li_list:
                    point_text = li_list[0].text.replace('ポイント：', '').replace('pt', '')
                    try:
                        item_dict['Point'] = int(point_text)
                    except:
                        item_dict['Point'] = None

            # 在庫（◎ / ○ / △ / × など）
            stock_tr = soup.find('tr', class_='id_stock_msg_')
            if stock_tr:
                stock_td = stock_tr.find('td', class_='id_txt')
                if stock_td:
                    item_dict['Stock'] = stock_td.get_text(strip=True)

            # カートボタンあり＝カートが空いていない → 要確認
            cart_btn = detail_div.find('input', class_=re.compile(r'btn_cart'))
            if cart_btn:
                item_dict['要確認'] = '要確認'

            # 辞書をリストに追加
            onlinestore_data.append(item_dict)

        except requests.exceptions.RequestException as e:
            # リクエストエラー
            not_found_reasons[str(code)] = f"リクエストエラー: {str(e)}"
            continue
        except Exception as e:
            # その他のエラー
            not_found_reasons[str(code)] = f"エラー: {str(e)}"
            continue

    # データフレーム化
    column_order = ['No', 'Name', 'Price', 'Point', 'Stock', '要確認', 'Icon', '通販単価', '差額', '送料区分名']
    df_onlinestore = pd.DataFrame(onlinestore_data)
    if df_onlinestore.empty:
        df_onlinestore = pd.DataFrame(columns=column_order)
    else:
        # salelistの「商品コード」「通販単価」「送料区分名」をNoで紐づけ、差額列も追加
        salelist_renamed = sale_list.rename(
            columns={'商品コード': 'No', '通販単価': '通販単価', '送料区分名': '送料区分名'}
        )
        df_onlinestore['No'] = df_onlinestore['No'].astype(str)
        salelist_renamed['No'] = salelist_renamed['No'].astype(str)

        df_onlinestore = pd.merge(
            df_onlinestore, salelist_renamed[['No', '通販単価', '送料区分名']], on='No', how='left'
        )

        df_onlinestore['通販単価'] = df_onlinestore['通販単価'].apply(
            lambda x: f"{int(str(x).replace(',', '')):,}"
            if pd.notnull(x) and str(x).replace(',', '').isdigit()
            else x
        )

        def calc_diff(row):
            try:
                price = int(str(row['Price']).replace(',', ''))
                sale = int(str(row['通販単価']).replace(',', ''))
                return f"{price - sale:,}"
            except Exception:
                return None

        df_onlinestore['差額'] = df_onlinestore.apply(calc_diff, axis=1)
        df_onlinestore = df_onlinestore[column_order]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("スクレイピング完了！")
    
    # 取得できなかった商品の理由をセッション状態に保存
    st.session_state.not_found_reasons_onlinestore = not_found_reasons
    
    return df_onlinestore

# 楽天市場API取得関数
def get_rakuten_data(sale_list):
    """楽天市場APIから商品情報を取得する関数"""
    st.info("楽天市場APIからのデータ取得を開始します...")
    
    REQUEST_URL = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20170706"
    APP_ID = 1027604414937000350

    # 商品コード拡張
    cat1 = sale_list[sale_list['大分類コード'] == 1]
    cat2 = sale_list[sale_list['大分類コード'] == 2]
    other = sale_list[~sale_list['大分類コード'].isin([1, 2])]

    rows = []
    for _, row in cat1.iterrows():
        code = str(row['商品コード'])
        
        # 販売単価1-5の値を安全に取得
        def safe_get_price(price_value):
            try:
                if pd.isna(price_value) or price_value == '' or price_value is None:
                    return 0
                return float(str(price_value).replace(',', ''))
            except (ValueError, TypeError):
                return 0
        
        sale_price1 = safe_get_price(row.get('販売単価1', 0))
        sale_price2 = safe_get_price(row.get('販売単価2', 0))
        sale_price3 = safe_get_price(row.get('販売単価3', 0))
        sale_price4 = safe_get_price(row.get('販売単価4', 0))
        sale_price5 = safe_get_price(row.get('販売単価5', 0))
        
        # 販売単価1-5が0でない場合の計算
        if sale_price1 > 0 or sale_price2 > 0 or sale_price3 > 0 or sale_price4 > 0 or sale_price5 > 0:
            # -50と-100は販売単価1
            for suf in ['-50', '-100']:
                r = row.copy()
                r['商品コード'] = code + suf
                r['通販単価'] = float(str(sale_price1).replace(',', '')) if sale_price1 > 0 else np.nan
                rows.append(r)
            
            # -200は販売単価2×2
            r = row.copy()
            r['商品コード'] = code + '-200'
            r['通販単価'] = float(str(sale_price2).replace(',', '')) * 2 if sale_price2 > 0 else np.nan
            rows.append(r)
            
            # -300は販売単価3×3
            r = row.copy()
            r['商品コード'] = code + '-300'
            r['通販単価'] = float(str(sale_price3).replace(',', '')) * 3 if sale_price3 > 0 else np.nan
            rows.append(r)
            
            # -400は販売単価4×4
            r = row.copy()
            r['商品コード'] = code + '-400'
            r['通販単価'] = float(str(sale_price4).replace(',', '')) * 4 if sale_price4 > 0 else np.nan
            rows.append(r)
            
            # -500は販売単価5×5
            r = row.copy()
            r['商品コード'] = code + '-500'
            r['通販単価'] = float(str(sale_price5).replace(',', '')) * 5 if sale_price5 > 0 else np.nan
            rows.append(r)
        else:
            # 従来の計算方法（販売単価1-5がすべて0の場合）
            for i, suf in enumerate(['-100', '-200', '-300', '-400', '-500'], 1):
                r = row.copy()
                r['商品コード'] = code + suf
                r['通販単価'] = float(str(row['通販単価']).replace(',', '')) * i if row['通販単価'] else np.nan
                rows.append(r)
    
    for _, row in cat2.iterrows():
        code = str(row['商品コード'])
        r = row.copy()
        r['商品コード'] = code + '-50'
        r['通販単価'] = float(str(row['通販単価']).replace(',', '')) if row['通販単価'] else np.nan
        rows.append(r)
    for _, row in other.iterrows():
        r = row.copy()
        r['商品コード'] = str(row['商品コード'])
        r['通販単価'] = float(str(row['通販単価']).replace(',', '')) if row['通販単価'] else np.nan
        rows.append(r)
    sale_list_mod = pd.DataFrame(rows)

    codes = sale_list_mod['商品コード'].astype(str).unique()
    item_list = []
    # 取得できなかった商品とその理由を記録
    not_found_reasons = {}
    
    # プログレスバー
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_codes = len(codes)
    
    for idx, code in enumerate(codes):
        # 進捗更新
        progress = (idx + 1) / total_codes
        progress_bar.progress(progress)
        status_text.text(f"処理中: {idx + 1}/{total_codes} - 商品コード: {code}")
        
        params = {
            "format": "json",
            "shopCode": "tonya",
            "keyword": code,
            "orFlag": 0,
            "hasReviewFlag": 0,
            "applicationId": APP_ID,
            "availability": 1,
            "hits": 30,
            "page": 1,
            'sort': '+itemPrice',
        }
        found = False
        try:
            res = requests.get(REQUEST_URL, params=params)
            if res.status_code != 200:
                not_found_reasons[code] = f"HTTPエラー: {res.status_code}"
                time.sleep(2.1)
                continue
            result = res.json()
        except requests.exceptions.RequestException as e:
            not_found_reasons[code] = f"リクエストエラー: {str(e)}"
            time.sleep(2.1)
            continue
        except Exception as e:
            not_found_reasons[code] = f"エラー: {str(e)}"
            time.sleep(2.1)
            continue
        
        for item in result.get('Items', []):
            d = item['Item']
            url = d.get('itemUrl', '')
            url = url.replace("https://item.rakuten.co.jp/tonya/", "").replace("/?rafcid=wsc_i_is_1027604414937000350", "")
            if url == code:
                # availability=1 で取得しているため、ヒットした商品は在庫あり扱い
                tmp = {
                    'itemCode': url,
                    'itemName': d.get('itemName', ''),
                    'itemPrice': d.get('itemPrice', ''),
                    'pointRate': d.get('pointRate', ''),
                    'postageFlag': "送料込" if d.get('postageFlag') == 0 else "送料別" if d.get('postageFlag') == 1 else "",
                    'Stock': '在庫あり',
                    '要確認': '要確認',
                }
                item_list.append(tmp)
                found = True
                break
        
        if not found:
            not_found_reasons[code] = "APIで商品が見つかりませんでした"
        
        # API制限を考慮して待機（楽天市場API: 1分30リクエスト = 2秒間隔）
        time.sleep(2.1)

    df_rakuten = pd.DataFrame(item_list)
    if df_rakuten.empty:
        df_rakuten = pd.DataFrame(columns=['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', 'Stock', '要確認'])

    df_sales = sale_list_mod[['商品コード', '通販単価', '送料区分名']].rename(columns={'商品コード': 'itemCode'})
    df_merged = pd.merge(df_rakuten, df_sales, on='itemCode', how='left')

    df_merged['itemPrice'] = df_merged['itemPrice'].replace(',', '', regex=True).astype(float)
    df_merged['通販単価'] = df_merged['通販単価'].astype(float)
    df_merged['差額'] = df_merged['itemPrice'] - df_merged['通販単価']

    df_merged['通販単価'] = df_merged['通販単価'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_merged['itemPrice'] = df_merged['itemPrice'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_merged['差額'] = df_merged['差額'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')

    cols = ['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', 'Stock', '要確認', '通販単価', '差額', '送料区分名']
    df_merged = df_merged[cols]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("楽天市場API取得完了！")
    
    # 取得できなかった商品の理由をセッション状態に保存
    st.session_state.not_found_reasons_rakuten = not_found_reasons
    
    return df_merged

# Yahoo!ショッピングAPI取得関数
def get_yahoo_data(sale_list):
    """Yahoo!ショッピングAPIから商品情報を取得する関数"""
    st.info("Yahoo!ショッピングAPIからのデータ取得を開始します...")
    
    # Yahoo!ショッピングAPIのエンドポイント
    # 制限内容: 1アプリケーションIDあたり1日50,000回
    # 商品検索(v3)APIは1分30リクエスト（2秒間隔でリクエスト）
    YAHOO_API_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
    YAHOO_APP_ID = "dj00aiZpPTBCMkFRMnZSNU1sSyZzPWNvbnN1bWVyc2VjcmV0Jng9ZDQ-"
    
    # 商品コード拡張（楽天と同じロジック）
    cat1 = sale_list[sale_list['大分類コード'] == 1]
    cat2 = sale_list[sale_list['大分類コード'] == 2]
    other = sale_list[~sale_list['大分類コード'].isin([1, 2])]

    rows = []
    for _, row in cat1.iterrows():
        code = str(row['商品コード'])
        
        # 販売単価1-5の値を安全に取得
        def safe_get_price(price_value):
            try:
                if pd.isna(price_value) or price_value == '' or price_value is None:
                    return 0
                return float(str(price_value).replace(',', ''))
            except (ValueError, TypeError):
                return 0
        
        sale_price1 = safe_get_price(row.get('販売単価1', 0))
        sale_price2 = safe_get_price(row.get('販売単価2', 0))
        sale_price3 = safe_get_price(row.get('販売単価3', 0))
        sale_price4 = safe_get_price(row.get('販売単価4', 0))
        sale_price5 = safe_get_price(row.get('販売単価5', 0))
        
        # 販売単価1-5が0でない場合の計算
        if sale_price1 > 0 or sale_price2 > 0 or sale_price3 > 0 or sale_price4 > 0 or sale_price5 > 0:
            # -50と-100は販売単価1
            for suf in ['-50', '-100']:
                r = row.copy()
                r['商品コード'] = code + suf
                r['通販単価'] = float(str(sale_price1).replace(',', '')) if sale_price1 > 0 else np.nan
                rows.append(r)
            
            # -200は販売単価2×2
            r = row.copy()
            r['商品コード'] = code + '-200'
            r['通販単価'] = float(str(sale_price2).replace(',', '')) * 2 if sale_price2 > 0 else np.nan
            rows.append(r)
            
            # -300は販売単価3×3
            r = row.copy()
            r['商品コード'] = code + '-300'
            r['通販単価'] = float(str(sale_price3).replace(',', '')) * 3 if sale_price3 > 0 else np.nan
            rows.append(r)
            
            # -400は販売単価4×4
            r = row.copy()
            r['商品コード'] = code + '-400'
            r['通販単価'] = float(str(sale_price4).replace(',', '')) * 4 if sale_price4 > 0 else np.nan
            rows.append(r)
            
            # -500は販売単価5×5
            r = row.copy()
            r['商品コード'] = code + '-500'
            r['通販単価'] = float(str(sale_price5).replace(',', '')) * 5 if sale_price5 > 0 else np.nan
            rows.append(r)
        else:
            # 従来の計算方法（販売単価1-5がすべて0の場合）
            for i, suf in enumerate(['-100', '-200', '-300', '-400', '-500'], 1):
                r = row.copy()
                r['商品コード'] = code + suf
                r['通販単価'] = float(str(row['通販単価']).replace(',', '')) * i if row['通販単価'] else np.nan
                rows.append(r)
    
    for _, row in cat2.iterrows():
        code = str(row['商品コード'])
        r = row.copy()
        r['商品コード'] = code + '-50'
        r['通販単価'] = float(str(row['通販単価']).replace(',', '')) if row['通販単価'] else np.nan
        rows.append(r)
    for _, row in other.iterrows():
        r = row.copy()
        r['商品コード'] = str(row['商品コード'])
        r['通販単価'] = float(str(row['通販単価']).replace(',', '')) if row['通販単価'] else np.nan
        rows.append(r)
    sale_list_mod = pd.DataFrame(rows)

    yahoo_item_codes = sale_list_mod['商品コード'].astype(str).unique()
    yahoo_items = []
    # 取得できなかった商品とその理由を記録
    not_found_reasons = {}
    
    # プログレスバー
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_codes = len(yahoo_item_codes)
    
    for idx, code in enumerate(yahoo_item_codes):
        # 進捗更新
        progress = (idx + 1) / total_codes
        progress_bar.progress(progress)
        status_text.text(f"処理中: {idx + 1}/{total_codes} - 商品コード: {code}")
        
        params = {
            "appid": YAHOO_APP_ID,
            "query": code,
            "hits": 30,  # 複数ヒットに対応するため30件まで取得
            "seller_id": "tonya",  # 出店者IDを指定
        }
        # リトライ処理を追加
        max_retries = 3
        retry_count = 0
        success = False
        found = False
        
        while retry_count < max_retries and not success:
            try:
                res = requests.get(YAHOO_API_URL, params=params)
                
                # 429エラー（Too Many Requests）の場合は待機時間を延長
                if res.status_code == 429:
                    wait_time = (retry_count + 1) * 5  # 5秒、10秒、15秒と段階的に延長
                    st.warning(f"API制限に達しました。{wait_time}秒待機します...")
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                
                if res.status_code != 200:
                    not_found_reasons[code] = f"HTTPエラー: {res.status_code}"
                    retry_count += 1
                    continue
                
                res.raise_for_status()
                data = res.json()
                hits = data.get("hits", [])
                if hits:
                    # 通販単価を取得（sale_list_modから該当商品の通販単価を取得）
                    target_price = None
                    matching_row = sale_list_mod[sale_list_mod['商品コード'] == code]
                    if not matching_row.empty:
                        target_price = matching_row.iloc[0]['通販単価']
                    
                    # 通販単価と一致する商品を探す
                    selected_item = None
                    if target_price is not None:
                        for item in hits:
                            item_price = item.get("price", "")
                            if item_price:
                                try:
                                    # 価格を数値に変換して比較
                                    item_price_num = float(str(item_price).replace(',', ''))
                                    target_price_num = float(str(target_price).replace(',', ''))
                                    if abs(item_price_num - target_price_num) < 1:  # 1円以内の差なら一致とみなす
                                        selected_item = item
                                        break
                                except (ValueError, TypeError):
                                    continue
                    
                    # 通販単価と一致する商品がない場合は最初の商品を使用
                    if selected_item is None:
                        selected_item = hits[0]
                        if target_price is not None:
                            st.info(f"商品コード: {code} - 通販単価と一致する商品が見つかりません。最初の商品を選択します。")
                    
                    shipping_name = ""
                    if "shipping" in selected_item and "name" in selected_item["shipping"]:
                        shipping_name = selected_item["shipping"]["name"]
                    
                    in_stock = bool(selected_item.get("inStock", False))
                    yahoo_items.append({
                        "itemCode": code,
                        "itemName": selected_item.get("name", ""),
                        "itemPrice": selected_item.get("price", ""),
                        "pointRate": selected_item.get("point", {}).get("times", ""),
                        "postageFlag": shipping_name,
                        "Stock": "在庫あり" if in_stock else "在庫なし",
                        "要確認": "要確認" if in_stock else "",
                    })
                    found = True
                else:
                    not_found_reasons[code] = "APIで商品が見つかりませんでした（ヒットなし）"
                success = True
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = (retry_count + 1) * 5
                    st.warning(f"API制限に達しました。{wait_time}秒待機します...")
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                else:
                    not_found_reasons[code] = f"HTTPエラー: {e.response.status_code}"
                    retry_count += 1
                    continue
            except requests.exceptions.RequestException as e:
                not_found_reasons[code] = f"リクエストエラー: {str(e)}"
                retry_count += 1
                continue
            except Exception as e:
                not_found_reasons[code] = f"エラー: {str(e)}"
                retry_count += 1
                continue
        
        if not success and retry_count >= max_retries:
            if code not in not_found_reasons:
                not_found_reasons[code] = "最大リトライ回数に達しました"
        
        if not found and code not in not_found_reasons:
            not_found_reasons[code] = "商品が見つかりませんでした"
        
        # API制限を考慮して待機（Yahoo!ショッピングAPI: 1分30リクエスト = 2秒間隔）
        time.sleep(2.1)

    # データフレーム化
    df_yahoo = pd.DataFrame(yahoo_items)
    if df_yahoo.empty:
        st.warning("Yahoo!ショッピングAPIから商品情報が取得できませんでした。")
        df_yahoo = pd.DataFrame(columns=['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', 'Stock', '要確認'])

    # 楽天と同様に在庫データとマージ
    df_yahoo_sales = sale_list_mod[['商品コード', '通販単価', '送料区分名']].rename(columns={'商品コード': 'itemCode'})
    df_yahoo_merged = pd.merge(df_yahoo, df_yahoo_sales, on='itemCode', how='left')

    # 価格の整形・差額計算
    df_yahoo_merged['itemPrice'] = df_yahoo_merged['itemPrice'].replace(',', '', regex=True).astype(float)
    df_yahoo_merged['通販単価'] = df_yahoo_merged['通販単価'].astype(float)
    df_yahoo_merged['差額'] = df_yahoo_merged['itemPrice'] - df_yahoo_merged['通販単価']

    df_yahoo_merged['通販単価'] = df_yahoo_merged['通販単価'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_yahoo_merged['itemPrice'] = df_yahoo_merged['itemPrice'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_yahoo_merged['差額'] = df_yahoo_merged['差額'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')

    # カラム順を楽天と揃える
    cols = ['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', 'Stock', '要確認', '通販単価', '差額', '送料区分名']
    df_yahoo_merged = df_yahoo_merged[cols]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("Yahoo!ショッピングAPI取得完了！")
    
    # 取得できなかった商品の理由をセッション状態に保存
    st.session_state.not_found_reasons_yahoo = not_found_reasons
    
    return df_yahoo_merged


# ---------- 表示ヘルパー ----------
def _filter_needs_review(df):
    """要確認列が立っている行だけ返す"""
    if df is None or df.empty or "要確認" not in df.columns:
        return pd.DataFrame()
    return df[df["要確認"].astype(str).str.strip() == "要確認"].copy()


def _build_mall_not_found(df_items, not_found_reasons):
    """楽天・Yahoo共通: 拡張コードを考慮して取得失敗商品を抽出（従来ロジック）"""
    sale_list = st.session_state.sale_list
    if sale_list is None or df_items is None:
        return pd.DataFrame()

    found_codes = {str(code).strip() for code in df_items["itemCode"].astype(str)}

    cat1_codes = set()
    cat2_codes = set()
    base_code_extensions = {}
    for code in found_codes:
        if "-" in code:
            base_code = code.split("-")[0].strip()
            suffix = code.split("-", 1)[1].strip() if "-" in code else ""
            if base_code not in base_code_extensions:
                base_code_extensions[base_code] = set()
            base_code_extensions[base_code].add(suffix)

    # suffix は '50' / '100' 形式（itemCode を '-' で分割した右側）
    for base_code, extensions in base_code_extensions.items():
        if len(extensions) > 1 or (len(extensions) == 1 and "50" not in extensions):
            cat1_codes.add(base_code)
        elif len(extensions) == 1 and "50" in extensions:
            matching_rows = sale_list[
                sale_list["商品コード"].astype(str).str.strip() == base_code
            ]
            if not matching_rows.empty:
                cat_code = matching_rows.iloc[0]["大分類コード"]
                if cat_code == 2:
                    cat2_codes.add(base_code)
                else:
                    cat1_codes.add(base_code)
            else:
                cat2_codes.add(base_code)

    other_codes = {code for code in found_codes if "-" not in code}

    not_found_list = []
    for _, row in sale_list.iterrows():
        code = str(row["商品コード"]).strip()
        cat_code = row["大分類コード"]
        if cat_code == 1:
            if code not in cat1_codes:
                not_found_list.append(row)
        elif cat_code == 2:
            if code not in cat2_codes:
                not_found_list.append(row)
        else:
            if code not in other_codes:
                not_found_list.append(row)

    if not not_found_list:
        return pd.DataFrame()

    not_found_df = pd.DataFrame(not_found_list)

    def get_reason(row):
        code = str(row["商品コード"]).strip()
        cat_code = row["大分類コード"]
        reasons = []
        if cat_code == 1:
            for suffix in ["-50", "-100", "-200", "-300", "-400", "-500"]:
                ext_code = code + suffix
                if ext_code in not_found_reasons:
                    reasons.append(f"{ext_code}: {not_found_reasons[ext_code]}")
        elif cat_code == 2:
            ext_code = code + "-50"
            if ext_code in not_found_reasons:
                reasons.append(not_found_reasons[ext_code])
        else:
            if code in not_found_reasons:
                reasons.append(not_found_reasons[code])
        return "; ".join(reasons) if reasons else "理由不明"

    not_found_df["取得失敗理由"] = not_found_df.apply(get_reason, axis=1)
    if "商品名" not in not_found_df.columns:
        not_found_df["商品名"] = ""
    return not_found_df[["商品コード", "商品名", "取得失敗理由"]].copy()


def _render_not_found_block(not_found_display_df, site_label):
    if not_found_display_df is None or not_found_display_df.empty:
        return
    st.markdown("---")
    st.subheader("❌ 取得できなかった商品")
    st.warning(f"{len(not_found_display_df)}件の商品が取得できませんでした")
    st.dataframe(not_found_display_df, use_container_width=True, height=400)
    st.download_button(
        label="取得できなかった商品データをダウンロード",
        data=not_found_display_df.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"取得できなかった商品_{site_label}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key=f"dl_not_found_{site_label}",
    )


def render_onlinestore_panel():
    df = st.session_state.df_onlinestore
    if df is None:
        st.info("自社サイトのデータはまだありません。")
        return

    st.success(f"自社サイト: {len(df)}件取得済み")
    needs = _filter_needs_review(df)
    if not needs.empty:
        st.warning(f"要確認（カートに入れられる状態）: {len(needs)}件")
        st.dataframe(needs, use_container_width=True, height=360)
        st.caption("↑ カートボタンがある商品。在庫記号（◎○△×）も併せて確認してください。")

    st.subheader("全件")
    st.dataframe(df, use_container_width=True, height=500)

    if st.session_state.sale_list is not None:
        found_codes = set(df["No"].astype(str))
        not_found_df = st.session_state.sale_list[
            ~st.session_state.sale_list["商品コード"].astype(str).isin(found_codes)
        ].copy()
        if not not_found_df.empty:
            if st.session_state.not_found_reasons_onlinestore:
                not_found_df["取得失敗理由"] = not_found_df["商品コード"].astype(str).map(
                    lambda x: st.session_state.not_found_reasons_onlinestore.get(x, "理由不明")
                )
            else:
                not_found_df["取得失敗理由"] = "理由不明"
            if "商品名" not in not_found_df.columns:
                not_found_df["商品名"] = ""
            _render_not_found_block(
                not_found_df[["商品コード", "商品名", "取得失敗理由"]], "自社サイト"
            )

    st.download_button(
        label="自社サイトデータをダウンロード",
        data=df.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"自社サイトデータ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="dl_onlinestore",
    )


def render_rakuten_panel():
    df = st.session_state.df_rakuten
    if df is None:
        st.info("楽天市場のデータはまだありません。")
        return

    st.success(f"楽天市場: {len(df)}件取得済み")
    needs = _filter_needs_review(df)
    if not needs.empty:
        st.warning(f"要確認（在庫あり）: {len(needs)}件")
        st.dataframe(needs, use_container_width=True, height=360)

    st.subheader("全件")
    st.dataframe(df, use_container_width=True, height=500)
    _render_not_found_block(
        _build_mall_not_found(df, st.session_state.not_found_reasons_rakuten),
        "楽天市場",
    )
    st.download_button(
        label="楽天市場データをダウンロード",
        data=df.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"楽天市場データ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="dl_rakuten",
    )


def render_yahoo_panel():
    df = st.session_state.df_yahoo
    if df is None:
        st.info("Yahoo!ショッピングのデータはまだありません。")
        return

    st.success(f"Yahoo!ショッピング: {len(df)}件取得済み")
    needs = _filter_needs_review(df)
    if not needs.empty:
        st.warning(f"要確認（在庫あり）: {len(needs)}件")
        st.dataframe(needs, use_container_width=True, height=360)

    st.subheader("全件")
    st.dataframe(df, use_container_width=True, height=500)
    _render_not_found_block(
        _build_mall_not_found(df, st.session_state.not_found_reasons_yahoo),
        "Yahoo!ショッピング",
    )
    st.download_button(
        label="Yahoo!ショッピングデータをダウンロード",
        data=df.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"Yahoo!ショッピングデータ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="dl_yahoo",
    )


def fetch_all_sites(sale_list):
    """自社・楽天・Yahoo を順に取得（各サイトの既存ロジックを利用）"""
    st.info("全サイトの一括取得を開始します（自社 → 楽天 → Yahoo の順）")
    overall = st.progress(0)
    overall_text = st.empty()

    overall_text.text("1/3 自社サイトを取得中…")
    overall.progress(0.05)
    st.session_state.df_onlinestore = scrape_own_site(sale_list)
    overall.progress(0.33)

    overall_text.text("2/3 楽天市場APIを取得中…")
    st.session_state.df_rakuten = get_rakuten_data(sale_list)
    overall.progress(0.66)

    overall_text.text("3/3 Yahoo!ショッピングAPIを取得中…")
    st.session_state.df_yahoo = get_yahoo_data(sale_list)
    overall.progress(1.0)
    overall_text.text("全サイトの取得が完了しました")


# サイドバー
def render_sidebar():
    """サイドバーの表示（全サイト一括取得）"""
    if st.session_state.sale_list is None:
        return

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔧 データ取得")
    st.sidebar.markdown(
        "1回の操作で **自社サイト・楽天・Yahoo** を順に取得します。\n\n"
        "各サイトの取得方法は従来どおりです。\n\n"
        "⚠️ 楽天・Yahoo は API 制限のため時間がかかります。"
    )

    if st.sidebar.button("全サイト一括取得", type="primary", use_container_width=True):
        st.session_state.df_onlinestore = None
        st.session_state.df_rakuten = None
        st.session_state.df_yahoo = None
        st.session_state.not_found_reasons_onlinestore = {}
        st.session_state.not_found_reasons_rakuten = {}
        st.session_state.not_found_reasons_yahoo = {}

        fetch_all_sites(st.session_state.sale_list)
        st.rerun()


# メイン処理
def main():
    st.subheader("📁 CSVファイルアップロード")

    uploaded_file = st.file_uploader(
        "CSVファイルを選択してください",
        type=["csv"],
        help="商品データが含まれたCSVファイルをアップロードしてください",
    )

    if uploaded_file is not None:
        sale_list = load_csv_data_from_upload(uploaded_file)
        if sale_list is not None:
            st.success(f"読み込み完了: {len(sale_list)}件の商品データ")
            st.info("👈 サイドバーの「全サイト一括取得」を押してください")
    else:
        st.info("👆 CSVファイルをアップロードして、全サイトの商品データを取得しましょう")

    render_sidebar()

    has_any = (
        st.session_state.df_onlinestore is not None
        or st.session_state.df_rakuten is not None
        or st.session_state.df_yahoo is not None
    )

    if has_any:
        st.markdown("---")
        st.subheader("📊 取得結果")

        summary_cols = st.columns(3)
        own_n = (
            len(_filter_needs_review(st.session_state.df_onlinestore))
            if st.session_state.df_onlinestore is not None
            else 0
        )
        rak_n = (
            len(_filter_needs_review(st.session_state.df_rakuten))
            if st.session_state.df_rakuten is not None
            else 0
        )
        yah_n = (
            len(_filter_needs_review(st.session_state.df_yahoo))
            if st.session_state.df_yahoo is not None
            else 0
        )
        summary_cols[0].metric("自社・要確認", f"{own_n}件")
        summary_cols[1].metric("楽天・要確認", f"{rak_n}件")
        summary_cols[2].metric("Yahoo・要確認", f"{yah_n}件")
        st.caption(
            "要確認 = カートに入れられる／在庫ありの状態。"
            "売切れ（カートなし・在庫なし）は対象外です。"
        )

        tab_own, tab_rakuten, tab_yahoo = st.tabs(
            ["🏪 自社サイト", "🛒 楽天市場", "🛍️ Yahoo!ショッピング"]
        )
        with tab_own:
            render_onlinestore_panel()
        with tab_rakuten:
            render_rakuten_panel()
        with tab_yahoo:
            render_yahoo_panel()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 取得結果")
    if st.session_state.df_onlinestore is not None:
        st.sidebar.success(f"自社サイト: {len(st.session_state.df_onlinestore)}件")
    if st.session_state.df_rakuten is not None:
        st.sidebar.success(f"楽天市場: {len(st.session_state.df_rakuten)}件")
    if st.session_state.df_yahoo is not None:
        st.sidebar.success(f"Yahoo!: {len(st.session_state.df_yahoo)}件")

    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666;'>
            <small>商品データ取得ツール v1.1 | 株式会社フレッシュロースター珈琲問屋</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
