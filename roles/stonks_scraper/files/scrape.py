import logging
from time import time
from requests import get
import websocket
from bson import encode, decode
from sqlite3 import connect

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def print_queries(q):
  logger.debug("sql query: %s", q)

sql = connect("/data/stonks.db")
sql.set_trace_callback(print_queries)

DC = "Light"
WORLDS = {}
ITEM_LAST_CHECKED = {}

def setup_sqlite_tables():
  cur = sql.cursor()
  cur.execute("CREATE TABLE IF NOT EXISTS items (item_id INT PRIMARY KEY, item_name TEXT)")
  cur.execute("CREATE TABLE IF NOT EXISTS worlds (world_id INT PRIMARY KEY, world_name TEXT)")
  cur.execute("CREATE TABLE IF NOT EXISTS sales (timestamp INT, world_id INT, item_id INT, price INT, quantity INT, buyer TEXT, PRIMARY KEY (timestamp, item_id, price))")

  sql.commit()

def store_item_name(item_id):
  logger.debug("start store_item_name")
  item_id_int = int(item_id)
  if (item_id_int in ITEM_LAST_CHECKED and ITEM_LAST_CHECKED[item_id_int] < (time() + 30)):
    return
  ITEM_LAST_CHECKED[item_id_int] = time()
  cur = sql.cursor()
  cur.execute("SELECT item_name FROM items WHERE item_id = ?", (item_id_int,))
  res = cur.fetchone()
  if not res:
    xivapi_response = get(f"https://xivapi.com/item/{item_id_int}").json()['Name_en']
    cur.execute("INSERT INTO items (item_id, item_name) VALUES (?, ?)", (item_id_int, xivapi_response))
    sql.commit()

def find_world_in_list(worlds, id):
  for world in worlds:
    if world['id'] == id:
      return world['name']

def get_worlds():
  cur = sql.cursor()

  dc_worlds = []
  dc_list = get("https://universalis.app/api/v2/data-centers").json()

  for dc in dc_list:
    if dc['name'] == DC:
      dc_worlds = dc['worlds']

  if len(dc_worlds) < 1:
    logger.error("No worlds found in DC '%s'", DC)
    exit(1)

  logger.info("Got %i worlds in %s DC", len(dc_worlds), DC)

  world_list = get("https://universalis.app/api/v2/worlds").json()

  worlds = {}

  for world in dc_worlds:
    worlds[world] = find_world_in_list(world_list, world)
    cur.execute("INSERT INTO worlds (world_id, world_name) VALUES (?, ?) ON CONFLICT DO NOTHING", (world, worlds[world]))

  sql.commit()

  return worlds

def process_sale(item_id, world_id, sale):
  timestamp = sale['timestamp']
  price = sale['pricePerUnit']
  quantity = sale['quantity']
  buyer = sale['buyerName']
  logger.debug("process_sale world_id %i item_id %i", world_id, item_id)
  world_name = WORLDS[world_id]
  store_item_name(item_id)

  time_last_week = (time() - (60 * 60 * 24 * 7)) # time - 7 days
  if timestamp < time_last_week:
    logger.debug("item sale timestamp too old: item_id %s timestamp %s", item_id, timestamp)
    return

  logger.info("world id %i world name %s", world_id, world_name)

  cur = sql.cursor()
  cur.execute("""
  INSERT INTO sales (timestamp, world_id, item_id, price, quantity, buyer) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING
  """, (timestamp, world_id, item_id, price, quantity, buyer))
  sql.commit()

def subscribe_to_worlds(ws):
  for world in WORLDS:
    logger.debug("subscribing to %i", world)
    ws.send(encode({
      "event": "subscribe",
      "channel": f"sales/add{{world={world}}}"
    }))

def on_message(ws, message):
  sales = decode(message)
  item_id = sales['item']
  world_id = sales['world']
  for sale in sales['sales']:
    process_sale(item_id, world_id, sale)

def on_error(ws, error):
  logger.error(error)

def start_websocket_connection():
  ws = websocket.WebSocketApp("wss://universalis.app/api/ws",
                              on_open=subscribe_to_worlds,
                              on_message=on_message)
  return ws

if __name__ == '__main__':
  setup_sqlite_tables()

  WORLDS = get_worlds()

  ws = start_websocket_connection()

  ws.run_forever()
