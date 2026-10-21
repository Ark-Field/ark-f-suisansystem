import streamlit as st
import requests
import pandas as pd
import datetime
import os
import urllib.parse
import re
import webbrowser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO

# ReportLab imports for PDF generation
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ページの設定
st.set_page_config(
    page_title="アーク水産事業部：飲食店データ収集・アプローチ管理システム",
    page_icon="🌊",
    layout="wide"
)

MASTER_FILE = "master_database.csv"

def init_master():
    if not os.path.exists(MASTER_FILE):
        df = pd.DataFrame(columns=[
            "取込日", "郵便番号", "店舗名", "住所", "電話", "FAX", "メール", "インスタのリンク", "優先アプローチ", "ステータス", "アプローチ結果", "備考"
        ])
        df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")
    else:
        df = pd.read_csv(MASTER_FILE)
        updated = False
        if "郵便番号" not in df.columns:
            df.insert(1, "郵便番号", "")
            updated = True
        if "アプローチ結果" not in df.columns:
            df["アプローチ結果"] = "-"
            updated = True
        if "ステータス" not in df.columns:
            df["ステータス"] = "未アプローチ"
            updated = True
        if "メール" not in df.columns:
            df["メール"] = ""
            updated = True
        if updated:
            df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")

def format_phone_number(phone_str):
    if not phone_str or phone_str in ['nan', '-', '']:
        return ""
    formatted = re.sub(r'^\+81\s?', '0', phone_str.strip())
    formatted = formatted.replace(" ", "-").replace("--", "-")
    return formatted

def format_address(address_str):
    if not address_str:
        return ""
    cleaned = re.sub(r'^(日本|Japan)[,、\s]*', '', address_str.strip())
    return cleaned.strip()

def extract_postal_code(address_str):
    """住所文字列から郵便番号（例: 104-0061 や 1040061）を抽出する関数"""
    if not address_str:
        return ""
    match = re.search(r'(?:〒)?([0-9]{3}-[0-9]{4}|[0-9]{7})', address_str)
    if match:
        raw_code = match.group(1)
        if len(raw_code) == 7 and '-' not in raw_code:
            return f"{raw_code[:3]}-{raw_code[3:]}"
        return raw_code
    return ""

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

init_master()

st.title("🌊 水産事業部：飲食店データ収集・アプローチ管理システム（完全統合版）")
st.markdown("Google Places APIを使ったデータ収集、インスタ5件分割、SMTP一斉送信、長4封筒PDF宛名印刷システムです。")

# 共通：今週の取得件数を計算してトップにアラート表示する関数
def check_weekly_alert():
    if os.path.exists(MASTER_FILE):
        df = pd.read_csv(MASTER_FILE)
        if not df.empty and '取込日' in df.columns:
            try:
                df['取込日_dt'] = pd.to_datetime(df['取込日'], errors='coerce')
                today_date = datetime.date.today()
                start_of_week = today_date - datetime.timedelta(days=today_date.weekday())
                this_week_df = df[df['取込日_dt'].dt.date >= start_of_week]
                this_week_count = len(this_week_df)
                
                if this_week_count > 50:
                    st.warning(f"🚨 **【今週のペース超過アラート】** 今週すでに新規データが **{this_week_count}件** 登録されています（50件オーバー）。アプローチの進捗やAPI利用状況をご確認ください！")
                else:
                    st.info(f"📊 **今週の登録状況**: 現在 **{this_week_count}件** / 目安50件")
            except Exception:
                pass

check_weekly_alert()

main_tab1, main_tab2, main_tab3 = st.tabs(["🔍 1. データ収集（API）", "📊 2. アプローチ管理・アプローチの実行", "📁 3. 累計マスターデータベース"])

