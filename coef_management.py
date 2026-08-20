import dash
from dash import html, dcc, Input, Output, State, ALL, MATCH, callback_context, no_update
import json
import time
import pandas as pd
import urllib3
import math

from app import app 
from utils import api, table_combined, push_corrections_to_gsheet, github_get_file, github_update_file, update_spreadsheets_values_airbus_api, TARGET_SPREADSHEET_ID, load_dataframe_from_airbus_api

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

letter2testtype = {'S':'STATIC','X':'INTERFLIGHT','F':'FLIGHT','V':'FLIGHT','P':'RUN','R':'RUN'}

# --- CONFIGURATION ---
MAX_PARAMS = 15 

def check_ac_type(msn):
    if not msn: return "A320"
    first = str(msn)[0].upper()
    if first == 'V': return 'A350'
    if first == 'P': return 'A330'
    if first == 'M': return 'A321'
    if first == 'L': return 'A380'
    return 'A320'

def get_msn_number(msn_str):
    return ''.join(filter(str.isdigit, str(msn_str)))

def safe_float_format(val, precision=4):
    """Formate proprement les nombres pour l'affichage."""
    try:
        if val is None or val == "": return ""
        return f"{float(val):.{precision}f}"
    except:
        return str(val)

def safe_eval(v):
    """Calcule le résultat si la chaîne commence par '=', sinon renvoie la valeur brute"""
    if v and str(v).startswith('='):
        try:
            return str(pd.eval(str(v)[1:]))
        except Exception as e:
            return v
    return v

def parse_target_values(value_str):
    """Extrait les coefficients ou points SLINE de la chaîne stockée."""
    targets = {}
    if "x0=" in value_str:
        segments = value_str.split(" ; ")
        for seg in segments:
            parts = seg.split(", ")
            parts = [p for p in parts if "x" in p or "y" in p]
            
            if len(parts) >= 2:
                try:
                    x_val = float(parts[0].split("=")[1])
                    y_val = float(parts[1].split("=")[1])
                    targets[x_val] = y_val
                except:
                    pass
    else:
        pairs = value_str.split(", ")
        for pair in pairs:
            if "=" in pair:
                k, v = pair.split("=")
                targets[k.strip()] = float(v)
    return targets

def compare_coeffs(val_ref, val_target, tolerance):
    """Vérification avec tolérance flottante."""
    try:
        return abs(float(val_ref) - float(val_target)) <= tolerance
    except:
        return False


