def conectar_google_sheets():
    """Autentica de forma segura usando los secretos de Streamlit."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ No se encontró la configuración de `gcp_service_account` en los secretos.")
            return None
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Copiamos los secretos y normalizamos los saltos de línea de la clave privada por seguridad
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        cliente = gspread.authorize(creds)
        return cliente
    except Exception as e:
        st.error(f"❌ Error al autenticar con las credenciales de Google: {e}")
        return None