# ==========================================
# タブ1: データ収集（API）
# ==========================================
with main_tab1:
    st.subheader("Google Places API (New) 飲食店データ収集")
    st.markdown("指定したエリアとキーワードでGoogleマップから店舗情報を新規取得し、マスターデータベースに自動追加します。")
    
    col1, col2 = st.columns(2)
    with col1:
        api_key_input = st.text_input("Google Places API キー", type="password", value="")
        area_input = st.text_input("エリア（例: 本八幡、銀座、新橋）", value="中央区")
    with col2:
        keyword_input = st.text_input("キーワード（例: 海鮮居酒屋、寿司、宅配）", value="海鮮居酒屋")
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
                        postal_code = extract_postal_code(raw_address)
                        
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
                            "郵便番号": postal_code,
                            "店舗名": store_name,
                            "住所": address,
                            "電話": phone,
                            "FAX": "",
                            "メール": "",
                            "インスタのリンク": insta_link,
                            "優先アプローチ": approach,
                            "ステータス": "未アプローチ",
                            "アプローチ結果": "-",
                            "備考": website if website else f"https://www.google.com/search?q={urllib.parse.quote(store_name + ' 食べログ')}"
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
# タブ2: アプローチ管理・実行
# ==========================================
with main_tab2:
    st.subheader("📊 アプローチ管理・全体＆実行")
    st.markdown("すべての店舗データを一覧で確認しながら、各種修正やアプローチ結果の入力を行えます。")
    
    if os.path.exists(MASTER_FILE):
        target_df = pd.read_csv(MASTER_FILE)
    else:
        target_df = pd.DataFrame()

    if target_df.empty:
        st.warning("マスターデータベースがまだありません。タブ1（データ収集）でデータを取得してください。")
    else:
        if '郵便番号' not in target_df.columns:
            target_df.insert(1, '郵便番号', "")
        if '優先アプローチ' not in target_df.columns:
            target_df['優先アプローチ'] = target_df.apply(determine_approach, axis=1)
        if 'ステータス' not in target_df.columns:
            target_df['ステータス'] = "未アプローチ"
        if 'アプローチ結果' not in target_df.columns:
            target_df['アプローチ結果'] = "-"
        if 'メール' not in target_df.columns:
            target_df['メール'] = ""
        if '除外' not in target_df.columns:
            target_df.insert(0, '除外', False)

        # 💡 【解決策】クリックして確実に別タブで開ける「リンク一発確認ビュー（st.dataframe）」を上部に配置！
        with st.expander("🌐 【ここをクリック】食べログ・公式HP・インスタのリンクを1クリックで開く専用ビュー", expanded=True):
            st.markdown("下のテーブルのリンク（URL）をクリックすると、**確実に別タブでサイトが開きます**。（※編集用テーブルは下部にあります）")
            link_view_df = target_df[['店舗名', '優先アプローチ', 'インスタのリンク', '備考', '電話', '住所']].copy()
            link_view_df.rename(columns={'備考': '公式HP/食べログ等'}, inplace=True)
            st.dataframe(
                link_view_df,
                width="stretch",
                column_config={
                    "インスタのリンク": st.column_config.LinkColumn("インスタのリンク", help="クリックして別タブで開く"),
                    "公式HP/食べログ等": st.column_config.LinkColumn("公式HP/食べログ等", help="クリックして別タブで開く")
                }
            )

        st.markdown("---")
        st.markdown("### 📝 全体編集テーブル（ステータス・アプローチ結果の入力・保存はこちら）")
        
        edited_master_df = st.data_editor(
            target_df,
            key="master_full_editor",
            width="stretch",
            num_rows="fixed",
            column_config={
                "除外": st.column_config.CheckboxColumn("除外", help="チェックを入れるとアプローチ対象から除外されます"),
                "優先アプローチ": st.column_config.SelectboxColumn(
                    "優先アプローチ",
                    options=["インスタDM", "メール", "FAX", "郵送", "要確認"],
                    required=True
                ),
                "ステータス": st.column_config.SelectboxColumn(
                    "ステータス",
                    options=["未アプローチ", "active", "商談化", "見送り"],
                    required=True
                ),
                "アプローチ結果": st.column_config.SelectboxColumn(
                    "アプローチ結果",
                    options=["-", "● (成功・反応あり)", "▲ (保留・要再連絡)", "✖ (不通・拒否)", "留守電"],
                    required=True
                )
            }
        )

        if st.button("💾 編集した内容をマスターデータベースに保存する", type="primary", key="btn_save_master"):
            save_df = edited_master_df.drop(columns=['除外'], errors='ignore')
            save_df.to_csv(MASTER_FILE, index=False, encoding='utf-8-sig')
            st.success("【保存完了】変更内容をマスターデータベースに反映しました！")

        active_df = edited_master_df[edited_master_df['除外'] == False]

        st.markdown("---")
        st.subheader("🚀 手法別・実行アクション")

        exec_tabs = st.tabs(["🔗 インスタDM（3分の1幅でコンパクト配置）", "📠 FAXリスト", "✉️ SMTPメール送信", "🖨️ 郵送・長4封筒PDF"])

        with exec_tabs[0]:
            insta_sub = active_df[active_df['優先アプローチ'] == 'インスタDM']
            st.markdown(f"対象店舗数: **{len(insta_sub)}件**")
            
            insta_rows = []
            for _, row in insta_sub.iterrows():
                link = str(row.get('インスタのリンク', ''))
                if link and link not in ['', 'nan', '-', 'None']:
                    if not link.startswith('http'):
                        link = 'https://' + link.lstrip('@')
                    insta_rows.append((row.get('店舗名', ''), link))
            
            if not insta_rows:
                st.info("対象のインスタDMリンクがありません。")
            else:
                col_left, col_mid, col_right = st.columns([1, 1, 1])
                with col_left:
                    st.markdown("##### 📌 インスタ一括オープン（5件ずつ）")
                    chunk_size = 5
                    for i in range(0, len(insta_rows), chunk_size):
                        chunk = insta_rows[i:i+chunk_size]
                        s_idx = i + 1
                        e_idx = min(i + chunk_size, len(insta_rows))
                        if st.button(f"🔗 インスタを開く: 第 {s_idx} 〜 {e_idx} 件目（{len(chunk)}件）", key=f"btn_chunk_{i}"):
                            for name, lk in chunk:
                                webbrowser.open(lk)
                            st.success(f"{s_idx} 〜 {e_idx} 件目のリンクを開きました！")
                with col_mid:
                    st.info("💡 **ヒント**: 左のボタンを押すと、ブラウザに5件ずつInstagramのページが別タブで立ち上がります。")

        with exec_tabs[1]:
            fax_sub = active_df[active_df['優先アプローチ'] == 'FAX']
            st.markdown(f"対象店舗数: **{len(fax_sub)}件**")
            if not fax_sub.empty:
                csv_data = fax_sub[['店舗名', 'FAX', '住所']].to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label=f"📠 FAX送信対象リスト（{len(fax_sub)}件）をCSVダウンロード",
                    data=csv_data,
                    file_name="fax_target_list.csv",
                    mime="text/csv",
                    key="dl_fax_all"
                )
            else:
                st.info("対象のFAX店舗はありません。")

        with exec_tabs[2]:
            mail_sub = active_df[active_df['優先アプローチ'] == 'メール']
            st.markdown(f"対象店舗数: **{len(mail_sub)}件**")
            
            valid_mails = []
            for _, row in mail_sub.iterrows():
                m = str(row.get('メール', '')).strip()
                if m and m not in ['', 'nan', '-', 'None', 'nan']:
                    valid_mails.append((row.get('店舗名', ''), m))
            
            if not mail_sub.empty:
                st.dataframe(mail_sub[['店舗名', 'メール', '備考']], width="stretch")
            
            st.markdown("---")
            st.markdown("### ⚙️ SMTPメール自動送信設定")
            with st.form("smtp_form"):
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    smtp_server = st.text_input("SMTPサーバー", value="smtp.arkf.jp")
                    smtp_port = st.number_input("ポート番号", value=587, step=1)
                    smtp_user = st.text_input("送信元メールアドレス (User)", value="fax@arkf.jp")
                with col_s2:
                    smtp_password = st.text_input("メールパスワード", type="password", value="")
                    mail_subject = st.text_input("メール件名", value="【水産事業部】業務用冷凍寿司ネタの直販会社です。価格比較検討ください。在庫豊富にあります！！")
                
                mail_body = st.text_area("メール本文", value="""平素は格別のご愛顧を賜り厚く御礼申し上げます。

弊社㈱アークフィールド（千葉県市川市に所在）では冷凍すしネタをストックして直送にてご提供しております。
ぜひ一度、サンプルやカタログをご覧ください。

よろしくお願い申し上げます。詳しくは https://secure01.blue.shared-server.net/www.arkf.jp/index.html""")
                
                send_button = st.form_submit_button("🚀 登録されているメールアドレスに一斉送信する")
                
                if send_button:
                    if not smtp_user or not smtp_password:
                        st.error("送信元メールアドレスとパスワードを入力してください。")
                    elif not valid_mails:
                        st.warning("有効なメールアドレスが登録されている店舗がありません。")
                    else:
                        success_count = 0
                        fail_count = 0
                        
                        with st.spinner("メールを送信中..."):
                            try:
                                server = smtplib.SMTP(smtp_server, int(smtp_port))
                                server.starttls()
                                server.login(smtp_user, smtp_password)
                                
                                for store_name, recipient in valid_mails:
                                    try:
                                        msg = MIMEMultipart()
                                        msg['From'] = smtp_user
                                        msg['To'] = recipient
                                        msg['Subject'] = mail_subject
                                        
                                        personalized_body = f"{store_name} ご担当者様\n\n" + mail_body
                                        msg.attach(MIMEText(personalized_body, 'plain'))
                                        
                                        server.sendmail(smtp_user, recipient, msg.as_string())
                                        success_count += 1
                                    except Exception as e:
                                        fail_count += 1
                                        
                                server.quit()
                                st.success(f"【送信完了】 成功: {success_count}件 / 失敗: {fail_count}件")
                            except Exception as e:
                                st.error(f"SMTPサーバーへの接続またはログインに失敗しました: {e}")

        with exec_tabs[3]:
            post_sub = active_df[active_df['優先アプローチ'] == '郵送']
            st.markdown(f"対象店舗数: **{len(post_sub)}件**")
            
            if not post_sub.empty:
                st.dataframe(post_sub[['郵便番号', '店舗名', '住所']], width="stretch")
                
                if st.button("🖨️ 選択中店舗の長4封筒用 宛名PDFを生成する", type="primary", key="btn_gen_pdf"):
                    try:
                        buffer = BytesIO()
                        envelope_width = 205 * mm
                        envelope_height = 90 * mm
                        c = canvas.Canvas(buffer, pagesize=(envelope_width, envelope_height))
                        
                        # フォントの決定（ローカルWindows優先、なければNoto Sans JPを自動ダウンロード）
                        font_name = 'Helvetica'
                        font_path = "C:\\Windows\\Fonts\\meiryo.ttc"
                        if not os.path.exists(font_path):
                            font_path = "C:\\Windows\\Fonts\\msgothic.ttc"
                        
                        if os.path.exists(font_path):
                            pdfmetrics.registerFont(TTFont('JapaneseFont', font_path))
                            font_name = 'JapaneseFont'
                        else:
                            # Streamlit Cloud (Linux) 環境では Noto Sans JP を自動取得
                            noto_font_path = "NotoSansJP-Regular.ttf"
                            if not os.path.exists(noto_font_path):
                                font_url = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP-Regular.ttf"
                                try:
                                    r = requests.get(font_url)
                                    if r.status_code == 200:
                                        with open(noto_font_path, "wb") as f_font:
                                            f_font.write(r.content)
                                except Exception:
                                    pass
                            
                            if os.path.exists(noto_font_path):
                                pdfmetrics.registerFont(TTFont('NotoSansJP', noto_font_path))
                                font_name = 'NotoSansJP'
                        
                        for _, row in post_sub.iterrows():
                            p_code = str(row.get('郵便番号', '')).strip()
                            store_name = str(row.get('店舗名', '')).strip()
                            address = str(row.get('住所', '')).strip()
                            
                            c.saveState()
                            c.setFont(font_name, 12)
                            
                            if p_code and p_code != 'nan':
                                c.drawString(120 * mm, 70 * mm, f"〒 {p_code}")
                            
                            c.setFont(font_name, 11)
                            c.drawString(40 * mm, 50 * mm, address)
                            
                            c.setFont(font_name, 16)
                            c.drawString(45 * mm, 32 * mm, f"{store_name} 御中")
                            
                            c.restoreState()
                            c.showPage()
                        
                        c.save()
                        buffer.seek(0)
                        
                        st.success("長4封筒用宛名PDFの生成が完了しました！（文字化け防止対応済み）")
                        st.download_button(
                            label="📥 長4封筒 宛名PDFをダウンロードする",
                            data=buffer,
                            file_name="envelope_addresses_chou4.pdf",
                            mime="application/pdf",
                            key="download_pdf_chou4"
                        )
                    except Exception as e:
                        st.error(f"PDF生成中にエラーが発生しました: {e}")
            else:
                st.info("そのほかの郵送対象店舗はありません。")