def create_correction_row(index):
    """Génère une carte de saisie masquée par défaut (Bootstrap/DCC)"""
    sline_rows = []
    for pt in range(5):
        sline_rows.append(html.Div(className="row g-1 mb-1 align-items-center", children=[
            html.Div(className="col-3", children=[
                dcc.Input(id={'type': 'curr-x', 'index': index, 'pt': pt}, disabled=True, className="form-control form-control-sm bg-light fw-bold text-center")
            ]), 
            html.Div(className="col-4", children=[
                dcc.Input(id={'type': 'curr-y', 'index': index, 'pt': pt}, disabled=True, className="form-control form-control-sm bg-light text-center")
            ]), 
            html.Div(className="col-5", children=[
                dcc.Input(id={'type': 'sline-val', 'index': index, 'pt': pt}, placeholder="New Y formula...", className="form-control form-control-sm") 
            ])
        ]))

    return html.Div(
        id={'type': 'card-visibility-wrapper', 'index': index},
        style={'display': 'none'}, 
        children=[
            html.Div(
                id={'type': 'card-wrapper', 'index': index},
                n_clicks=0,
                className="card shadow-sm mb-4 border-1",
                children=[
                    dcc.Store(id={'type': 'row-padaone-store', 'index': index}, data=None),
                    
                    html.Div(className="card-header d-flex justify-content-between align-items-center bg-white py-2", children=[
                        html.Span(f"PARAMETER REQUEST #{index + 1}", className="badge bg-primary text-uppercase"),
                        html.Button("Delete", id={'type': 'delete-btn', 'index': index}, className="btn btn-sm btn-outline-danger")
                    ]),
                    
                    html.Div(className="card-body", children=[
                        html.Div(className="row mb-3", children=[
                            html.Div(className="col-md-6", children=[
                                html.Label("Sabre Name", className="form-label small fw-bold"),
                                dcc.Input(id={'type': 'p-select', 'index': index}, placeholder="271RAID1--", className="form-control", debounce=True)
                            ]),
                            html.Div(className="col-md-6", children=[
                                html.Label("Correction Type", className="form-label small fw-bold"),
                                dcc.Dropdown(id={'type': 't-select', 'index': index}, options=[{"label":"Position","value":"pos"},{"label":"Load","value":"load"}], value="pos", clearable=False)
                            ]),
                        ]),
                        
                        html.Div(className="border rounded p-3 bg-light", children=[
                            html.Div(id={'type': 'load-wrapper', 'index': index}, style={'display': 'none'}, children=[
                                html.Label("Offset (FZ Value in daN)", className="form-label small fw-bold text-info"),
                                dcc.Input(id={'type': 'new-value-load', 'index': index}, placeholder="Ex: =-200-50", className="form-control w-50")
                            ]),
                            
                            html.Div(id={'type': 'pos-wrapper', 'index': index}, children=[
                                html.Div(className="mb-3", children=[
                                    dcc.RadioItems(id={'type': 'law-select', 'index': index}, options=[{"label": " LINEAR", "value": "LINEAR"}, {"label": " SLINE", "value": "SLINE"}], value="LINEAR", inline=True, inputClassName="me-1", labelClassName="me-3 small fw-bold"),
                                ]),
                                
                                html.Div(id={'type': 'linear-wrapper', 'index': index}, className="row", children=[
                                    html.Div(className="col-6 border-end", children=[
                                        html.P("Current Coefs", className="small text-muted mb-2 fw-bold text-center"),
                                        dcc.Input(id={'type': 'curr-a', 'index': index}, disabled=True, className="form-control form-control-sm bg-light mb-2 text-center"),
                                        dcc.Input(id={'type': 'curr-b', 'index': index}, disabled=True, className="form-control form-control-sm bg-light text-center")
                                    ]),
                                    html.Div(className="col-6", children=[
                                        html.P("New Target", className="small text-primary mb-2 fw-bold text-center"),
                                        dcc.Input(id={'type': 'new-value-a', 'index': index}, placeholder="New Coef A", className="form-control form-control-sm mb-2 text-center"),
                                        dcc.Input(id={'type': 'new-value-b', 'index': index}, placeholder="New Coef B", className="form-control form-control-sm text-center")
                                    ])
                                ]),
                                
                                html.Div(id={'type': 'sline-wrapper', 'index': index}, style={'display': 'none'}, children=[
                                    html.Div(className="row g-1 mb-1 text-center", children=[
                                        html.Div("X / Min Range", className="col-3 small fw-bold text-muted"),
                                        html.Div("Curr Y / Coef B", className="col-4 small fw-bold text-muted"),
                                        html.Div("New Y", className="col-5 small fw-bold text-primary")
                                    ]),
                                    html.Div(sline_rows)
                                ])
                            ])
                        ]),

                        html.Div(className="row mt-3 pt-3 border-top", children=[
                            html.Div(className="col-md-8", children=[
                                html.Label("Reason", className="form-label small fw-bold text-muted"),
                                dcc.Textarea(id={'type': 'j-input', 'index': index}, className="form-control", style={'height': '60px'})
                            ]),
                            html.Div(className="col-md-4", children=[
                                html.Label("Retrofit ID", className="form-label small fw-bold text-muted"),
                                dcc.Input(id={'type': 'r-input', 'index': index}, className="form-control")
                            ])
                        ])
                    ])
                ]
            )
        ]
    )

def retrofit_management_content():
    return html.Div([
        html.Div([
            html.H3("Retrofit Application Monitoring", className="mb-3"),
            html.Button("Check Retrofits Status", id="check-retrofit-btn", className="btn btn-primary mb-3", n_clicks=0),
            dcc.Loading(id="loading-retrofit", children=html.Div(id="retrofit-check-output"), type="circle"),
        ], className="p-3"),
        
        html.Div(id='retrofit-table-container', className="px-3")
    ])

