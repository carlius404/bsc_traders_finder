from web3 import Web3
from web3.middleware import geth_poa_middleware
import requests as requests
import json
import matplotlib.pyplot as plt
from eth_abi import decode_abi
import time
import random
from dotenv import load_dotenv
import os
from bsc_lib import bscScanner
load_dotenv()

api_key=os.getenv('BSC_API_KEY')
http_provider='https://bsc-dataseed.binance.org/'
BS=bscScanner(api_key,http_provider)
w3 = Web3(Web3.HTTPProvider(http_provider))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)


def get_stats(capital,gains,trades_by_pair):
    #biggest drawdow,sharpe ratio,%gain, %avg position, avg numer of trades per token
    #%win

    wins=len([x for x in gains if x > 0]) #numero di trade con profitto
    perc_gains=[]
    n_trades=[]
    for token in trades_by_pair:
        n_trades.append(len(trades_by_pair[token])) #numero di trade fatti su quel token
        trades=trades_by_pair[token]["values"]
        investment=sum([x for x in trades if x < 0]) #totale di wbnb investiti nel token
        gain=sum([x for x in trades if x > 0]) #totale di wbnb guadagnati vendendo il token
        if investment>0:
            perc_gains.append((gain/investment)-1) #guadagno percentuale tradando il token
    avg_ntrades_per_token=0
    avg_perc_gain=0
    if len(perc_gains)>0:
        avg_perc_gain=sum(perc_gains)/len(perc_gains) #guadagno percentuale medio
    if len(n_trades)>0:
        avg_ntrades_per_token=sum(n_trades)/len(n_trades) #numero medio di trade fatti su un token

    return {"capital":capital, "perc_gains":perc_gains, "%wins":wins/len(gains), 
            "avg_perc_gain":avg_perc_gain,"avg_ntrades_per_token":avg_ntrades_per_token}

def get_address_trades(address,start,min_txs):
    #prendo le transazioni fatte dal wallet che volevo analizzare
    txs,_=BS.get_tokentxs(address,"asc",start,"latest")
    
    if len(txs)<min_txs:
        return None,None,None
    gains=[0] #contiene i guadagni dei trade, per trade considero l-insieme di tutte le volte che si compra o vende lo stesso token. 
              #sommando le perdite e i guadagni comprando o vendendo quel token si ottiene un elemento della lista "gains"
    capital=[0] #l'andamento di ogni buy e sell (non solo del guadagno/perdita efffettiva per trade)
    trades_by_pair={} #dizionario con chiave il pair e come valore tutti i buy e sell relativi al token
    ntxs=len(txs)
    if len(txs)>500:
        txs=txs[:500]
    warnings=[]
    #ora voglio trovare gli swap effettuati nelle nuove transazioni e aggiornare le liste gains,capital e il dizionario trades_by_gain
    i=0
    done_txs=[]
    for tx in txs:
        tx_hash=tx["hash"]
        print("     %s %s tx of %s"%(tx_hash,i,ntxs))
        i+=1
        if tx_hash not in done_txs:
            done_txs.append(tx_hash)
            trades,warning=BS.swaps_from_hash(tx_hash) #prende le informazioni relative allo swap, come quantint' di token scambiati, e address del pair
            #nel caso ci siano transazioni con troppi log viene segnalato
            if warning!=None:
                warnings.append(warning)
            #aggiorno con i dati 
            for trade in trades:
                capital.append(capital[-1]+trade["wbnb_val"])
                pair_address=trade["pair"]
                if pair_address not in trades_by_pair:
                    trades_by_pair[pair_address]={"values":[],"blocks":[]}
                trades_by_pair[pair_address]["values"].append(trade["wbnb_val"])
                trades_by_pair[pair_address]["blocks"].append(trade["block"])
    #calcolo il guadagno effettivo effettuato tradando un token e lo aggiungo alla lista gains      
    for pair in trades_by_pair:
        gains.append(gains[-1]+sum(trades_by_pair[pair]["values"]))
    return gains, capital, trades_by_pair

def update_data(pairs,done_wallets,traders):
    with open('data/pairs.json', 'w') as f:
        json.dump(pairs, f)
    with open('data/wallets.json', 'w') as f:
        json.dump(done_wallets, f)
    with open('data/traders.json', 'w') as f:
        json.dump(traders, f)


