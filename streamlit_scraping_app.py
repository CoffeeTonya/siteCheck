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

try:
    import tomllib  # Python 3.11 以降の標準ライブラリ
except ModuleNotFoundError:
    tomllib = None

# ページ設定
st.set_page_config(
    page_title="掲載内容チェック",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)


def load_local_secrets():
    """このスクリプトと同じ場所にある .streamlit/secrets.toml を読む

    st.secrets が探すのは起動時のカレントディレクトリ配下のため、
    別の場所から streamlit run した場合でも設定を拾えるようにする。
    """
    if tomllib is None:
        return {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.streamlit', 'secrets.toml')
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except Exception:
        return {}


LOCAL_SECRETS = load_local_secrets()


def get_setting(name, default=''):
    """設定値を secrets.toml → 環境変数 の順に読む"""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        # secrets.toml を置いていない環境では st.secrets の参照自体が例外になる
        pass
    if name in LOCAL_SECRETS:
        return str(LOCAL_SECRETS[name])
    return os.environ.get(name, default)


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
    st.session_state.selected_data_source = 'onlinestore'
if 'not_found_reasons_onlinestore' not in st.session_state:
    st.session_state.not_found_reasons_onlinestore = {}
if 'not_found_reasons_rakuten' not in st.session_state:
    st.session_state.not_found_reasons_rakuten = {}
if 'not_found_reasons_yahoo' not in st.session_state:
    st.session_state.not_found_reasons_yahoo = {}
# 楽天ウェブサービスは 2026-05-14 の刷新で applicationId と accessKey の両方が必須になった
if 'rakuten_app_id' not in st.session_state:
    st.session_state.rakuten_app_id = get_setting('RAKUTEN_APP_ID')
if 'rakuten_access_key' not in st.session_state:
    st.session_state.rakuten_access_key = get_setting('RAKUTEN_ACCESS_KEY')

# タイトル
st.title("🔍 掲載内容チェック")
st.caption("商品リストの値段と、サイト・モールに掲載されている内容を突き合わせます")


def load_csv_data_from_upload(uploaded_file):
    """アップロードされた商品リストのCSVを読み込む"""
    try:
        sale_list = pd.read_csv(uploaded_file)
    except Exception as e:
        st.sidebar.error(f"CSVを読み込めませんでした: {e}")
        return None

    missing = [col for col in ['商品コード', '通販単価'] if col not in sale_list.columns]
    if missing:
        st.sidebar.error(f"リストに必要な列がありません: {'、'.join(missing)}")
        return None
    if '大分類コード' not in sale_list.columns:
        st.sidebar.warning("「大分類コード」列がないため、楽天市場とYahoo!ショッピングは取得できません。")

    st.session_state.sale_list = sale_list
    return sale_list


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
            # 進捗更新
            progress = (idx + 1) / total_items
            progress_bar.progress(progress)
            status_text.text(f"処理中: {idx + 1}/{total_items} - 商品コード: {code}")
            
            url = f'https://www.tonya.co.jp/shop/g/g{code}'
            res = requests.get(url, timeout=30)
            
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

            # 在庫
            stock_tr = soup.find('tr', class_='id_stock_msg_')
            if stock_tr:
                stock_td = stock_tr.find('td', class_='id_txt')
                if stock_td:
                    item_dict['Stock'] = stock_td.text

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
    
    # 取得できなかった商品の理由をセッション状態に保存
    st.session_state.not_found_reasons_onlinestore = not_found_reasons
    
    return df_onlinestore

# 楽天市場API取得関数
def get_rakuten_data(sale_list):
    """楽天市場APIから商品情報を取得する関数"""
    # 旧ドメイン app.rakuten.co.jp は 2026-05-14 に停止済み（アクセスすると 503 が返る）
    REQUEST_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
    # 楽天アプリ登録時の「許可されたWebサイト」と一致しないと 403 で拒否される
    ALLOWED_SITE = get_setting('RAKUTEN_ALLOWED_SITE', 'https://tonya.co.jp').rstrip('/')
    # 画面で入力された値を優先し、無ければ secrets.toml や環境変数から読む
    APP_ID = str(st.session_state.get('rakuten_app_id', '')).strip() or get_setting('RAKUTEN_APP_ID')
    ACCESS_KEY = str(st.session_state.get('rakuten_access_key', '')).strip() or get_setting('RAKUTEN_ACCESS_KEY')

    if not APP_ID or not ACCESS_KEY:
        st.error(
            "楽天のアプリID（applicationId）とアクセスキー（accessKey）が未設定です。"
            "楽天ウェブサービスのダッシュボードでアプリを再登録し、サイドバーに入力してください。"
        )
        return None

    st.info("楽天市場APIからのデータ取得を開始します...")

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
    # 認証エラーやメンテナンスが続くときに全件を待たずに打ち切るためのカウンタ
    consecutive_http_errors = 0
    
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
            headers = {
                "accessKey": ACCESS_KEY,
                "Origin": ALLOWED_SITE,
                "Referer": ALLOWED_SITE + "/",
            }
            res = requests.get(REQUEST_URL, params=params, headers=headers, timeout=30)
            if res.status_code != 200:
                detail = res.text[:200].replace('\n', ' ')
                not_found_reasons[code] = f"HTTPエラー: {res.status_code} {detail}"
                consecutive_http_errors += 1
                if consecutive_http_errors >= 5:
                    st.error(
                        f"楽天APIが連続で失敗しました（HTTP {res.status_code}）。"
                        "アプリID・アクセスキー、または楽天側の稼働状況を確認してください。処理を中断します。"
                    )
                    break
                time.sleep(2.1)
                continue
            consecutive_http_errors = 0
            result = res.json()
        except requests.exceptions.RequestException as e:
            not_found_reasons[code] = f"リクエストエラー: {str(e)}"
            time.sleep(2.1)
            continue
        except Exception as e:
            not_found_reasons[code] = f"エラー: {str(e)}"
            time.sleep(2.1)
            continue
        
        # 新旧バージョンでキー名（Items/items・Item/item）が異なる場合に備えて両方を受ける
        raw_items = result.get('Items', result.get('items', []))
        for item in raw_items:
            d = item.get('Item', item.get('item', item)) if isinstance(item, dict) else {}
            url = d.get('itemUrl', '')
            # itemUrl 末尾のアフィリエイトパラメータはアプリごとに変わるため、店舗URL直後の商品コードだけを取り出す
            m = re.search(r'item\.rakuten\.co\.jp/tonya/([^/?#]+)', url)
            item_code = m.group(1) if m else ''
            if item_code == code:
                tmp = {
                    'itemCode': item_code,
                    'itemName': d.get('itemName', ''),
                    'itemPrice': d.get('itemPrice', ''),
                    'pointRate': d.get('pointRate', ''),
                    'postageFlag': "送料込" if d.get('postageFlag') == 0 else "送料別" if d.get('postageFlag') == 1 else ""
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
                    
                    yahoo_items.append({
                        "itemCode": code,
                        "itemName": selected_item.get("name", ""),
                        "itemPrice": selected_item.get("price", ""),
                        "pointRate": selected_item.get("point", {}).get("times", ""),
                        "postageFlag": shipping_name,
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
    
    # 取得できなかった商品の理由をセッション状態に保存
    st.session_state.not_found_reasons_yahoo = not_found_reasons
    
    return df_yahoo_merged

# ---------------------------------------------------------------------------
# 取得先ごとの設定と、リストとの突き合わせに使う共通処理
# ---------------------------------------------------------------------------

SOURCES = {
    'onlinestore': {
        'label': 'オンラインストア',
        'icon': '🏪',
        'df_key': 'df_onlinestore',
        'reason_key': 'not_found_reasons_onlinestore',
        'code_col': 'No',
        'name_col': 'Name',
        'price_col': 'Price',
        'extended': False,
        'button': '自社サイトを確認する',
        'note': '商品ページを1件ずつ開いて、価格・ポイント・在庫を読み取ります。',
    },
    'rakuten': {
        'label': '楽天市場',
        'icon': '🛒',
        'df_key': 'df_rakuten',
        'reason_key': 'not_found_reasons_rakuten',
        'code_col': 'itemCode',
        'name_col': 'itemName',
        'price_col': 'itemPrice',
        'extended': True,
        'button': '楽天市場を確認する',
        'note': '楽天のAPIで検索します。1件あたり約2秒かかります。',
    },
    'yahoo': {
        'label': 'Yahoo!ショッピング',
        'icon': '🛍️',
        'df_key': 'df_yahoo',
        'reason_key': 'not_found_reasons_yahoo',
        'code_col': 'itemCode',
        'name_col': 'itemName',
        'price_col': 'itemPrice',
        'extended': True,
        'button': 'Yahoo!ショッピングを確認する',
        'note': 'Yahoo!のAPIで検索します。1件あたり約2秒かかります。',
    },
}

# 画面に出すときの列名（データそのものの列名は変えない）
COLUMN_LABELS = {
    'No': '商品コード',
    'itemCode': '商品コード',
    'Name': '商品名',
    'itemName': '商品名',
    'Price': '掲載価格',
    'itemPrice': '掲載価格',
    '通販単価': 'リスト価格',
    '差額': '差額',
    'Point': 'ポイント',
    'pointRate': 'ポイント倍率',
    'Stock': '在庫',
    'Icon': 'アイコン',
    'postageFlag': '送料',
    '送料区分名': '送料区分',
}


def to_number(value):
    """カンマ付きの文字列などを数値にする（数値にできなければ None）"""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    text = str(value).replace(',', '').strip()
    if text == '' or text.lower() == 'nan':
        return None
    try:
        return float(text)
    except ValueError:
        return None


def add_judgement(df, price_col):
    """掲載価格とリストの通販単価を突き合わせ、判定列を先頭に付ける"""
    if df is None or df.empty:
        return df

    def judge(row):
        listed = to_number(row.get('通販単価'))
        shown = to_number(row.get(price_col))
        if shown is None:
            return '価格を取得できず'
        if listed is None:
            return 'リストに価格なし'
        return '一致' if abs(shown - listed) < 1 else '要確認'

    judged = df.copy()
    judged.insert(0, '判定', judged.apply(judge, axis=1))
    return judged


def collect_reasons(code, reasons, extended):
    """取得できなかった理由を、枝番付きのコードも含めて集める"""
    if code in reasons:
        return reasons[code]
    if extended:
        details = [
            f"{code}{suffix}: {reasons[code + suffix]}"
            for suffix in ['-50', '-100', '-200', '-300', '-400', '-500']
            if code + suffix in reasons
        ]
        if details:
            return " / ".join(details)
    return '理由不明'


def build_not_found_df(source_key):
    """リストにあって掲載側で見つからなかった商品を、理由付きで抜き出す"""
    conf = SOURCES[source_key]
    sale_list = st.session_state.sale_list
    df = st.session_state.get(conf['df_key'])
    empty = pd.DataFrame(columns=['商品コード', '商品名', '取得失敗理由'])
    if sale_list is None or df is None:
        return empty

    reasons = st.session_state.get(conf['reason_key'], {})
    found = {str(code).strip() for code in df[conf['code_col']].astype(str)} if not df.empty else set()
    # 枝番（-100 など）を付けて取得する掲載先では、枝番を落とした元コードでも突き合わせる
    found_base = {code.split('-')[0] for code in found}

    rows = []
    for _, row in sale_list.iterrows():
        code = str(row['商品コード']).strip()
        if code in found or (conf['extended'] and code in found_base):
            continue
        rows.append({
            '商品コード': code,
            '商品名': row.get('商品名', ''),
            '取得失敗理由': collect_reasons(code, reasons, conf['extended']),
        })
    return pd.DataFrame(rows) if rows else empty


def clear_all_results():
    """商品リストを入れ替えたときに、前のリストで取った結果を捨てる"""
    for conf in SOURCES.values():
        st.session_state[conf['df_key']] = None
        st.session_state[conf['reason_key']] = {}


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------

def render_rakuten_credentials():
    """楽天の認証情報（secrets.toml から読めていれば畳んでおく）

    入力欄に key を付けると、楽天以外を選んでいる間に Streamlit が値を捨ててしまうため、
    値の受け渡しは value と戻り値で行う。
    """
    app_id = str(st.session_state.get('rakuten_app_id', '')).strip()
    access_key = str(st.session_state.get('rakuten_access_key', '')).strip()

    if app_id and access_key:
        with st.sidebar.expander("✅ 認証情報は設定済み"):
            app_id = st.text_input("アプリID（applicationId）", value=app_id)
            access_key = st.text_input("アクセスキー（accessKey）", value=access_key, type="password")
            st.caption("恒久的に変えるときは .streamlit/secrets.toml を書き換えてください。")
    else:
        st.sidebar.warning("楽天の認証情報が未設定です")
        app_id = st.sidebar.text_input("アプリID（applicationId）", value=app_id)
        access_key = st.sidebar.text_input("アクセスキー（accessKey）", value=access_key, type="password")
        st.sidebar.caption(".streamlit/secrets.toml に書いておくと、次回から自動で読み込まれます。")

    st.session_state.rakuten_app_id = app_id
    st.session_state.rakuten_access_key = access_key


def render_sidebar():
    """サイドバー：リストの読み込みから取得の実行まで"""
    st.sidebar.subheader("① 商品リストを読み込む")
    uploaded_file = st.sidebar.file_uploader(
        "CSVファイル",
        type=['csv'],
        help="商品コード・商品名・通販単価・大分類コードが入ったリスト",
    )
    if uploaded_file is not None and st.session_state.get('uploaded_file_name') != uploaded_file.name:
        if load_csv_data_from_upload(uploaded_file) is not None:
            # リストを入れ替えたら、前のリストで取った結果は残さない
            st.session_state.uploaded_file_name = uploaded_file.name
            clear_all_results()
            st.rerun()

    sale_list = st.session_state.sale_list
    if sale_list is None:
        return

    st.sidebar.success(f"リスト {len(sale_list):,} 件")

    st.sidebar.markdown("---")
    st.sidebar.subheader("② 突き合わせる掲載先")
    source_key = st.sidebar.radio(
        "掲載先",
        list(SOURCES.keys()),
        format_func=lambda key: f"{SOURCES[key]['icon']} {SOURCES[key]['label']}",
        label_visibility='collapsed',
    )
    conf = SOURCES[source_key]
    st.sidebar.caption(conf['note'])

    if source_key == 'rakuten':
        render_rakuten_credentials()

    st.sidebar.markdown("---")
    st.sidebar.subheader("③ 実行")
    if st.sidebar.button(conf['button'], type="primary", use_container_width=True):
        runners = {
            'onlinestore': scrape_own_site,
            'rakuten': get_rakuten_data,
            'yahoo': get_yahoo_data,
        }
        df_result = runners[source_key](sale_list)
        # 認証情報が未設定のときは None が返るので、エラー表示を消さないよう再実行しない
        if df_result is not None:
            st.session_state[conf['df_key']] = df_result
            st.session_state.selected_data_source = source_key
            st.rerun()

    if any(st.session_state.get(c['df_key']) is not None for c in SOURCES.values()):
        if st.sidebar.button("取得結果を消す", use_container_width=True):
            clear_all_results()
            st.rerun()


# ---------------------------------------------------------------------------
# メイン画面
# ---------------------------------------------------------------------------
def build_column_config(df):
    """表の見出しを日本語にする（データそのものの列名は変えない）"""
    config = {}
    for col, label in COLUMN_LABELS.items():
        if col not in df.columns:
            continue
        config[col] = st.column_config.ListColumn(label) if col == 'Icon' \
            else st.column_config.Column(label)
    return config


def style_by_judgement(df):
    """判定に応じて行に色を付ける"""
    colors = {
        '一致': 'background-color: #edf7ed',
        '要確認': 'background-color: #fdecea',
    }

    def paint(row):
        return [colors.get(row['判定'], 'background-color: #fff8e1')] * len(row)

    return df.style.apply(paint, axis=1)


def render_result_table(judged, source_key):
    """突き合わせ結果の絞り込みと表示"""
    conf = SOURCES[source_key]

    left, right = st.columns([2, 3])
    with left:
        view = st.radio(
            "表示",
            ['要確認のみ', 'すべて', '一致のみ'],
            horizontal=True,
            key=f"view_{source_key}",
            label_visibility='collapsed',
        )
    with right:
        keyword = st.text_input(
            "絞り込み",
            key=f"filter_{source_key}",
            placeholder="商品コード・商品名で絞り込む",
            label_visibility='collapsed',
        )

    view_df = judged
    if view == '要確認のみ':
        view_df = view_df[view_df['判定'] != '一致']
    elif view == '一致のみ':
        view_df = view_df[view_df['判定'] == '一致']

    if keyword.strip():
        haystack = view_df[conf['code_col']].astype(str) + ' ' + view_df[conf['name_col']].astype(str)
        view_df = view_df[haystack.str.contains(keyword.strip(), case=False, na=False)]

    if view_df.empty:
        st.info("この条件に当てはまる商品はありません。")
        return

    st.caption(f"{len(view_df):,} 件を表示")
    # 行数が多いと色付けが重くなるので、一定を超えたら色を付けずに出す
    table = style_by_judgement(view_df) if len(view_df) <= 1000 else view_df
    st.dataframe(
        table,
        use_container_width=True,
        height=min(620, 80 + 35 * len(view_df)),
        column_config=build_column_config(view_df),
        hide_index=True,
    )


def render_source_result(source_key):
    """掲載先ごとの突き合わせ結果"""
    conf = SOURCES[source_key]
    df = st.session_state[conf['df_key']]
    judged = add_judgement(df, conf['price_col'])
    not_found_df = build_not_found_df(source_key)
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')

    if judged is None or judged.empty:
        st.warning("掲載情報を1件も取得できませんでした。")
        judged = pd.DataFrame(columns=['判定'])

    counts = judged['判定'].value_counts()
    matched = int(counts.get('一致', 0))
    mismatched = int(counts.get('要確認', 0))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("リスト", f"{len(st.session_state.sale_list):,} 件")
    col2.metric("価格が一致", f"{matched:,} 件")
    col3.metric("要確認", f"{mismatched:,} 件")
    col4.metric("掲載が見つからず", f"{len(not_found_df):,} 件")

    if mismatched == 0 and not_found_df.empty and matched:
        st.success(f"{conf['label']}の掲載内容はリストと一致しています。")
    elif mismatched:
        st.warning(f"リストと値段が違う商品が {mismatched:,} 件あります。")

    tab_result, tab_missing = st.tabs([
        f"突き合わせ結果（{len(judged):,}）",
        f"掲載が見つからず（{len(not_found_df):,}）",
    ])

    with tab_result:
        render_result_table(judged, source_key)
        st.download_button(
            "この結果をCSVでダウンロード",
            data=judged.to_csv(index=False, encoding='utf-8-sig'),
            file_name=f"突き合わせ結果_{conf['label']}_{stamp}.csv",
            mime="text/csv",
            key=f"dl_result_{source_key}",
        )

    with tab_missing:
        if not_found_df.empty:
            st.success("リストの商品はすべて掲載側で見つかりました。")
        else:
            st.dataframe(
                not_found_df,
                use_container_width=True,
                height=min(500, 80 + 35 * len(not_found_df)),
                hide_index=True,
            )
            st.download_button(
                "見つからなかった商品をCSVでダウンロード",
                data=not_found_df.to_csv(index=False, encoding='utf-8-sig'),
                file_name=f"掲載が見つからず_{conf['label']}_{stamp}.csv",
                mime="text/csv",
                key=f"dl_missing_{source_key}",
            )


def render_welcome():
    """リスト未読込のときの案内"""
    st.info("まず左のサイドバーから、商品リストのCSVを読み込んでください。")
    st.markdown(
        """
        **このツールでできること**

        商品リストの値段と、実際に掲載されている値段が合っているかを1件ずつ突き合わせます。
        ページの入れ替え後に、値段が反映されているか・商品が消えていないかを確かめる用途を想定しています。

        **使い方**

        1. 商品リスト（CSV）を読み込む
        2. 突き合わせたい掲載先を選ぶ（自社サイト・楽天市場・Yahoo!ショッピング）
        3. 実行する。結果は掲載先ごとにタブで並び、値段が違うものだけを絞り込めます
        """
    )


def render_list_preview():
    """読み込んだ商品リストの中身"""
    with st.expander("読み込んだ商品リストを見る"):
        st.dataframe(
            st.session_state.sale_list,
            use_container_width=True,
            height=300,
            hide_index=True,
        )


def main():
    render_sidebar()

    if st.session_state.sale_list is None:
        render_welcome()
        return

    finished = [key for key in SOURCES if st.session_state.get(SOURCES[key]['df_key']) is not None]
    if not finished:
        st.info("サイドバーで掲載先を選び、「③ 実行」のボタンを押してください。")
        render_list_preview()
        return

    tabs = st.tabs([f"{SOURCES[key]['icon']} {SOURCES[key]['label']}" for key in finished])
    for tab, key in zip(tabs, finished):
        with tab:
            render_source_result(key)

    render_list_preview()
    st.caption("掲載内容チェック | 株式会社フレッシュロースター珈琲問屋")

if __name__ == "__main__":
    main()