def layout():
    return html.Div(className="container py-4", style={"maxWidth": "1450px"}, children=[
        dcc.Store(id="active-indices-store", data=[0]), 
        dcc.Store(id="active-card-index", data=0),
        html.H1("Parameter Coef Management", className="fw-bold mb-4 px-3"),
        dcc.Tabs(id="tabs-coef", value="correction", children=[
            dcc.Tab(label="1. Coef Consultation", value="correction", className="custom-tab", selected_className="custom-tab--selected"),
            dcc.Tab(label="2. Retrofit Management", value="retrofit_mgmt", className="custom-tab", selected_className="custom-tab--selected"),
        ]),
        html.Div(id="tabs-content-coef", className="mt-4")
    ])

@app.callback(
    Output("tabs-content-coef", "children"),
    Input("tabs-coef", "value")
)
def render_tab_content(tab_value):
    if tab_value == "correction":
        try:
            tableC = api.events.table(prefix="BD4EV", name=table_combined)
            msns_list = list(set(tableC.read_distinct(['aircraft'])['aircraft']))
            
            if "V0700" not in msns_list:
                msns_list.append("V0700")
                
            msns = sorted(msns_list)
        except Exception as e: 
            msns = sorted(["F6101", "V0059", "V0700"])

        return html.Div(className="row px-3", children=[
            html.Div(className="col-md-7", children=[
                html.Div(className="card shadow-sm p-3 mb-4 bg-white", children=[
                    html.Div(className="row align-items-end", children=[
                        html.Div(className="col-md-6", children=[
                            html.Label("Aircraft MSN", className="form-label fw-bold"),
                            dcc.Dropdown(id="manage-msn-drop", 
                                         options=[{"label": m, "value": m} for m in msns], 
                                         value=msns[0], clearable=False)
                        ]),
                        html.Div(className="col-md-6 text-end", children=[
                            html.Button("+ Add Parameter", id="add-item-btn", className="btn btn-outline-primary")
                        ])
                    ])
                ]),
                html.Div(id="corrections-list", children=[create_correction_row(i) for i in range(MAX_PARAMS)]),
            ]),
            
            html.Div(className="col-md-5", children=[
                html.Div(className="card shadow-sm sticky-top", style={"top": "20px"}, children=[
                    html.Div(className="card-header bg-dark text-white fw-bold", children="Calibration History (Padaone)"),
                    html.Div(className="card-body overflow-auto", style={"height": "75vh"}, children=[
                        dcc.Loading(html.Div(id="padaone-history-display"))
                    ])
                ])
            ])
        ])
    
    elif tab_value == "retrofit_mgmt":
        return retrofit_management_content()
    
    return html.Div("Tab not found.")

@app.callback(
    Output("active-indices-store", "data"),
    [Input("add-item-btn", "n_clicks"), Input({'type': 'delete-btn', 'index': ALL}, 'n_clicks')],
    State("active-indices-store", "data"),
    prevent_initial_call=True
)
def update_indices(n_add, n_deletes, current_indices):
    ctx = callback_context
    trig_id = ctx.triggered[0]['prop_id']
    if "add-item-btn" in trig_id:
        for i in range(MAX_PARAMS):
            if i not in current_indices:
                current_indices.append(i)
                break
        return sorted(current_indices)
    elif "delete-btn" in trig_id:
        idx = json.loads(trig_id.split(".")[0])['index']
        if idx in current_indices: 
            current_indices.remove(idx)
        return sorted(current_indices)
    return no_update

@app.callback(
    Output({'type': 'card-visibility-wrapper', 'index': ALL}, 'style'),
    Input("active-indices-store", "data")
)
def refresh_visibility(active_list):
    return [{'display': 'block' if i in active_list else 'none'} for i in range(MAX_PARAMS)]

@app.callback(
    Output('active-card-index', 'data'),
    [Input({'type': 'p-select', 'index': ALL}, 'value'),
     Input({'type': 'j-input', 'index': ALL}, 'value'),
     Input({'type': 'r-input', 'index': ALL}, 'value'),
     Input('manage-msn-drop', 'value')],
    prevent_initial_call=True
)
def handle_focus(*args):
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    
    trig_prop = ctx.triggered[0]['prop_id']
    trig_id_raw = trig_prop.split(".")[0]
    
    if trig_id_raw.startswith('{'):
        try:
            trig_info = json.loads(trig_id_raw)
            return trig_info['index']
        except:
            return no_update
    return no_update