# ==========================================
# タブ3: 累計マスターデータベース確認＆読込
# ==========================================
main_tab3_obj = main_tab3
with main_tab3_obj:
    st.subheader("📊 累計マスターデータベース管理・バックアップ・読込")
    
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
        st.info("まだマスターデータベースが存在しません。タブ1（データ収集）からデータを取得するか、下からCSVをアップロードしてください。")

    st.markdown("---")
    st.markdown("### 🔄 マスターCSVの読込（復元・追加統合）")
    st.markdown("過去にダウンロードしたバックアップCSVファイルをアップロードすると、現在のマスターに重複を除外しながらデータを自動で合流・追加できます。")
    
    uploaded_file = st.file_uploader("マスターCSVファイルを選択", type=["csv"], key="master_uploader")
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.markdown(f"選択されたファイル内のデータ件数: **{len(uploaded_df)}件**")
            if st.button("🚀 アップロードしたCSVを現在のマスターに統合・復元する", type="primary"):
                current_master = pd.read_csv(MASTER_FILE) if os.path.exists(MASTER_FILE) else pd.DataFrame()
                combined = pd.concat([current_master, uploaded_df], ignore_index=True).drop_duplicates(subset=['店舗名'], keep='first')
                combined.to_csv(MASTER_FILE, index=False, encoding='utf-8-sig')
                added_count = len(combined) - len(current_master)
                st.success(f"【統合完了】マスターデータを合流しました！（新規追加: {added_count}件 / 重複スキップ）")
                st.rerun()
        except Exception as e:
            st.error(f"ファイルの読み込みに失敗しました: {e}")