from stellar_sdk import Network, Server

# Configuração Stellar
STELLAR_NETWORK = Network.TESTNET_NETWORK_PASSPHRASE
HORIZON_URL = "https://horizon-testnet.stellar.org"
server = Server(HORIZON_URL)