@app.callback(
    Output({'type': 'row-padaone-store', 'index': ALL}, 'data'),
    [Input({'type': 'p-select', 'index': ALL}, 'value'),
     Input('manage-msn-drop', 'value'),
     Input('tabs-coef', 'value')],
    [State({'type': 'row-padaone-store', 'index': ALL}, 'data')],
    prevent_initial_call=True
)
def fetch_padaone_unified(p_values, selected_msn, active_tab, current_stores):
    from dash import callback_context, no_update
    ctx = callback_context
    
    if not p_values:
        return []

    do_nothing = [no_update] * len(p_values)

    if not ctx.triggered or active_tab != 'correction':
        return do_nothing

    if not current_stores or len(current_stores) != len(p_values):
        current_stores = [{}] * len(p_values)

    new_stores = []
    has_changes = False

    for i, param_id in enumerate(p_values):
        curr_store = current_stores[i] or {}

        if not param_id or len(str(param_id)) < 4:
            new_stores.append(curr_store)
            continue

        if curr_store.get('param') == param_id and curr_store.get('msn') == selected_msn:
            new_stores.append(curr_store)
        else:
            updated_store = execute_padaone_fetch(param_id, selected_msn)
            new_stores.append(updated_store)
            has_changes = True

    if has_changes:
        return new_stores
    
    return do_nothing

def execute_padaone_fetch(param_id, selected_msn):
    try:
        clean_msn = get_msn_number(selected_msn)
        
        start_str = "2000-01-01T00:00:00.000Z"
        end_str = "2030-12-31T23:59:59.000Z"

        df_history = api.padaone.get_calibration_history(
            ac_type=check_ac_type(selected_msn), 
            msn=clean_msn, 
            param_id=param_id.upper().strip(),
            start_gmt=start_str, 
            end_gmt=end_str
        )
        
        if df_history is None or df_history.empty:
            return {"param": param_id, "msn": selected_msn, "error": "No history found in Padaone."}
        
        df_history['Start Date'] = df_history['Start Date'].astype(str)
        return {"param": param_id, "msn": selected_msn, "history": df_history.to_dict('records')}
    except Exception as e:
        return {"param": param_id, "msn": selected_msn, "error": f"API Error: {str(e)}"}

@app.callback(
    Output('padaone-history-display', 'children'),
    [Input('active-card-index', 'data'),
     Input({'type': 'row-padaone-store', 'index': ALL}, 'data')],
    [State({'type': 'row-padaone-store', 'index': ALL}, 'id')],
    prevent_initial_call=False
)
def display_active_history(active_idx, all_stores, store_ids):
    active_data = next((d for d, i in zip(all_stores, store_ids) if i['index'] == active_idx), None)
    
    if not active_data:
        return html.Div("Enter a parameter name.", className="text-muted text-center mt-5")

    if "error" in active_data:
        return html.Div([
            html.H5("⚠️ Data Fetch Error", className="text-danger mb-3"),
            html.P(f"Parameter: {active_data.get('param', 'Unknown')}", className="fw-bold"),
            html.Div(active_data["error"], className="p-2 bg-light border text-danger font-monospace")
        ], className="p-3")

    if "history" not in active_data:
        return html.Div("Enter a parameter name.", className="text-muted text-center mt-5")
    
    df = pd.DataFrame(active_data['history'])
    table_rows = []
    
    for start_date, group in df.groupby('Start Date', sort=False):
        group = group.sort_values('Min Range')
        law = group['Calibration Law'].iloc[0]
        
        knots = []
        if law == 'LINEAR':
            knots.append({"x": "Offset B", "y": group['Coef B'].iloc[0]})
            knots.append({"x": "Slope A", "y": group['Coef A'].iloc[0]})
        else:
            for _, row in group.iterrows():
                x = float(row['Min Range'])
                y = (float(row['Coef A']) * x) + float(row['Coef B'])
                knots.append({"x": int(x), "y": y})
            
            last_row = group.iloc[-1]
            x_last = float(last_row['Max Range'])
            y_last = (float(last_row['Coef A']) * x_last) + float(last_row['Coef B'])
            knots.append({"x": int(x_last), "y": y_last})

        for i, knot in enumerate(knots):
            cells = []
            if i == 0:
                cells.append(html.Td(str(start_date)[:16].replace('T', ' '), rowSpan=len(knots), className="small border-end align-middle"))
                cells.append(html.Td(law, rowSpan=len(knots), className="small fw-bold border-end align-middle text-center"))
            
            cells.append(html.Td(str(knot['x']), className="ps-3 font-monospace", style={'width': '100px'}))
            if knot['x'] == "Slope A":
                formatted_y = safe_float_format(knot['y'], precision=5)
            else:
                formatted_y = safe_float_format(knot['y'])
                
            cells.append(html.Td(formatted_y, className="text-end font-monospace pe-3"))
            table_rows.append(html.Tr(cells, className="border-bottom" if i == len(knots)-1 else ""))
    
    return html.Div([
        html.H5(f"Parameter: {active_data['param']}", className="mb-3 text-primary px-2"),
        html.Table(className="table table-sm table-hover border-top", children=[
            html.Thead(html.Tr([
                html.Th("Date (GMT)"), html.Th("Law"), html.Th("X (Raw)"), html.Th("Y (Value)")
            ])),
            html.Tbody(table_rows)
        ])
    ])

