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
if 'selected_data_source' not in st.session_state:
    st.session_state.selected_data_source = "自社サイトスクレイピング"

# タイトル
st.title("📊 商品データ取得ツール")
st.markdown("---")

# CSVファイル読み込み機能
def load_csv_data_from_upload(uploaded_file):
    """アップロードされたCSVファイルを読み込む関数"""
    try:
        # ファイルを読み込み
        sale_list = pd.read_csv(uploaded_file)
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
    
    # プログレスバー
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_items = len(sale_list['商品コード'])
    
    for idx, code in enumerate(sale_list['商品コード']):
        try:
            # 進捗更新
            progress = (idx + 1) / total_items
            progress_bar.progress(progress)
            status_text.text(f"処理中: {idx + 1}/{total_items} - 商品コード: {code}")
            
            url = f'https://www.tonya.co.jp/shop/g/g{code}'
            res = requests.get(url)
            soup = BeautifulSoup(res.text, 'html.parser')

            # 各項目の初期化
            item_dict = {
                'No': None,
                'Name': None,
                'Price': None,
                'Point': None,
                'Stock': None,
                'Icon': []
            }

            # 商品詳細ブロック取得
            detail_div = soup.find('div', class_='goodsproductdetail_')
            if detail_div is None:
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

            # 在庫
            stock_tr = soup.find('tr', class_='id_stock_msg_')
            if stock_tr:
                stock_td = stock_tr.find('td', class_='id_txt')
                if stock_td:
                    item_dict['Stock'] = stock_td.text

            # 辞書をリストに追加
            onlinestore_data.append(item_dict)

        except Exception as e:
            # エラー時はスキップ
            continue

    # データフレーム化
    df_onlinestore = pd.DataFrame(onlinestore_data)
    
    # salelistの「商品コード」「通販単価」「送料区分名」をdf_onlinestoreにNoで紐づけて追加し、差額列も追加
    salelist_renamed = sale_list.rename(columns={'商品コード': 'No', '通販単価': '通販単価', '送料区分名': '送料区分名'})
    df_onlinestore['No'] = df_onlinestore['No'].astype(str)
    salelist_renamed['No'] = salelist_renamed['No'].astype(str)

    # 通販単価と送料区分名を追加
    df_onlinestore = pd.merge(df_onlinestore, salelist_renamed[['No', '通販単価', '送料区分名']], on='No', how='left')

    # 通販単価もカンマ区切りの文字列に変換
    df_onlinestore['通販単価'] = df_onlinestore['通販単価'].apply(
        lambda x: f"{int(str(x).replace(',', '')):,}" if pd.notnull(x) and str(x).replace(',', '').isdigit() else x
    )

    # 差額列を追加（Price - 通販単価）
    def calc_diff(row):
        try:
            price = int(str(row['Price']).replace(',', ''))
            sale = int(str(row['通販単価']).replace(',', ''))
            return f"{price - sale:,}"
        except:
            return None

    df_onlinestore['差額'] = df_onlinestore.apply(calc_diff, axis=1)
    
    # 列の順序を指定（通販単価、差額、送料区分名の順に）
    column_order = ['No', 'Name', 'Price', 'Point', 'Stock', 'Icon', '通販単価', '差額', '送料区分名']
    df_onlinestore = df_onlinestore[column_order]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("スクレイピング完了！")
    
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
        try:
            res = requests.get(REQUEST_URL, params=params)
            result = res.json()
        except:
            # API制限を考慮して待機（楽天市場API: 1分30リクエスト = 2秒間隔）
            time.sleep(2.1)
            continue
        for item in result.get('Items', []):
            d = item['Item']
            url = d.get('itemUrl', '')
            url = url.replace("https://item.rakuten.co.jp/tonya/", "").replace("/?rafcid=wsc_i_is_1027604414937000350", "")
            if url == code:
                tmp = {
                    'itemCode': url,
                    'itemName': d.get('itemName', ''),
                    'itemPrice': d.get('itemPrice', ''),
                    'pointRate': d.get('pointRate', ''),
                    'postageFlag': "送料込" if d.get('postageFlag') == 0 else "送料別" if d.get('postageFlag') == 1 else ""
                }
                item_list.append(tmp)
        # API制限を考慮して待機（楽天市場API: 1分30リクエスト = 2秒間隔）
        time.sleep(2.1)

    df_rakuten = pd.DataFrame(item_list)
    if df_rakuten.empty:
        df_rakuten = pd.DataFrame(columns=['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag'])

    df_sales = sale_list_mod[['商品コード', '通販単価', '送料区分名']].rename(columns={'商品コード': 'itemCode'})
    df_merged = pd.merge(df_rakuten, df_sales, on='itemCode', how='left')

    df_merged['itemPrice'] = df_merged['itemPrice'].replace(',', '', regex=True).astype(float)
    df_merged['通販単価'] = df_merged['通販単価'].astype(float)
    df_merged['差額'] = df_merged['itemPrice'] - df_merged['通販単価']

    df_merged['通販単価'] = df_merged['通販単価'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_merged['itemPrice'] = df_merged['itemPrice'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')
    df_merged['差額'] = df_merged['差額'].apply(lambda x: '{:,.0f}'.format(x) if not np.isnan(x) else '')

    cols = ['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', '通販単価', '差額', '送料区分名']
    df_merged = df_merged[cols]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("楽天市場API取得完了！")
    
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
                    
                    yahoo_items.append({
                        "itemCode": code,
                        "itemName": selected_item.get("name", ""),
                        "itemPrice": selected_item.get("price", ""),
                        "pointRate": selected_item.get("point", {}).get("times", ""),
                        "postageFlag": shipping_name,
                    })
                else:
                    st.warning(f"商品コード: {code} でヒットなし")
                success = True
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = (retry_count + 1) * 5
                    st.warning(f"API制限に達しました。{wait_time}秒待機します...")
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                else:
                    st.error(f"Yahoo!商品取得エラー: {code} - {e}")
                    break
            except Exception as e:
                st.error(f"Yahoo!商品取得エラー: {code} - {e}")
                break
        
        if not success and retry_count >= max_retries:
            st.error(f"商品コード: {code} の取得に失敗しました（最大リトライ回数に達しました）")
        
        # API制限を考慮して待機（Yahoo!ショッピングAPI: 1分30リクエスト = 2秒間隔）
        time.sleep(2.1)

    # データフレーム化
    df_yahoo = pd.DataFrame(yahoo_items)
    if df_yahoo.empty:
        st.warning("Yahoo!ショッピングAPIから商品情報が取得できませんでした。")
        df_yahoo = pd.DataFrame(columns=['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag'])

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
    cols = ['itemCode', 'itemName', 'itemPrice', 'pointRate', 'postageFlag', '通販単価', '差額', '送料区分名']
    df_yahoo_merged = df_yahoo_merged[cols]
    
    # プログレスバーを完了
    progress_bar.progress(1.0)
    status_text.text("Yahoo!ショッピングAPI取得完了！")
    
    return df_yahoo_merged

# サイドバー
def render_sidebar():
    """サイドバーの表示"""
    # サイドバーでデータ取得方法の選択
    if st.session_state.sale_list is not None:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔧 データ取得方法")
        
        data_source = st.sidebar.radio(
            "取得するデータを選択：",
            ["自社サイトスクレイピング", "楽天市場API取得", "Yahoo!ショッピングAPI取得"],
            index=0 if st.session_state.selected_data_source == "自社サイトスクレイピング" else 
                 1 if st.session_state.selected_data_source == "楽天市場API取得" else 2,
            key="data_source_radio"
        )
        
        # セッション状態に選択を保存
        st.session_state.selected_data_source = data_source
        
        st.sidebar.markdown("---")
        
        # 選択に応じたデータ取得ボタン
        if data_source == "自社サイトスクレイピング":
            st.sidebar.subheader("🏪 自社サイトスクレイピング")
            st.sidebar.markdown("自社サイトから商品情報を取得します。")
            
            if st.sidebar.button("スクレイピング開始", type="primary", use_container_width=True):
                df_result = scrape_own_site(st.session_state.sale_list)
                st.session_state.df_onlinestore = df_result
                
                # メインエリアに結果を表示するためにリダイレクト
                st.rerun()
        
        elif data_source == "楽天市場API取得":
            st.sidebar.subheader("🛒 楽天市場API取得")
            st.sidebar.markdown("楽天市場APIから商品情報を取得します。")
            
            if st.sidebar.button("API取得開始", type="primary", use_container_width=True):
                df_result = get_rakuten_data(st.session_state.sale_list)
                st.session_state.df_rakuten = df_result
                
                # メインエリアに結果を表示するためにリダイレクト
                st.rerun()
        
        elif data_source == "Yahoo!ショッピングAPI取得":
            st.sidebar.subheader("🛍️ Yahoo!ショッピングAPI取得")
            st.sidebar.markdown("Yahoo!ショッピングAPIから商品情報を取得します。")
            st.sidebar.info("⚠️ **API制限**: 1分30リクエスト（約2秒間隔）\n\n処理に時間がかかります。")
            
            if st.sidebar.button("Yahoo!API取得開始", type="primary", use_container_width=True):
                df_result = get_yahoo_data(st.session_state.sale_list)
                st.session_state.df_yahoo = df_result
                
                # メインエリアに結果を表示するためにリダイレクト
                st.rerun()

# メイン処理
def main():
    # CSVファイルアップロードセクション
    st.subheader("📁 CSVファイルアップロード")
    
    uploaded_file = st.file_uploader(
        "CSVファイルを選択してください",
        type=['csv'],
        help="商品データが含まれたCSVファイルをアップロードしてください"
    )
    st.text('汎用明細表：M04/シリーズ商品マスタ')
    
    if uploaded_file is not None:
        # CSVファイルを読み込み
        sale_list = load_csv_data_from_upload(uploaded_file)
        
        if sale_list is not None:
            st.success(f"読み込み完了: {len(sale_list)}件の商品データ")
            st.info("👈 サイドバーからデータ取得方法を選択してください")
    
    else:
        st.info("👆 CSVファイルをアップロードして、自社サイトまたは楽天市場のデータを取得しましょう！")
    
    # サイドバーを表示（CSV読み込み後に実行）
    render_sidebar()

    # 結果表示（選択されたデータソースのみ表示）
    if st.session_state.selected_data_source == "自社サイトスクレイピング" and st.session_state.df_onlinestore is not None:
        st.markdown("---")
        st.subheader("📊 自社サイト取得結果")
        st.success("スクレイピングが完了しました！")
        
        # 高さを指定してデータフレームを表示
        st.dataframe(
            st.session_state.df_onlinestore,
            use_container_width=True,
            height=600
        )
        
        # 取得できなかった商品リストを表示
        if st.session_state.sale_list is not None:
            # 取得できた商品コードのリスト
            found_codes = set(st.session_state.df_onlinestore['No'].astype(str))
            # 元のsale_listから取得できなかった商品を抽出
            not_found_df = st.session_state.sale_list[
                ~st.session_state.sale_list['商品コード'].astype(str).isin(found_codes)
            ]
            
            if not not_found_df.empty:
                st.markdown("---")
                st.subheader("❌ 取得できなかった商品")
                st.warning(f"{len(not_found_df)}件の商品が取得できませんでした")
                
                # 取得できなかった商品を表示
                st.dataframe(
                    not_found_df,
                    use_container_width=True,
                    height=400
                )
                
                # 取得できなかった商品のダウンロードボタン
                csv_data_not_found = not_found_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="取得できなかった商品データをダウンロード",
                    data=csv_data_not_found,
                    file_name=f"取得できなかった商品_自社サイト_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
        
        # ダウンロードボタン
        csv_data = st.session_state.df_onlinestore.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="自社サイトデータをダウンロード",
            data=csv_data,
            file_name=f"自社サイトデータ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    
    elif st.session_state.selected_data_source == "楽天市場API取得" and st.session_state.df_rakuten is not None:
        st.markdown("---")
        st.subheader("📊 楽天市場取得結果")
        st.success("楽天市場API取得が完了しました！")
        
        # 高さを指定してデータフレームを表示
        st.dataframe(
            st.session_state.df_rakuten,
            use_container_width=True,
            height=800
        )
        
        # 取得できなかった商品リストを表示
        if st.session_state.sale_list is not None:
            # 取得できた商品コードのリスト（拡張コードから元のコードを抽出）
            found_original_codes = set()
            for code in st.session_state.df_rakuten['itemCode'].astype(str):
                # 拡張コード（-50, -100, -200等）から元のコードを抽出
                if '-' in code:
                    original_code = code.split('-')[0]
                    found_original_codes.add(original_code)
                else:
                    found_original_codes.add(code)
            
            # 元のsale_listから取得できなかった商品を抽出
            # 大分類コード1,2は変換前の商品コードなので取得対象外
            target_sale_list = st.session_state.sale_list[
                ~st.session_state.sale_list['大分類コード'].isin([1, 2])
            ]
            
            # 取得できなかった商品を抽出（取得できた元のコードを除外）
            not_found_df = target_sale_list[
                ~target_sale_list['商品コード'].astype(str).isin(found_original_codes)
            ]
            
            if not not_found_df.empty:
                st.markdown("---")
                st.subheader("❌ 取得できなかった商品")
                st.warning(f"{len(not_found_df)}件の商品が取得できませんでした")
                
                # 取得できなかった商品を表示
                st.dataframe(
                    not_found_df,
                    use_container_width=True,
                    height=400
                )
                
                # 取得できなかった商品のダウンロードボタン
                csv_data_not_found = not_found_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="取得できなかった商品データをダウンロード",
                    data=csv_data_not_found,
                    file_name=f"取得できなかった商品_楽天市場_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
        
        # ダウンロードボタン
        csv_data = st.session_state.df_rakuten.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="楽天市場データをダウンロード",
            data=csv_data,
            file_name=f"楽天市場データ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    
    elif st.session_state.selected_data_source == "Yahoo!ショッピングAPI取得" and st.session_state.df_yahoo is not None:
        st.markdown("---")
        st.subheader("📊 Yahoo!ショッピング取得結果")
        st.success("Yahoo!ショッピングAPI取得が完了しました！")
        
        # 高さを指定してデータフレームを表示
        st.dataframe(
            st.session_state.df_yahoo,
            use_container_width=True,
            height=800
        )
        
        # 取得できなかった商品リストを表示
        if st.session_state.sale_list is not None:
            # 取得できた商品コードのリスト（拡張コードから元のコードを抽出）
            found_original_codes = set()
            for code in st.session_state.df_yahoo['itemCode'].astype(str):
                # 拡張コード（-50, -100, -200等）から元のコードを抽出
                if '-' in code:
                    original_code = code.split('-')[0]
                    found_original_codes.add(original_code)
                else:
                    found_original_codes.add(code)
            
            # 元のsale_listから取得できなかった商品を抽出
            # 大分類コード1,2は変換前の商品コードなので取得対象外
            target_sale_list = st.session_state.sale_list[
                ~st.session_state.sale_list['大分類コード'].isin([1, 2])
            ]
            
            # 取得できなかった商品を抽出（取得できた元のコードを除外）
            not_found_df = target_sale_list[
                ~target_sale_list['商品コード'].astype(str).isin(found_original_codes)
            ]
            
            if not not_found_df.empty:
                st.markdown("---")
                st.subheader("❌ 取得できなかった商品")
                st.warning(f"{len(not_found_df)}件の商品が取得できませんでした")
                
                # 取得できなかった商品を表示
                st.dataframe(
                    not_found_df,
                    use_container_width=True,
                    height=400
                )
                
                # 取得できなかった商品のダウンロードボタン
                csv_data_not_found = not_found_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="取得できなかった商品データをダウンロード",
                    data=csv_data_not_found,
                    file_name=f"取得できなかった商品_Yahoo!ショッピング_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
        
        # ダウンロードボタン
        csv_data = st.session_state.df_yahoo.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="Yahoo!ショッピングデータをダウンロード",
            data=csv_data,
            file_name=f"Yahoo!ショッピングデータ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

    # サイドバーに結果表示
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 取得結果")
    
    if st.session_state.df_onlinestore is not None:
        st.sidebar.success(f"自社サイトデータ: {len(st.session_state.df_onlinestore)}件")
    
    if st.session_state.df_rakuten is not None:
        st.sidebar.success(f"楽天市場データ: {len(st.session_state.df_rakuten)}件")
    
    if st.session_state.df_yahoo is not None:
        st.sidebar.success(f"Yahoo!ショッピングデータ: {len(st.session_state.df_yahoo)}件")

    # フッター
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666;'>
            <small>商品データ取得ツール v1.0 | 株式会社フレッシュロースター珈琲問屋</small>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()

