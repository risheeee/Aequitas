import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from confluent_kafka import DeserializingConsumer, KafkaError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import ProtobufDeserializer
from confluent_kafka.serialization import StringDeserializer
from supabase import create_client, Client
from schema.DecisionEvent_pb2 import DecisionEvent

load_dotenv()

# setting up supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("Supabase credentials not found :-(")
    sys.exit(1)

supabase: Client = create_client(url, key)

# kafka + schema registry config
sr_client = SchemaRegistryClient({"url": os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8081")})
protobuf_deserializer = ProtobufDeserializer(DecisionEvent, {'use.deprecated.format': False})
string_deserializer = StringDeserializer('utf_8')

conf = {
    'bootstrap.servers': os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
    'key.deserializer': string_deserializer,
    'value.deserializer': protobuf_deserializer,
    'group.id': 'supabase-archiver-group-v3', 
    'auto.offset.reset': 'earliest'
}

consumer = DeserializingConsumer(conf)
topic = os.environ.get("KAFKA_TOPIC", "raw_decisions")
consumer.subscribe([topic])

print(f"consumer started. listening to '{topic}'")

try:
    while True:
        msg = consumer.poll(1.0)
        
        if msg is None:
            continue
            
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            print(f"🍒 Error: {msg.error()}")
            continue

        # process msg once found
        event = msg.value()
        
        if event is None:
            continue

        try:
            # Convert protobuf millisecond epoch to ISO8601 UTC for PostgreSQL.
            event_seconds = event.timestamp_ms / 1000
            iso_timestamp = datetime.fromtimestamp(event_seconds, tz=timezone.utc).isoformat()

            existing = (
                supabase
                .table("decisions")
                .select("id")
                .eq("applicant_id", event.applicant_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                print(f"Skipping duplicate applicant_id={event.applicant_id[:8]}...")
                continue

            # preprare payload
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
            supabase.table("decisions").insert(row).execute()        # 'decisions' is the table name in sql created on supabase
            print(f"🥵 Saved: {event.applicant_id[:8]}... | Dec: {event.decision} | Prob: {event.approval_probability:.2f}")

        except Exception as e:
            print(f"🍒 error processign msg: {e}")

except KeyboardInterrupt:
    print("\n Stopping consumer..")
finally:
    consumer.close()