def parse_targets(val_str):
    targets = {}
    if "x0=" in val_str:
        for seg in val_str.split(" ; "):
            pts = dict(item.split("=") for item in seg.split(", "))
            targets[float(pts['x0'])] = float(pts['y0']) 
    else:
        for item in val_str.split(", "):
            k, v = item.split("=")
            targets[k.strip()] = float(v)
    return targets

@app.callback(
    [Output('retrofit-table-container', 'children'),
     Output('retrofit-check-output', 'children')],
    [Input('tabs-coef', 'value'),
     Input('check-retrofit-btn', 'n_clicks')],
    prevent_initial_call=False
)
def manage_retrofit_logic(active_tab, n_clicks):
    if active_tab != 'retrofit_mgmt':
        return no_update, no_update

    ctx = dash.callback_context
    is_check_clicked = ctx.triggered and 'check-retrofit-btn' in ctx.triggered[0]['prop_id']

    data = github_get_file("corrections_db.json") 
    if not data:
        return html.Div("No data found.", className="alert alert-warning"), ""

    table_rows = []
    has_updates = False

    header = html.Div(className="row fw-bold bg-light p-3 border-bottom shadow-sm m-0 align-items-center", children=[
        html.Div("MSN", className="col-1"),
        html.Div("Parameter", className="col-2"),
        html.Div("Target Values", className="col-3"),
        html.Div("Retrofit ID", className="col-2"),
        html.Div("Status", className="col-2"),
        html.Div("Actions", className="col-2 text-end"),
    ])

    for absolute_idx, entry in enumerate(data):
        retrofit_id = str(entry.get('retrofit', '')).strip()
        if not retrofit_id or retrofit_id.upper() in ['NONE', 'N/A']:
            continue

        status = entry.get('status', 'In progress')
        
        if status == 'Validated':
            continue

        msn, param, target_str = entry.get('msn', 'N/A'), entry.get('param', '-'), entry.get('value', '-')
        test_details_ui = []

        if is_check_clicked:
            try:
                ac_type = check_ac_type(msn)
                clean_msn = get_msn_number(msn)
                t_type = letter2testtype.get(retrofit_id[0], 'STATIC')
                
                r_dates = api.onesearch.get_test_dates(ac_type, clean_msn, t_type, retrofit_id[1:])
                retro_date = pd.to_datetime(r_dates[0], utc=True) if r_dates else pd.to_datetime("2000-01-01T00:00:00Z", utc=True)

                all_tests = pd.DataFrame(api.events.table(prefix="BD4EV", name=table_combined).read(aircraft=msn))
                sub_tests = pd.DataFrame()
                if not all_tests.empty:
                    all_tests['isoStart'] = pd.to_datetime(all_tests['isoStart'], utc=True, errors='coerce')
                    sub_tests = all_tests[all_tests['isoStart'] >= retro_date].sort_values('isoStart').drop_duplicates(subset=['test'])

                pada_hist = api.padaone.get_calibration_history(ac_type, clean_msn, param.upper().strip(), "2000-01-01T00:00:00.000Z", "2030-12-31T23:59:59.000Z")
                
                if pada_hist is not None and not pada_hist.empty:
                    pada_hist['Start Date'] = pd.to_datetime(pada_hist['Start Date'], utc=True)
                    targets = parse_target_values(target_str)
                    
                    has_flights = not sub_tests.empty
                    all_flights_match = True if has_flights else False

                    for _, t_row in sub_tests.iterrows():
                        t_name, t_date = t_row['test'], t_row['isoStart']
                        active_hist = pada_hist[pada_hist['Start Date'] <= t_date]
                        
                        match = False
                        applied_str = "No history"
                        is_manual_check = False

                        if not active_hist.empty:
                            cur_group = pada_hist[pada_hist['Start Date'] == active_hist.iloc[-1]['Start Date']]
                            law = cur_group['Calibration Law'].iloc[0]
                            match = True 

                            if law == 'LINEAR':
                                a, b = float(cur_group['Coef A'].iloc[0]), float(cur_group['Coef B'].iloc[0])
                                applied_str = f"A={a}, B={b:.4f}"
                                if not (compare_coeffs(targets.get('A'), a, 0.0001) and compare_coeffs(targets.get('B'), b, 1.0)):
                                    match = False
                            else:
                                is_manual_check = not any(isinstance(k, float) for k in targets.keys())
                                
                                parts = []
                                for _, h in cur_group.iterrows():
                                    x_val = float(h['Min Range'])
                                    y_val = (float(h['Coef A']) * x_val) + float(h['Coef B'])
                                    parts.append(f"Y({x_val:.0f})={y_val:.2f}")
                                
                                if not cur_group.empty:
                                    last_row = cur_group.iloc[-1]
                                    x_last = float(last_row['Max Range'])
                                    y_last = (float(last_row['Coef A']) * x_last) + float(last_row['Coef B'])
                                    parts.append(f"Y({x_last:.0f})={y_last:.2f}")
                                    
                                applied_str = " ; ".join(parts) 
                                
                                if not is_manual_check:
                                    for tx, ty in targets.items():
                                        found = cur_group[abs(cur_group['Min Range'] - tx) < 1.0]
                                        if found.empty or not compare_coeffs(ty, (found.iloc[0]['Coef A']*tx + found.iloc[0]['Coef B']), 1.0):
                                            match = False; break
                        
                        if not match or is_manual_check:
                            all_flights_match = False

                        icon, color = (("✅", "text-success") if match else ("❌", "text-danger")) if not is_manual_check else ("🔍", "text-warning")
                        test_details_ui.append(html.Div([
                            html.Span(f"Test {t_name} ({t_date.strftime('%Y-%m-%d')}) ➔ "),
                            html.Span(f"{applied_str} {icon}", className=f"fw-bold {color}")
                        ], className="small mb-2 ms-4 border-start border-3 border-info ps-2"))
                    
                    new_status = "Done" if all_flights_match else "In progress"
                    if status != new_status:
                        entry['status'] = new_status
                        status = new_status
                        has_updates = True

            except Exception as e:
                test_details_ui.append(html.Div(f"Error: {e}", className="small text-danger ms-4"))
        
        if not test_details_ui:
            msg = "Confirmed ✅ (Click Check to refresh)" if status == "Done" else "Click 'Check' to fetch flight history."
            test_details_ui = [html.Div(msg, className="small text-muted fst-italic ms-4")]

        summary = html.Summary(className=f"row align-items-center p-3 {'bg-success bg-opacity-10' if status == 'Done' else 'bg-white'} border-bottom m-0",
            children=[
                html.Div(msn, className="col-1 fw-bold"), 
                html.Div(param, className="col-2"),
                html.Div(className="col-3", children=[
                    dcc.Input(id={'type': 'retro-val-input', 'index': absolute_idx}, value=target_str, className="form-control form-control-sm font-monospace")
                ]), 
                html.Div(retrofit_id, className="col-2 text-primary fw-bold"),
                html.Div(html.Span(status, className=f"badge {'bg-success' if status == 'Done' else 'bg-warning text-dark'}"), className="col-2"),
                html.Div(className="col-2 text-end", children=[
                    html.Button("💾 Save", id={'type': 'retro-save-btn', 'index': absolute_idx}, className="btn btn-sm btn-light border me-1", title="Sauvegarder la nouvelle valeur"),
                    html.Button("✅ Validated", id={'type': 'retro-valid-btn', 'index': absolute_idx}, className="btn btn-sm btn-light border", title="Valider et archiver le retrofit")
                ])
            ])
        table_rows.append(html.Details(children=[summary, html.Div(children=test_details_ui, className="p-3 bg-light")], className="w-100"))

    if has_updates:
        github_update_file("corrections_db.json", data, "Update retrofit status (All-Match logic)")

    return html.Div(className="border shadow-sm rounded bg-white mt-3", children=[header] + table_rows), f"Last check: {time.strftime('%H:%M:%S')}"

