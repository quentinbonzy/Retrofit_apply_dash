# -*- coding: utf-8 -*-

# utils.py
import requests
import base64
import json
import pandas as pd
import time
import platform
import datetime as dt
import re
import os

from typing import Dict, Any, Optional, List
# LIGNE CI-DESSOUS COMMENTÉE POUR ÉVITER LE CRASH "No module named assets" :
from pytsas.api import Api

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# %% TSAS Api call & Configuration
token = '***'

if platform.system() == 'Windows': # Local
    api = Api(token=token)
    CA_CERT_PATH_GHE = "H:/1- TOPICS/3 - FTI/TSAS/Dash/Code Gsheet surv auto FTI/cacerts-airbus.pem"
else: # DashServer (Linux)
    api = Api(token=token, certfile="/home/hosting/.pip/CAroot.pem")
    # Sur le serveur, on utilise le certificat copié dans le dossier assets de GitHub
    CA_CERT_PATH_GHE = os.path.join(BASE_DIR, "assets", "cacerts-airbus.pem")

# Noms des tables partagées
table_loads = "PRIVATE_CDVE_TO155726_SURV_AUTO_LOAD_FTI_V11"
table_position = "PRIVATE_CDVE_TO155726_SURV_AUTO_POSITION_FTI_V32"
table_bool = 'PRIVATE_CDVE_TO155726_SURV_AUTO_BOOL_FTI'
#table_combined = 'PRIVATE_CDVE_TO155726_SURV_AUTO_FTI_SOL'
table_combined = 'PRIVATE_CDVE_TO155726_SURV_AUTO_FTI_SOL_V2'
table_vol = 'PRIVATE_CDVE_TO155726_SURV_AUTO_FTI_VOL'

# --- Configuration Globale Partagée ---
github_enterprise_url = 'https://gheprivate.intra.corp/api/v3'
repository_owner = 'flight-controls-testing'
repository_name = 'SurvAuto_FTI'
feedback_file_path = 'feedback_db.json'
snag_file_path = 'snag_db.json'
ACTUATOR_SN_SHEET_ID = '1nxuvqMOR0XK18xXFdrgJupLLu5AqRJ_qH4zI6oas30Y'

access_token = '***'

GITHUB_API_JSON_URL = 'https://gheprivate.intra.corp/api/v3/repos/flight-controls-testing/SurvAuto_FTI/contents/feedback_db.json'
ROOT_URL_AIRBUS_API = "https://armosservices-1s46-d.apps.ocp01.airbus.corp/"
SESSION_REQUESTS_AIRBUS = requests.Session()
SESSION_REQUESTS_AIRBUS.verify = CA_CERT_PATH_GHE
GHE_TOKEN = '***'

TARGET_SPREADSHEET_ID = '1Z6gXkssy01SW07WrlINjPGBqkEKt9B1nDT5C6AqrYeY'
TARGET_SHEET_NAME = 'raw_data'
RANGE_TO_READ_FROM_SHEET = f'{TARGET_SHEET_NAME}!A1:Z5000'

