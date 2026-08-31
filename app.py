def conectar_google_sheets():
    """Autentica de forma segura decodificando correctamente los saltos de clave privada."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ No se encontró la configuración de `gcp_service_account` en los secretos de Streamlit.")
            return None
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Extraer credenciales y asegurar formato correcto de la llave privada
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        if "private_key" in creds_dict:
            # Reemplazar literales '\\n' por saltos de línea reales de manera estricta
            pk = creds_dict["private_key"]
            pk = pk.replace("\\n", "\n")
            creds_dict["private_key"] = pk
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        cliente = gspread.authorize(creds)
        return cliente
    except Exception as e:
        st.error(f"❌ Error al autenticar con las credenciales de Google: {e}")
        return None
