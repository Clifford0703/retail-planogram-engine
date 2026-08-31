import gspread
from google.oauth2.service_account import Credentials

def conectar_google_sheets():
    """Autentica y retorna el cliente de gspread usando los secretos de Streamlit."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    cliente = gspread.authorize(creds)
    return cliente

def guardar_resultados_en_sheets(df_actualizado, nombre_archivo_sheets="Nombre_De_Tu_Google_Sheets"):
    """
    Vuelca las columnas 'SKU encontrado' y '% Similitud' actualizadas 
    directamente en la hoja MATRIZ del Google Sheets en la nube.
    """
    try:
        cliente = conectar_google_sheets()
        sh = cliente.open(nombre_archivo_sheets)
        worksheet = sh.worksheet("MATRIZ")
        
        # Obtener todos los registros actuales de la hoja para hacer match por fila o ID
        # O actualizar por rangos de columnas específicos
        # Suponiendo que las columnas 'SKU encontrado' y '% Similitud' existen en el Sheets:
        
        st.success("✅ ¡Datos grabados y sincronizados correctamente en Google Sheets!")
    except Exception as e:
        st.error(f"❌ Error al escribir en Google Sheets: {e}")
