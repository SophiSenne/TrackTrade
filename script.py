import requests
from stellar_sdk import Keypair

# ===== ATENÇÃO =====
# Substitua abaixo pela sua seed secreta (NÃO compartilhe com ninguém!)
SECRET_SEED = "SBEWRYHINR67NAOIOBHSCMYX5AODNCBZH2BI2CDHFOH6LG46346O5WQU"

# Deriva a chave pública (G...)
kp = Keypair.from_secret(SECRET_SEED)
public_key = kp.public_key
print(f"Chave pública derivada: {public_key}")

# Monta a URL do Friendbot
url = f"https://friendbot.stellar.org?addr={public_key}"
print(f"Chamando Friendbot: {url}")

# Faz a requisição
response = requests.get(url)

# Mostra o resultado
if response.status_code == 200:
    print("Conta financiada com sucesso na testnet!")
    print(response.json())
else:
    print("Erro ao chamar Friendbot:", response.status_code, response.text)

