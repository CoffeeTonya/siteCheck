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
if 'sale_list' not in st.session_state:
    st.session_state.sale_list = None

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
    
    # salelistの「商品コード」と「通販単価」をdf_onlinestoreにNoで紐づけて追加し、差額列も追加
    salelist_renamed = sale_list.rename(columns={'商品コード': 'No', '通販単価': '通販単価'})
    df_onlinestore['No'] = df_onlinestore['No'].astype(str)
    salelist_renamed['No'] = salelist_renamed['No'].astype(str)

    # 通販単価を追加
    df_onlinestore = pd.merge(df_onlinestore, salelist_renamed[['No', '通販単価']], on='No', how='left')

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
            time.sleep(1.2)
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
        time.sleep(1.2)

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

# サイドバー
def render_sidebar():
    """サイドバーの表示"""
    # サイドバーでデータ取得方法の選択
    if st.session_state.sale_list is not None:
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔧 データ取得方法")
        
        data_source = st.sidebar.radio(
            "取得するデータを選択：",
            ["自社サイトスクレイピング", "楽天市場API取得"],
            index=0
        )
        
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

# メイン処理
def main():
    # CSVファイルアップロードセクション
    st.subheader("📁 CSVファイルアップロード")
    
    uploaded_file = st.file_uploader(
        "CSVファイルを選択してください",
        type=['csv'],
        help="商品データが含まれたCSVファイルをアップロードしてください"
    )
    
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

    # 結果表示
    if st.session_state.df_onlinestore is not None:
        st.markdown("---")
        st.subheader("📊 自社サイト取得結果")
        st.success("スクレイピングが完了しました！")
        
        # 高さを指定してデータフレームを表示
        st.dataframe(
            st.session_state.df_onlinestore,
            use_container_width=True,
            height=600
        )
        
        # ダウンロードボタン
        csv_data = st.session_state.df_onlinestore.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="自社サイトデータをダウンロード",
            data=csv_data,
            file_name=f"自社サイトデータ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    
    if st.session_state.df_rakuten is not None:
        st.markdown("---")
        st.subheader("📊 楽天市場取得結果")
        st.success("楽天市場API取得が完了しました！")
        
        # 高さを指定してデータフレームを表示
        st.dataframe(
            st.session_state.df_rakuten,
            use_container_width=True,
            height=800
        )
        
        # ダウンロードボタン
        csv_data = st.session_state.df_rakuten.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="楽天市場データをダウンロード",
            data=csv_data,
            file_name=f"楽天市場データ_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

    # サイドバーに結果表示
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 取得結果")
    
    if st.session_state.df_onlinestore is not None:
        st.sidebar.success(f"自社サイトデータ: {len(st.session_state.df_onlinestore)}件")
    
    if st.session_state.df_rakuten is not None:
        st.sidebar.success(f"楽天市場データ: {len(st.session_state.df_rakuten)}件")

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
