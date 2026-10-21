import streamlit as st
import requests
import pandas as pd
import datetime
import os
import urllib.parse
import re
import webbrowser

# ページの設定
st.set_page_config(
    page_title="水産事業部：飲食店データ収集・アプローチ管理システム",
    page_icon="🌊",
    layout="wide"
)

MASTER_FILE = "master_database.csv"

def init_master():
    if not os.path.exists(MASTER_FILE):
        df = pd.DataFrame(columns=[
            "取込日", "店舗名", "住所", "電話", "FAX", "メール", "インスタのリンク", "優先アプローチ", "ステータス", "備考"
        ])
        df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")

def format_phone_number(phone_str):
    """+81 を 0 に変換し、不要なスペースや記号を整える関数"""
    if not phone_str or phone_str in ['nan', '-', '']:
        return ""
    formatted = re.sub(r'^\+81\s?', '0', phone_str.strip())
    formatted = formatted.replace(" ", "-").replace("--", "-")
    return formatted

def format_address(address_str):
    """住所から「日本」やそれに続くカンマ・読点・不要な文字列を除去する関数"""
    if not address_str:
        return ""
    cleaned = re.sub(r'^(日本|Japan)[,、\s]*', '', address_str.strip())
    return cleaned.strip()

def determine_approach(row):
    inst = str(row.get('インスタのリンク', '')).strip()
    if inst and inst not in ['', 'nan', '-', 'None']: return 'インスタDM'
    mail = str(row.get('メール', '')).strip()
    if mail and mail not in ['', 'nan', '-', 'None']: return 'メール'
    fax = str(row.get('FAX', '')).strip()
    if fax and fax not in ['', 'nan', '-', 'None']: return 'FAX'
    addr = str(row.get('住所', '')).strip()
    if addr and addr not in ['', 'nan', '-', 'None']: return '郵送'
    return '要確認'

# --- タイトル ---
st.title("🌊 水産事業部：飲食店データ収集・アプローチ管理システム（統合版）")
st.markdown("Google Places APIを使った飲食店データの自動収集と、収集したデータのグループ別アプローチ管理をひとつのアプリで行えます。")

# --- メインのタブ切り替え ---
main_tab1, main_tab2, main_tab3 = st.tabs(["🔍 1. データ収集（API）", "📊 2. アプローチ管理・一括処理", "📁 3. 累計マスターデータベース"])

