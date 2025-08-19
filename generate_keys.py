import streamlit_authenticator as stauth

# Lista de contraseñas en texto plano que quieres hashear
passwords = ["12345", "secret"]  # Cambia estas por las contraseñas reales

# Crea una instancia del Hasher
hasher = stauth.Hasher()

# Pasa la lista de contraseñas al método generate
hashed_passwords = hasher.generate(passwords)

print(hashed_passwords)