# --- Fonctions GitHub ---
def github_get_file(file_path):
    url = f'{github_enterprise_url}/repos/{repository_owner}/{repository_name}/contents/{file_path}'
    headers = {
        'Authorization': f'Bearer {access_token}', 
        'Accept': 'application/vnd.github.v3+json',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    try:
        response = requests.get(url, headers=headers, verify=CA_CERT_PATH_GHE)
        response.raise_for_status()
        response_data = response.json()
        
        if 'content' in response_data and response_data['content']:
            content_str = base64.b64decode(response_data['content']).decode('utf-8')
        elif 'download_url' in response_data:
            print(f"Fichier > 1Mo. Utilisation de l'URL de téléchargement.")
            download_response = requests.get(response_data['download_url'], headers=headers, verify=CA_CERT_PATH_GHE)
            download_response.raise_for_status()
            content_str = download_response.text
        else:
            raise ValueError("Impossible de récupérer le contenu du fichier depuis l'API GitHub.")
            
        return json.loads(content_str)
    
    except Exception as e:
        print(f"ERREUR dans github_get_file: {e}. Le fichier '{file_path}' est peut-être inaccessible ou corrompu.")
        return {}

def github_update_file(file_path, content, message):
    url = f'{github_enterprise_url}/repos/{repository_owner}/{repository_name}/contents/{file_path}'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    try:
        get_response = requests.get(url, headers=headers, verify=CA_CERT_PATH_GHE)
        get_response.raise_for_status()
        sha = get_response.json()['sha']
        update_data = {
            "message": message,
            "committer": {"name":"to155726","email":"nicolas.refutin@airbus.com"},
            "content": base64.b64encode(json.dumps(content, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8'),
            "sha": sha
        }
        update_response = requests.put(url, headers=headers, json=update_data, verify=CA_CERT_PATH_GHE)
        update_response.raise_for_status()
        return True
    except Exception as e:
        print(f"ERREUR dans github_update_file: {e}")
        return False
   
def synchroniser_google_sheet():
    print("\n--- DÉBUT DE LA SYNCHRONISATION GOOGLE SHEET ---")
    try:
        key_columns_for_comparison = ['Top_Key', 'Second_Key', 'Type', 'PARAMETER']
        json_data = github_get_file(feedback_file_path)
        if not json_data:
            print("ERREUR Gsheet Sync: Échec de la récupération du JSON. Arrêt.")
            return
        
        list_for_df = transform_json_to_flat_list_for_df(json_data)
        new_df = pd.DataFrame(list_for_df) if list_for_df else pd.DataFrame()

        if new_df.empty:
            print("INFO Gsheet Sync: DataFrame depuis GitHub est vide. Aucune action.")
            return
        
        final_column_order = [
            'Top_Key', 'Second_Key','Test_Date', 'Type', 'PARAMETER', 'STATE',
            'Status', '0+', 'Val(0+)',
            '0-', 'Val(0-)', 'Droop+', 'Val(D+)', 'Droop-', 'Val(D-)', 'Full+',
            'Val(F+)', 'Full-', 'Val(F-)', 
            'FZ',             
            'FZ moy damp',    
            'FZ moy active',  
            'Comments',
            'HYD_rise', 'Temperature_Value', 'Temperature_Diff_TAT1', 'OOD',
            'Correction value', 'Retrofit', 'Statut', 'Change reason'
        ]
        
        for col in final_column_order:
            if col not in new_df.columns:
                new_df[col] = None
        
        new_df_reordered = new_df[final_column_order]
        old_df = load_dataframe_from_airbus_api(TARGET_SPREADSHEET_ID, RANGE_TO_READ_FROM_SHEET)

        old_df_aligned = pd.DataFrame()
        if old_df is not None and not old_df.empty:
            old_df_aligned = old_df.reindex(columns=final_column_order)

        new_df_normalized = new_df_reordered.fillna('').astype(str)
        old_df_normalized = old_df_aligned.fillna('').astype(str)

        send_update_to_api = False
        if old_df_normalized.empty:
            send_update_to_api = True
        else:
            comparison_result = compare_dataframes(old_df_normalized, new_df_normalized, key_columns_for_comparison)
            if not comparison_result:
                send_update_to_api = True
        
        if send_update_to_api:
            api_response = update_spreadsheets_values_airbus_api(TARGET_SPREADSHEET_ID, TARGET_SHEET_NAME, new_df_normalized)
                
    except Exception as e:
        print(f"ERREUR CRITIQUE dans synchroniser_google_sheet : {e}")
        
def transform_json_to_flat_list_for_df(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    flat_list = []
    if not isinstance(json_data, dict):
        return flat_list
        
    for msn, tests in json_data.items():
        if not isinstance(tests, dict): continue
        for test_name, content_dict in tests.items():
            if not isinstance(content_dict, dict): continue
            
            is_completed = content_dict.get('check', False)
            status_text = "Completed" if is_completed else "In Progress"
            
            test_date_iso = content_dict.get('test_date')
            test_date_formatted = ''
            if test_date_iso:
                try:
                    test_date_formatted = dt.datetime.fromisoformat(test_date_iso.replace('Z', '+00:00')).strftime('%d-%m-%Y')
                except:
                    test_date_formatted = test_date_iso
            
            for section_type in ['loads', 'position', 'temperature', 'wo_loads', 'wo_position', 'corrections']:
                if section_type in content_dict and isinstance(content_dict[section_type], list):
                    for item in content_dict[section_type]:
                        if not isinstance(item, dict) or not item.get('PARAMETER'):
                            continue

                        row = {
                            'Top_Key': msn,
                            'Second_Key': test_name,
                            'Test_Date': test_date_formatted,
                            'Type': section_type,
                            'PARAMETER': item.get('PARAMETER'),
                            'Status': status_text,
                            'Comments': item.get('Comments'),
                            'STATE': item.get('STATE') 
                        }
                        
                        if section_type in ['loads', 'position', 'wo_loads', 'wo_position']:
                            row.update({
                                '0+': item.get('0+'), 'Val(0+)': item.get('Val(0+)') or item.get('0+ Val'),
                                '0-': item.get('0-'), 'Val(0-)': item.get('Val(0-)') or item.get('0- Val'),
                                'Droop+': item.get('D+'), 'Val(D+)': item.get('D+ Val'),
                                'Droop-': item.get('D-'), 'Val(D-)': item.get('D- Val'),
                                'Full+': item.get('F+') or item.get('Full+'), 
                                'Val(F+)': item.get('F+ Val') or item.get('Val(F+)'),
                                'Full-': item.get('F-') or item.get('Full-'), 
                                'Val(F-)': item.get('F- Val') or item.get('Val(F-)') ,
                                'FZ': item.get('FZ'),                  
                                'FZ moy damp': item.get('FZ moy damp'), 
                                'FZ moy active': item.get('FZ moy active') 
                            })
                        elif section_type == 'temperature':
                            row.update({
                                'HYD_rise': item.get('HYD rise'),
                                'Temperature_Value': item.get('Val()'),
                                'Temperature_Diff_TAT1': item.get('Val(diff_TAT1)'),
                                'OOD': item.get('OOD'),
                            })

                        elif section_type == 'corrections':
                            row.update({
                                'Correction value': item.get('value'),
                                'Retrofit': item.get('retrofit'),
                                'Statut': item.get('status'),
                                'Change reason': item.get('reason')
                            })

                        flat_list.append(row)
    return flat_list

def normalize_test_to_int(test_string: str) -> int:
    if not isinstance(test_string, str) or not test_string:
        return -1
    try:
        numeric_part = ''.join(filter(str.isdigit, test_string))
        if numeric_part:
            return int(numeric_part)
        return -1
    except (ValueError, TypeError):
        return -1

def get_snag_comments_for_test(msn: str, test: str, all_tests_df: pd.DataFrame) -> Dict[str, str]:
    snag_comments = {}
    
    all_snags = github_get_file(snag_file_path)
    if not isinstance(all_snags, list) or not all_snags:
        return snag_comments

    current_test_num = normalize_test_to_int(test)
    if current_test_num == -1:
        return snag_comments

    relevant_snags = []
    all_msn_snags = [s for s in all_snags if s.get('MSN') == msn]
    for snag in all_msn_snags:
        status = snag.get('Status')
        if status == 'Open' or status == 'Closed':
            relevant_snags.append(snag)

    if not relevant_snags:
        return snag_comments

    for snag in relevant_snags:
        snag_param_raw = snag.get('Parameter')
        snag_id = snag.get('Snag ID')
        if not snag_param_raw or not snag_id:
            continue
        
        name_clean = str(snag_param_raw).strip().upper().replace(" ", "")
        root = re.sub(r'^\d+', '', name_clean).replace("-", "").replace("_", "")
        
        exceptions = {
            "RUF1": "RUDF1", "RUF2": "RUDF2", "RUF3": "RUDF3",
            "T0F1": "THSF1", "T0F2": "THSF2",
            "T0D1": "THSD1", "T0D2": "THSD2"
        }
        
        param_root = root
        for key, val in exceptions.items():
            if root.startswith(key): 
                param_root = val
                break
        
        phoenix_param = f"{param_root}_FTI"

        start_test = snag.get('Start test')
        start_date = snag.get('Start Date')
        end_test = snag.get('End test')
        end_date = snag.get('End Date')

        effective_start_test_num = -1
        effective_end_test_num = -1

        start_test_num = normalize_test_to_int(start_test)
        if start_test_num != -1:
            effective_start_test_num = start_test_num
        elif start_date:
            try:
                start_date_dt = pd.to_datetime(start_date, format='%d/%m/%y', errors='coerce').tz_localize('UTC')
                if pd.notna(start_date_dt):
                    future_tests = all_tests_df[all_tests_df['Test Date'] >= start_date_dt]
                    if not future_tests.empty:
                        first_test_name = future_tests.sort_values(by='Test Date', ascending=True)['Test'].iloc[0]
                        effective_start_test_num = normalize_test_to_int(first_test_name)
            except: pass
        
        if effective_start_test_num == -1: continue

        end_test_num = normalize_test_to_int(end_test)
        if end_test_num != -1:
            effective_end_test_num = end_test_num
        elif end_date:
            try:
                end_date_dt = pd.to_datetime(end_date, format='%d/%m/%y', errors='coerce').tz_localize('UTC')
                if pd.notna(end_date_dt):
                    relevant_tests = all_tests_df[all_tests_df['Test Date'] <= end_date_dt]
                    if not relevant_tests.empty:
                        latest_test_name = relevant_tests.sort_values(by='Test Date', ascending=False)['Test'].iloc[0]
                        effective_end_test_num = normalize_test_to_int(latest_test_name)
            except: pass

        is_in_range = False
        if effective_end_test_num != -1:
            is_in_range = (effective_start_test_num <= current_test_num <= effective_end_test_num)
        else:
            is_in_range = (current_test_num >= effective_start_test_num)
        
        if is_in_range:
            comment = f"SNAG {snag_id}"
            if phoenix_param in snag_comments:
                if comment not in snag_comments[phoenix_param]:
                    snag_comments[phoenix_param] += f", {comment}"
            else:
                snag_comments[phoenix_param] = comment

    return snag_comments

def get_repo_objects_from_ghe(objects_url: str) -> Dict[str, Any]:
    headers = {"Authorization": f"token {GHE_TOKEN}"}
    while True:
        response = requests.get(objects_url, headers=headers, verify=CA_CERT_PATH_GHE)
        remaining_requests = int(response.headers.get("X-RateLimit-Remaining", 1))
        
        if response.status_code == 200:
            return response.json() 
        
        if remaining_requests <= 0: 
            reset_time_epoch = int(response.headers.get("X-RateLimit-Reset", time.time() + 60)) 
            sleep_duration = max(0, reset_time_epoch - int(time.time())) + 30 
            time.sleep(sleep_duration)
        else:
            response.raise_for_status() 

def load_dataframe_from_airbus_api(spreadsheet_id: str, sheet_range: str) -> Optional[pd.DataFrame]:
    _get_values_url = f'{ROOT_URL_AIRBUS_API.rstrip("/")}/gws/get_spreadsheets_values/'
    params = {"spreadsheetId": spreadsheet_id, "values_range": sheet_range}
    response = None
    try:
        response = SESSION_REQUESTS_AIRBUS.get(_get_values_url, params=params)
        response.raise_for_status()
        data = response.json()
        if "values" not in data or not data["values"]:
            return pd.DataFrame()
        values_list = data["values"]
        if len(values_list) < 1: return pd.DataFrame()
        headers = values_list[0]; data_rows = values_list[1:]
        df = pd.DataFrame(data_rows, columns=headers).fillna('').astype(str)
        return df
    except Exception as e:
        return None

def compare_dataframes(df1: pd.DataFrame, df2: pd.DataFrame, key_columns: List[str]) -> bool:
    if df1.empty and df2.empty: return True
    if df1.empty or df2.empty: return False
    cols_df1 = set(df1.columns); cols_df2 = set(df2.columns)
    if not all(col in cols_df1 for col in key_columns) or \
       not all(col in cols_df2 for col in key_columns):
        return False
    if cols_df1 != cols_df2:
        return False
    try:
        df1_sorted = df1.sort_values(by=key_columns).reset_index(drop=True)
        df2_sorted = df2.sort_values(by=key_columns).reset_index(drop=True)
        return df1_sorted.equals(df2_sorted)
    except Exception as e: return False

def fetch_padaone_params():
    url = f"{ROOT_URL_AIRBUS_API}padaone/parameters/"
    try:
        response = SESSION_REQUESTS_AIRBUS.get(url, timeout=10)
        response.raise_for_status()
        return sorted(response.json())
    except Exception as e:
        return []

def fetch_padaone_history(parameter_name):
    url = f"{ROOT_URL_AIRBUS_API}padaone/history/{parameter_name}"
    try:
        response = SESSION_REQUESTS_AIRBUS.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"history": []}

def update_spreadsheets_values_airbus_api(
    spreadsheetId: str, sheet_name: str, df: pd.DataFrame,
    value_input_option: Optional[str] = 'RAW', chunk_size: int = 5000):
    
    api_url_base = ROOT_URL_AIRBUS_API.rstrip('/') + '/'
    _update_endpoint_url = f'{api_url_base}gws/update_spreadsheets_values/'
    (total_df_rows, df_cols) = df.shape
    if df.empty:
        return None
        
    last_api_response = None
    for i, chunk_df_start_index in enumerate(range(0, total_df_rows, chunk_size)):
        chunk_df_end_index = min(chunk_df_start_index + chunk_size, total_df_rows)
        current_data_chunk_df = df.iloc[chunk_df_start_index:chunk_df_end_index]
        num_data_rows_in_chunk = current_data_chunk_df.shape[0]
        
        if num_data_rows_in_chunk == 0:
            continue
            
        payload_data_for_api = []
        if chunk_df_start_index == 0:
            payload_data_for_api.append(df.columns.tolist())
            
        payload_data_for_api.extend(current_data_chunk_df.values.tolist())
        num_rows_in_api_payload = len(payload_data_for_api)
        
        if chunk_df_start_index == 0:
            sheet_target_start_cell = "A1"
            sheet_target_end_row = num_rows_in_api_payload 
        else:
            sheet_data_target_start_row = chunk_df_start_index + 2 
            sheet_target_start_cell = f"A{sheet_data_target_start_row}"
            sheet_target_end_row = sheet_data_target_start_row + num_rows_in_api_payload - 1
            
        current_chunk_target_range = f'{sheet_name}!{sheet_target_start_cell}:{rowcol_to_a1(sheet_target_end_row, df_cols)}'
        
        params_for_api_call = {
            'spreadsheetId': spreadsheetId,
            'values_range': current_chunk_target_range,
            'data': payload_data_for_api,
            'value_input_option': value_input_option
        }
        
        json_payload_string = json.dumps(params_for_api_call)
        
        try:
            current_response = SESSION_REQUESTS_AIRBUS.post(_update_endpoint_url, data=json_payload_string)
            current_response.raise_for_status()
            last_api_response = current_response 
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            return None 
            
    return last_api_response

def push_corrections_to_gsheet(msn, batch_data):
    SHEET_CORRECTIONS = "Corrections"
    headers = ["Timestamp", "MSN", "Parameter", "Correction value", "Retrofit", "Statut", "Change reason", "Application date"]
    
    df_existing = load_dataframe_from_airbus_api(TARGET_SPREADSHEET_ID, f"{SHEET_CORRECTIONS}!A1:H5000")
    
    if df_existing is None or df_existing.empty:
        df_final = pd.DataFrame(columns=headers)
    else:
        df_final = df_existing.reindex(columns=headers)

    new_rows = []
    timestamp = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    for item in batch_data:
        new_rows.append({
            "Timestamp": timestamp,
            "MSN": msn,
            "Parameter": item['param'],
            "Correction value": item['value'],
            "Retrofit": item['retrofit'],
            "Statut": "In progress",
            "Change reason": item['reason'],
            "Application date": ""
        })
    
    df_new = pd.DataFrame(new_rows)
    df_updated = pd.concat([df_final, df_new], ignore_index=True).fillna('').astype(str)

    return update_spreadsheets_values_airbus_api(TARGET_SPREADSHEET_ID, SHEET_CORRECTIONS, df_updated)

MAGIC_NUMBER_A1 = 64
def rowcol_to_a1(row: int, col: int) -> str:
    row = int(row); col = int(col)
    if row < 1 or col < 1: raise ValueError(f"Indices L/C pour A1 >= 1. Reçu: L{row},C{col}")
    div = col; column_label = ""
    while div > 0:
        quotient, remainder = divmod(div, 26)
        if remainder == 0: remainder = 26; quotient -= 1
        column_label = chr(remainder + MAGIC_NUMBER_A1) + column_label
        div = quotient
    return f"{column_label}{row}"
