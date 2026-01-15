import time
import uuid
import random
from datetime import datetime
import requests
from confluent_kafka import SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import ProtobufSerializer
from schema.DecisionEvent_pb2 import DecisionEvent
from datetime import datetime, timezone
import os
import sys

# config
BOOTSTRAP_SERVERS = "localhost:9093"
SCHEMA_REGISTRY_URL = "http://localhost:8081"
MODEL_URL = "http://localhost:8000/predict"
TOPIC = "raw_decisions"

# proto schema
sr_client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
proto_file = os.path.join(os.path.dirname(__file__), "schema/DecisionEvent.proto")
with open(proto_file) as f:
    proto_content = f.read()

serializer = ProtobufSerializer(DecisionEvent, sr_client)

producer = SerializingProducer({
    "bootstrap.servers": BOOTSTRAP_SERVERS,
    "key.serializer": lambda k, ctx: str(k).encode("utf-8"),
    "value.serializer": serializer
})

RACES = [0, 1, 2, 3, 4 ]
SEXES = [0, 1]

def generate_applicant():
    return {
        "age": random.randint(17, 90),
        "workclass": random.randint(0, 8),
        "fnlwgt": random.randint(12000, 1_500_000),
        "education": random.randint(0, 15),
        "education_num": random.randint(1, 16),
        "marital_status": random.randint(0, 6),
        "occupation": random.randint(0, 14),
        "relationship": random.randint(0, 5),
        "race": random.choice(RACES),
        "sex": random.choice(SEXES),
        "capital_gain": random.randint(0, 99999),
        "capital_loss": random.randint(0, 4356),
        "hours_per_week": random.randint(1, 99),
        "native_country": random.randint(0, 41)
    }

def delivery_report(err, msg):
    if err:
        print(f"Failed: {err}")
    else: print(f"sent: {msg.key()}")

count = 0
start = time.time()
print("Producer starting (Limit: 100 requests)")

try:
    while count < 100:
        applicant = generate_applicant()
        try:
            resp = requests.post(MODEL_URL, json = applicant, timeout = 5)
            if resp.status_code != 200:
                print("API error")
                time.sleep(1)
                continue
            pred = resp.json()
        except Exception as e:
            print(f"connection error : {e}")
            time.sleep(5)
            continue

        event = DecisionEvent()
        event.applicant_id = str(uuid.uuid4())
        event.age = applicant["age"]
        event.race = applicant["race"]
        event.sex = applicant["sex"]
        event.decision = pred["decision"]
        event.approval_probability = pred["approval_probability"]
        event.timestamp_ms = int(datetime.now(timezone.utc).timestamp())

        producer.produce(
            topic=TOPIC,
            key=event.applicant_id,
            value=event,
            on_delivery=delivery_report
        )
        producer.poll(0)
        
        time.sleep(5) 

        count += 1
        if count % 10 == 0: 
            elapsed = time.time() - start
            print(f"{count} messages | {count/elapsed:.0f} msg/sec")
            start = time.time()

except KeyboardInterrupt:
    print("\nStopping producer...")
finally:
    producer.flush()
    print("Producer stopped.")