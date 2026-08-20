import dash
import dash_bootstrap_components as dbc

# 1. Création de l'application avec le thème Bootstrap
app = dash.Dash(__name__, suppress_callback_exceptions=True, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

# 2. Import de l'interface
from coef_management import layout

# 3. Assignation
app.layout = layout()

if __name__ == '__main__':
    # Remplacé par app.run avec le host pour autoriser TSAS à se connecter
    app.run(host='0.0.0.0', port=8050, debug=False)
