import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from confluent_kafka import Consumer, KafkaError
from supabase import create_client, Client
from schema.DecisionEvent_pb2 import DecisionEvent

load_dotenv()

# setting up supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("Supabase credentials not found :-(")

supabase: Client = create_client(url, key)

# kafka config
conf = {
    'bootstrap.servers': os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
    'group.id': 'supabase-archiver-group-v1',
    'auto.offset.reset': 'eearliest'
}

consumer = Consumer(conf)
topic = os.environ.get("KAFKA_TOPIC")
consumer.subscribe([topic])

print(f"consumer started. listening to '{topic}'")

try:
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"🍒 Error: {msg.error()}")
            break

        # process msg once found
        event = DecisionEvent()
        try:
            event.ParseFromString(msg.value())
            # convert the timestamp for supabase / postgre format
            obj = datetime.fromtimestamp(event.timestamp_ms)
            iso_timestamp = obj.isoformat()

            # preprare paylaod
            row = {
                "applicant_id": event.applicant_id,
                "age": event.age,
                "race": event.race,
                "sex": event.sex,
                "decision": event.decision,
                "probability": event.approval_probability,
                "created_at": iso_timestamp
            }

            # insert into supabase
            response = supabase.table("decisions").insert(row).execute()    # 'decisions' is the table name in sql created on supabase
            print(f"🥵 Saved: {event.applicant_id[:8]}... | Dec: {event.decision} | Prob: {event.approval_probability:.2f}")

        except Exception as e:
            print(f"error processign msg: {e}")

except KeyboardInterrupt:
    print("\n Stopping consumer..")
finally:
    consumer.close()