# ==========================================
# タブ1: データ収集（API）
# ==========================================
with main_tab1:
    st.subheader("Google Places API (New) 飲食店データ収集")
    st.markdown("指定したエリアとキーワードでGoogleマップから店舗情報を新規取得し、マスターデータベースに自動追加します。")
    
    col1, col2 = st.columns(2)
    with col1:
        api_key_input = st.text_input("Google Places API キー", type="password", value="")
        area_input = st.text_input("エリア（例: 中央区、銀座、新橋）", value="中央区")
    with col2:
        keyword_input = st.text_input("キーワード（例: 海鮮居酒屋、寿司）", value="海鮮居酒屋")
        target_count = st.slider("取得目標件数", min_value=5, max_value=50, value=25, step=5)
        
    execute_btn = st.button("データを収集する", type="primary", key="btn_fetch_api")
    
    if execute_btn:
        if not api_key_input:
            st.error("【エラー】APIキーを入力してください。")
        else:
            init_master()
            master_df = pd.read_csv(MASTER_FILE)
            today = datetime.date.today().strftime('%Y-%m-%d')
            
            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key_input,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri"
            }
            body = {
                "textQuery": f"東京都{area_input} {keyword_input}",
                "languageCode": "ja",
                "maxResultCount": 50
            }
            
            with st.spinner(f"Google Maps APIにリクエスト中: [東京都{area_input} {keyword_input}]..."):
                try:
                    response = requests.post(url, headers=headers, json=body)
                except Exception as e:
                    st.error(f"通信エラーが発生しました: {e}")
                    response = None
            
            if response and response.status_code != 200:
                st.error(f"APIエラーが発生しました。レスポンス: {response.text}")
            elif response:
                data = response.json()
                places = data.get("places", [])
                
                if not places:
                    st.warning("該当する店舗が見つかりませんでした。キーワードやエリアを変更してみてください。")
                else:
                    new_leads = []
                    skipped_count = 0
                    
                    for place in places:
                        if len(new_leads) >= target_count:
                            break
                            
                        store_name = place.get("displayName", {}).get("text", "")
                        raw_address = place.get("formattedAddress", "")
                        address = format_address(raw_address)
                        
                        raw_phone = place.get("internationalPhoneNumber", "")
                        phone = format_phone_number(raw_phone)
                        website = place.get("websiteUri", "")
                            
                        is_duplicate = False
                        if not master_df.empty:
                            match_name = (master_df['店舗名'] == store_name).any() if store_name else False
                            match_phone = (master_df['電話'] == phone).any() if (phone and phone not in ['', 'nan', '-']) else False
                            if match_name or match_phone:
                                is_duplicate = True
                                
                        if is_duplicate:
                            skipped_count += 1
                            continue
                            
                        insta_link = website if (website and "instagram.com" in website) else f"https://www.instagram.com/explore/tags/{urllib.parse.quote(store_name)}/"
                        approach = "インスタDM" if insta_link else ("メール" if website else "郵送")
                        
                        new_leads.append({
                            "取込日": today,
                            "店舗名": store_name,
                            "住所": address,
                            "電話": phone,
                            "FAX": "",
                            "メール": "",
                            "インスタのリンク": insta_link,
                            "優先アプローチ": approach,
                            "ステータス": "未アプローチ",
                            "備考": f"公式HP/グルメサイト: {website}" if website else "Google Places API取得"
                        })

                    if not new_leads:
                        st.info(f"検索結果にあった店舗はすべて既存マスターに登録済みでした（スキップ件数: {skipped_count}件）。")
                    else:
                        new_df = pd.DataFrame(new_leads)
                        weekly_filename = f"google_api_leads_{area_input}_{today}.csv"
                        new_df.to_csv(weekly_filename, index=False, encoding='utf-8-sig')
                        
                        updated_master = pd.concat([master_df, new_df], ignore_index=True)
                        updated_master.to_csv(MASTER_FILE, index=False, encoding='utf-8-sig')
                        
                        st.success(f"【完了】新規の店舗 {len(new_df)}件 を取得し、マスターに追加しました！（既存重複除外: {skipped_count}件）")
                        st.dataframe(new_df, width="stretch")
                        
                        with open(weekly_filename, "rb") as f:
                            st.download_button(
                                label="📥 今回の取得CSVをダウンロード",
                                data=f,
                                file_name=weekly_filename,
                                mime="text/csv"
                            )