@app.callback(
    [Output({'type': 'load-wrapper', 'index': MATCH}, 'style'),
     Output({'type': 'pos-wrapper', 'index': MATCH}, 'style'),
     Output({'type': 'linear-wrapper', 'index': MATCH}, 'style'),
     Output({'type': 'sline-wrapper', 'index': MATCH}, 'style'),
     Output({'type': 'curr-a', 'index': MATCH}, 'value'),
     Output({'type': 'curr-b', 'index': MATCH}, 'value'),
     Output({'type': 'law-select', 'index': MATCH}, 'value'),
     Output({'type': 'curr-x', 'index': MATCH, 'pt': ALL}, 'value'),
     Output({'type': 'curr-y', 'index': MATCH, 'pt': ALL}, 'value'),
     Output({'type': 'curr-x', 'index': MATCH, 'pt': ALL}, 'disabled'),
     Output({'type': 'curr-x', 'index': MATCH, 'pt': ALL}, 'className')],
    [Input({'type': 't-select', 'index': MATCH}, 'value'),
     Input({'type': 'law-select', 'index': MATCH}, 'value'),
     Input({'type': 'row-padaone-store', 'index': MATCH}, 'data')],
    [State({'type': 'curr-a', 'index': MATCH}, 'value'),
     State({'type': 'curr-b', 'index': MATCH}, 'value'),
     State({'type': 'curr-x', 'index': MATCH, 'pt': ALL}, 'value'),
     State({'type': 'curr-y', 'index': MATCH, 'pt': ALL}, 'value')],
    prevent_initial_call=True
)
def sync_card(t_type, user_law, pada_data, curr_a, curr_b, curr_x, curr_y):
    from dash import callback_context, no_update
    ctx = callback_context
    triggered_id = ctx.triggered[0]['prop_id'] if ctx.triggered else ""
    is_new_padaone = 'row-padaone-store' in triggered_id

    a, b = curr_a, curr_b
    x_vals = curr_x if curr_x else [""]*5
    y_vals = curr_y if curr_y else [""]*5
    history_law = "LINEAR"
    
    if pada_data and 'history' in pada_data:
        df_hist = pd.DataFrame(pada_data['history'])
        latest_date = df_hist['Start Date'].max()
        pts = df_hist[df_hist['Start Date'] == latest_date].sort_values('Min Range').to_dict('records')
        
        history_law = pts[0].get('Calibration Law', 'LINEAR')
        
        if is_new_padaone:
            if history_law == 'LINEAR':
                raw_a = pts[0].get('Coef A')
                a = str(raw_a) if raw_a is not None else ""
                b = safe_float_format(pts[0].get('Coef B'))
                x_vals, y_vals = [""]*5, [""]*5
            else:
                for i, p in enumerate(pts[:4]): 
                    x_val = float(p.get('Min Range', 0))
                    y_val = (float(p.get('Coef A', 0)) * x_val) + float(p.get('Coef B', 0))
                    x_vals[i] = safe_float_format(x_val)
                    y_vals[i] = safe_float_format(y_val)
                
                last_p = pts[-1]
                x_last = float(last_p.get('Max Range', 65535))
                y_last = (float(last_p.get('Coef A', 0)) * x_last) + float(last_p.get('Coef B', 0))
                x_vals[4] = safe_float_format(x_last)
                y_vals[4] = safe_float_format(y_last)

    final_law = history_law if is_new_padaone else user_law

    is_x_editable = (final_law == 'SLINE')
    disabled_x = [not is_x_editable] * 5
    
    base_class = "form-control form-control-sm fw-bold text-center"
    class_x = [base_class if is_x_editable else f"{base_class} bg-light" for _ in range(5)]

    return ({'display': 'block' if t_type == 'load' else 'none'},
            {'display': 'block' if t_type == 'pos' else 'none'},
            {'display': 'flex' if final_law == 'LINEAR' else 'none'},
            {'display': 'block' if final_law == 'SLINE' else 'none'},
            a if is_new_padaone else no_update, 
            b if is_new_padaone else no_update, 
            final_law, 
            x_vals if is_new_padaone else [no_update] * 5, 
            y_vals if is_new_padaone else [no_update] * 5, 
            disabled_x, class_x)