def swaps_by_pair(pair,period,max_swaps):
    if isinstance(pair,dict):
        pair_address=pair["pair"]
    else:
        pair_address=pair
    cotract=BS.create_contract(pair_address)
    #prendo le prime transazioni per vedere in che blocco è stata fatta la prima transazione sul pair, in modo da incominciare a cercare gli swap da quel blocco
    txs,_=BS.get_tokentxs(pair_address,"asc",0,"latest")
    first_swap_time=int(txs[0]["timeStamp"])
    first_swap_block=int(txs[0]["blockNumber"])
    last_block=int(txs[-1]["blockNumber"])
    #continuo a prendere swap dal primo swap fino a dopo "period" millisecondi
    last_swap_time=first_swap_time

    if isinstance(pair,dict):
        from_block=pair["restart"]
    else:
        from_block=first_swap_block
    all_swaps=[]
    while(last_swap_time<first_swap_time+period and from_block<last_block):
        swap_events = cotract.events.Swap().createFilter(fromBlock=from_block, toBlock=from_block+5000).get_all_entries()
        if swap_events!=[]:
            all_swaps+=swap_events
            last_swap_block=w3.eth.getBlock(swap_events[-1]['blockNumber'])
            last_swap_time=last_swap_block['timestamp']
            from_block=from_block+5000
        #se ho raccolto più di 100 swap esco dal while, perchè ho raccolto abbastanza wallet 
        #(tanto dopo nella funzione rabbit hole aggiungo wallet alla lista new_wallet soltanto se la lista ha meno di 100 elementi)
        if len(all_swaps)>max_swaps:
            break
        time.sleep(1)
    restart=from_block
    if last_swap_time>first_swap_time+period or from_block>last_block:
        restart=None
    return all_swaps,restart

def new_wallets_by_pair(pair,period,max_swaps):
    #raggolgo gli swap di un pair dal momento della creazione fino a "period" minuti dopo fino a quando non raccolgo "max_swaps"
    #nel caso raggiunga "max_swaps" prima di finire il periodo la funzione ritorna "restart" in modo da poter successivamente riprendere dall'ultimo analizzato
    swaps,restart=swaps_by_pair(pair,period*60,max_swaps)
    new_wallets=[]
    for swap in swaps:
        wallet=swap["args"]["to"]
        if wallet not in new_wallets:
            new_wallets.append(wallet)

    return new_wallets,restart
    
def rabbit_hole(start,min_txs,period,start_pair=""):
    #calcolo il numero del blocco di "start" giorni fa
    start=BS.estimate_block_number(start)

    with open('data/pairs.json',"r+") as f:
        pairs=json.load(f)
    with open('data/wallets.json',"r") as f:
        done_wallets=json.load(f)
    with open('data/traders.json',"r") as f:
        traders=json.load(f)
    # se il non ci sono pair salvati, allora crea una lista contenente il pair iniziale in modo che inizi da quello
    if pairs["todo"]==[]:
        pairs["todo"].append(start_pair)
    wallets=[]
    go=True
    found=0
    while go:
        for wallet in wallets:
            if wallet not in done_wallets:
                print("History of:", wallet)
                done_wallets["done"].append(wallet)
                gains,capital,trades_by_pair=get_address_trades(wallet,start,min_txs) #PROVARE A CAMBIARE CON TOKENTX
                if gains!=None:
                    #aggiorno i nuovi pair da anlizzare aggiungendo (se non già presenti) quelli tradati dal wallet analizzato
                    pairs["todo"]+=set(list(trades_by_pair.keys()))-set(pairs["todo"])
                    #calcolo le statistiche con cui valutare la performance dei wallet usando i dati raccolti dalla funzione get_address_trades
                    stats=get_stats(capital,gains,trades_by_pair)
                    traders["data"].append({wallet:stats})
                    #salvo i dati ogni X wallet trovati
                    found+=1
                    if found==1:
                        plt.plot(capital)
                        plt.show()
                        print("Saving data...")
                        found=0
                        update_data(pairs,done_wallets,traders)
        print("Wallets to analy are finished. Finding new ones:")
        #se finiscono i wallet da analizzare allora ne trovo di nuovi
        #prendo a caso un token fra quelli che devo analizzare
        pair_index=random.randint(0,len(pairs["todo"])-1)
        pair=pairs["todo"][pair_index]
        print("     pair:",pair)
        wallets,restart=new_wallets_by_pair(pair,period,300)
        if restart==None:
            pairs["todo"].pop(pair_index)
        else:
            pairs["todo"][pair_index]={"pair":pair,"restart":restart}
            
        print("     got %s new wallets."%(len(wallets)))


rabbit_hole(60,100,60,"0xdde0a4A7c05636228349eECF1F1208eB0c63554C")


#velocizzare non ricreando sempre il contratto pe perndere i dati dello swap
#Aggiungere asse del tempo a capital e gains
#prendere solo wallet che fanno transazioni non troppo a ridosso di quando e' stata aggiunta la liquidita'

#FILTRI WALLET
#considerare solo wallet che comprano qualche X minuti dipo la creazione 

#STATISTICHE WALLET:
#tempo medio entrata dopo aggiunta liquidità token

#STATISTICHE TOKENS:
#quante volte è stata aggiunta la liquidità e di quanto

#MONITORARE CHI CREA SHITCOIN E CAPIRE COME FA A GUADAGNARE
#STATISTICHE SHITCOIN
#filtrare txs live di un wallet https://ethereum.stackexchange.com/questions/93067/python-web3-contract-filtering