# ==========================================
# タブ2: アプローチ管理・一括処理
# ==========================================
with main_tab2:
    st.subheader("アプローチ管理・一括処理ダッシュボード")
    st.markdown("マスターデータベースまたは外部ファイルからデータを読み込み、手法ごとに分かれたタブから効率的にアプローチを実行できます。")
    
    data_source = st.radio("読み込み元を選択", ["累計マスターデータベース (master_database.csv) を使用", "任意のCSV/Excelファイルをアップロード"], horizontal=True)
    
    target_df = None
    if data_source.startswith("累計マスター"):
        if os.path.exists(MASTER_FILE):
            target_df = pd.read_csv(MASTER_FILE)
            st.success(f"マスターデータベースを読み込みました（全 {len(target_df)}件）")
        else:
            st.warning("マスターデータベースがまだありません。タブ1（データ収集）でデータを取得してください。")
    else:
        uploaded_file = st.file_uploader("CSVまたはExcelファイルを選択", type=["csv", "xlsx", "xls"], key="uploader_tab2")
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    target_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                else:
                    target_df = pd.read_excel(uploaded_file)
                st.success(f"ファイルを読み込みました ({len(target_df)}件)")
            except Exception as e:
                st.error(f"ファイル読込エラー: {e}")

    if target_df is not None and not target_df.empty:
        if '優先アプローチ' not in target_df.columns:
            target_df['優先アプローチ'] = target_df.apply(determine_approach, axis=1)
            
        sub_tabs = st.tabs(["インスタDM", "メール", "FAX", "郵送"])
        groups = ["インスタDM", "メール", "FAX", "郵送"]
        
        for i, group_name in enumerate(groups):
            with sub_tabs[i]:
                st.markdown(f"### 📌 {group_name} グループの一覧")
                sub_df = target_df[target_df['優先アプローチ'] == group_name].copy()
                
                if sub_df.empty:
                    st.info(f"現在、{group_name}に該当する店舗はありません。")
                    continue
                
                st.markdown(f"対象店舗数: **{len(sub_df)}件**（除外にチェックを入れると対象外にできます）")
                
                if '除外' not in sub_df.columns:
                    sub_df.insert(0, '除外', False)
                
                edited_df = st.data_editor(
                    sub_df,
                    key=f"editor_{group_name}",
                    width="stretch",
                    num_rows="fixed"
                )
                
                active_df = edited_df[edited_df['除外'] == False]
                st.markdown("---")
                
                if group_name == "インスタDM":
                    if st.button(f"🔗 選択中（{len(active_df)}件）のInstagramリンクをブラウザで開く", key=f"btn_insta_{group_name}"):
                        count = 0
                        for _, row in active_df.iterrows():
                            link = str(row.get('インスタのリンク', ''))
                            if link and link not in ['', 'nan', '-', 'None']:
                                if not link.startswith('http'):
                                    link = 'https://' + link.lstrip('@')
                                webbrowser.open(link)
                                count += 1
                        st.success(f"{count}件のInstagramリンクをブラウザで開きました！")
                        
                elif group_name == "FAX":
                    if not active_df.empty:
                        csv_data = active_df[['店舗名', 'FAX', '住所']].to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label=f"📠 FAX送信対象リスト（{len(active_df)}件）をCSVダウンロード",
                            data=csv_data,
                            file_name="fax_target_list.csv",
                            mime="text/csv",
                            key=f"dl_fax_{group_name}"
                        )
                        
                elif group_name == "メール":
                    st.info("✉️ メール配信機能や一括メール作成の連携が可能です。")
                    
                elif group_name == "郵送":
                    if not active_df.empty:
                        print_data = active_df[['店舗名', '住所']].to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label=f"🖨️ 宛名印刷用データ（{len(active_df)}件）をダウンロード",
                            data=print_data,
                            file_name="envelope_target_list.csv",
                            mime="text/csv",
                            key=f"dl_env_{group_name}"
                        )

# ==========================================
# タブ3: 累計マスターデータベース確認
# ==========================================
with main_tab3:
    st.subheader("📊 累計マスターデータベース管理")
    
    if os.path.exists(MASTER_FILE):
        master_df = pd.read_csv(MASTER_FILE)
        st.info(f"現在のマスター登録総数: **{len(master_df)}件**")
        
        search_query = st.text_input("マスター内を店舗名で検索・絞り込み", "", key="master_search")
        if search_query:
            filtered_df = master_df[master_df['店舗名'].str.contains(search_query, na=False)]
            st.dataframe(filtered_df, width="stretch")
        else:
            st.dataframe(master_df, width="stretch")
            
        with open(MASTER_FILE, "rb") as f:
            st.download_button(
                label="📥 累計マスターCSV（全データ）をダウンロード",
                data=f,
                file_name=MASTER_FILE,
                mime="text/csv",
                key="dl_master_all"
            )
    else:
        st.info("まだマスターデータベースが存在しません。タブ1（データ収集）からデータを取得してください。")