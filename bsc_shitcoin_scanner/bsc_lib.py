from web3 import Web3
import requests as requests
import json
from eth_abi import decode_abi

class bscScanner:
    def __init__(self, api_key, http_provider):
        self.api_key = api_key
        self.w3 = Web3(Web3.HTTPProvider(http_provider))


    def get_res(self,url):
        res=requests.get(url)
        res=json.loads(res.text)["result"]
        return res

    def get_tokentxs(self,address,sort,start,end):
        #restituisce una lista con le transazioni a partire dalla prima considera le transazioni dopo un certo periodo a partire dalla prima
        TotRes=[]
        
        res=requests.get(f'https://api.bscscan.com/api?module=account&action=tokentx&address={address}&startblock={start}&endblock={end}&sort={sort}&apikey={self.api_key}')
        res=json.loads(res.text)
        res=res['result']
        
        last_block=None
        if len(res)==10000:
            last_block=res[-1]["blockNumber"]
        return res, last_block

    def get_abi(self,address):
        url = f"https://api.bscscan.com/api?module=contract&action=getabi&address={address}&apikey={self.api_key}"
        res=self.get_res(url)
        abi=json.loads(res)
        return abi

    def create_contract(self,address):
        abi=self.get_abi(address)
        contract = self.w3.eth.contract(address=self.w3.toChecksumAddress(address), abi=abi)
        return contract

    def get_tokens_values(self,contract,data):
        amount0In,amount1In,amount0Out,amount1Out=data
        if amount0In!=0:
            t0=amount0In
            t1=-amount1Out
        else:
            t0=-amount0Out
            t1=amount1In

        token0=contract.functions.token0().call()
        token1=contract.functions.token1().call()
        decimals0=contract.functions.decimals().call()
        decimals1=contract.functions.decimals().call()
        symbol0=contract.functions.symbol().call()
        symbol1=contract.functions.symbol().call()
        if token0=="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c":
            return t0/10**18, t1/10**decimals1, symbol1, token1
        if token1=="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c":
            return t1/10**18, t0/10**decimals0, symbol0, token0
        return None

    def swaps_from_hash(self,tx_hash,max_logs=None):
        #prendo i log della transazione
        transaction_receipt = self.w3.eth.getTransactionReceipt(tx_hash)
        logs=transaction_receipt["logs"]
        trades=[]
        warning=None
        print("     %s logs"%len(logs))
        
        if max_logs==None:
            too_many_logs=False
        else:
            too_many_logs=len(logs)>max_logs

        if not too_many_logs:
            for log in logs:
                    #cerco i log che corrispondono ad uno swap
                    topic0=self.w3.toHex(log["topics"][0])
                    if topic0=="0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822":
                        pair_address=log["address"]
                        #ricreo il contratto e decodifico i dati dello swap
                        pair_contract=self.create_contract(pair_address)
                        decoded_data = decode_abi(['uint256', 'uint256', 'uint256','uint256'], bytes.fromhex(log["data"][2:]))
                        #estraggo la quantit' ricevuti o ceduti
                        wbnb_val,shit_val,shit_symbol,shit_token=self.get_tokens_values(pair_contract,decoded_data)
                        if wbnb_val!=None:
                            trades.append({"wbnb_val":wbnb_val,"shit_val":shit_val,"shit_symbol":shit_symbol,"shit_token":shit_token,"pair":pair_address,"block":log["blockNumber"]})    
        else:
            warning="too many logs"
        return trades,warning

    def estimate_block_number(self,days_ago):
        average_block_time_seconds = 3 
        seconds_per_day = 86400
        blocks_per_day = seconds_per_day / average_block_time_seconds
        blocks_ago = int(days_ago * blocks_per_day)
        current_block_number = self.w3.eth.block_number
        return current_block_number - blocks_ago 

class bscTrading:
    def __init__(self,my_wallet,copy_wallet, api_key, http_provider):
        self.api_key = api_key
        self.w3 = Web3(Web3.HTTPProvider(http_provider))
        self.my_wallet=my_wallet
        self.copy_wallet=copy_wallet
        self.routerV2="0x10ED43C718714eb63d5aA57B78B54704E256024E"

    def copy(self):
        print(f"Listening for swaps by {self.copy_wallet}")
        block_filter = self.eth.filter({'fromBlock': 'latest', 'address': self.routerV2, 'topics':["0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",self.copy_wallet]})
       