def conectar_google_sheets():
    """Autentica de forma segura limpiando los saltos de la clave privada."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ No se encontró la configuración de `gcp_service_account` en los secretos.")
            return None
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Convertimos los secretos a diccionario de forma limpia
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # Asegurar formato PEM correcto de la llave privada
        if "private_key" in creds_dict:
            pk = creds_dict["private_key"]
            # Limpiamos posibles espacios o comillas extra que añada TOML
            pk = pk.strip()
            if not pk.startswith("-----BEGIN PRIVATE KEY-----"):
                pk = "-----BEGIN PRIVATE KEY-----\n" + pk
            if not pk.endswith("-----END PRIVATE KEY-----"):
                pk = pk + "\n-----END PRIVATE KEY-----"
            creds_dict["private_key"] = pk
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        cliente = gspread.authorize(creds)
        return cliente
    except Exception as e:
        st.error(f"❌ Error al autenticar con Google: {e}")
        return None