@app.callback(
    Output('check-retrofit-btn', 'n_clicks'),
    [Input({'type': 'retro-save-btn', 'index': ALL}, 'n_clicks'),
     Input({'type': 'retro-valid-btn', 'index': ALL}, 'n_clicks')],
    [State({'type': 'retro-val-input', 'index': ALL}, 'value'),
     State({'type': 'retro-save-btn', 'index': ALL}, 'id'),
     State('check-retrofit-btn', 'n_clicks')],
    prevent_initial_call=True
)
def handle_retrofit_actions(save_clicks, valid_clicks, input_values, save_ids, current_check_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update
    
    trigger_id_str = ctx.triggered[0]['prop_id'].split('.')[0]
    try:
        trigger_info = json.loads(trigger_id_str)
        target_idx = trigger_info['index']
        action_type = trigger_info['type']
    except:
        return no_update
        
    if ctx.triggered[0]['value'] is None or ctx.triggered[0]['value'] == 0:
        return no_update

    data = github_get_file("corrections_db.json")
    if not data or target_idx >= len(data):
        return no_update

    target_entry = data[target_idx]
    target_msn = target_entry.get('msn')
    target_param = target_entry.get('param')

    if action_type == 'retro-save-btn':
        val_to_save = ""
        for ident, val in zip(save_ids, input_values):
            if ident['index'] == target_idx:
                val_to_save = val
                break
        target_entry['value'] = val_to_save
        github_update_file("corrections_db.json", data, f"Update target value for {target_param}")
        
    elif action_type == 'retro-valid-btn':
        target_entry['status'] = 'Validated'
        target_entry['application_date'] = time.strftime("%d/%m/%Y")
        github_update_file("corrections_db.json", data, f"Validate retrofit for {target_param}")
        
    try:
        df_gsheet = load_dataframe_from_airbus_api(TARGET_SPREADSHEET_ID, "Corrections!A1:H5000")
        
        if df_gsheet is not None and not df_gsheet.empty:
            df_gsheet_clean = df_gsheet.copy()
            df_gsheet_clean['MSN'] = df_gsheet_clean['MSN'].astype(str).str.strip()
            df_gsheet_clean['Parameter'] = df_gsheet_clean['Parameter'].astype(str).str.strip()
            
            mask = (df_gsheet_clean['MSN'] == str(target_msn).strip()) & (df_gsheet_clean['Parameter'] == str(target_param).strip())
            
            if mask.any():
                if action_type == 'retro-save-btn':
                    df_gsheet_clean.loc[mask, 'Correction value'] = val_to_save
                elif action_type == 'retro-valid-btn':
                    df_gsheet_clean.loc[mask, 'Statut'] = 'OK' 
                    df_gsheet_clean.loc[mask, 'Application date'] = time.strftime("%d/%m/%Y") 
                
                df_final_to_send = df_gsheet_clean.fillna('').astype(str)
                update_spreadsheets_values_airbus_api(TARGET_SPREADSHEET_ID, "Corrections", df_final_to_send)
    except Exception as e:
        print(f"ERREUR Synchro GSheet Retrofit : {e}")
        
    return (current_check_clicks or 0) + 1
