import datetime
from collections import defaultdict
import json
from stellar_sdk import Server
from stellar_config import server  # seu objeto Server configurado

# Configurações para limite de taxa de transações
RATE_LIMIT_SECONDS = 60  # Tempo em segundos
RATE_LIMIT_COUNT = 10    # Número máximo de transações dentro do período

transaction_history = defaultdict(lambda: [])

# Contas restritas de exemplo
RESTRICTED_ACCOUNTS = {
    "GA...",  # Conta restrita 1
    "GB..."   # Conta restrita 2
}

def log_alert(alert_type: str, details: dict):
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "alert_type": alert_type,
        "details": details
    }
    print(f"ALERTA: {json.dumps(log_entry, indent=2)}")

# Conta que você quer monitorar
account_id = "GCJVARGX3OWX2HF6J7YXUELAL55SZ3UNTPJQRMMYQRIKRJGI46GIE7WR"

print(f"Monitoring transactions for account: {account_id}...")

# Loop de monitoramento usando stream
for response in server.transactions().for_account(account_id).stream():
    tx_hash = response["id"]
    print(f"Nova transação detectada: {tx_hash}")

    # Pega todas as operações dessa transação
    operations = server.operations().for_transaction(tx_hash).call()["_embedded"]["records"]

    for op in operations:
        if op["type"] == "payment":
            amount = float(op["amount"])
            from_addr = op["from"]
            to_addr = op["to"]

            # Alerta se a conta de origem ou destino está na lista restrita
            if from_addr in RESTRICTED_ACCOUNTS or to_addr in RESTRICTED_ACCOUNTS:
                log_alert("RESTRICTED_ACCOUNT_TRANSACTION", {
                    "from": from_addr,
                    "to": to_addr,
                    "amount": amount,
                    "tx_hash": tx_hash
                })

            # Alerta se valor maior que 10000 tokens
            if amount > 10000:
                log_alert("HIGH_VALUE_TRANSACTION", {
                    "from": from_addr,
                    "to": to_addr,
                    "amount": amount,
                    "tx_hash": tx_hash
                })

            # Limite de taxa de transações
            now = datetime.datetime.now()
            transaction_history[from_addr].append(now)

            # Remove timestamps antigos
            transaction_history[from_addr] = [
                t for t in transaction_history[from_addr]
                if (now - t).total_seconds() < RATE_LIMIT_SECONDS
            ]

            if len(transaction_history[from_addr]) > RATE_LIMIT_COUNT:
                log_alert("RATE_LIMIT_EXCEEDED", {
                    "from": from_addr,
                    "count": len(transaction_history[from_addr]),
                    "time_period": RATE_LIMIT_SECONDS,
                    "tx_hash": tx_hash
                })
            else:
                print(f"Transação: {amount} tokens de {from_addr} para {to_addr}")
