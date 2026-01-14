import os
import json
import time
import redis
from collections import deque
from confluent_kafka import DeserializingConsumer, KafkaError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import ProtobufDeserializer
from confluent_kafka.serialization import StringDeserializer
from schema.DecisionEvent_pb2 import DecisionEvent
from dotenv import load_dotenv

load_dotenv()

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9093")
SCHEMA_REGISTRY_URL = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")
TOPIC = "raw_decisions"
REDIS_HOST = "localhost"
REDIS_PORT = 6379

WINDOW_SIZE = 100 
decision_window = deque(maxlen=WINDOW_SIZE)

try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.ping()
    print("✅ Connected to Redis")
except Exception as e:
    print(f"❌ Redis Connection Failed: {e}")
    exit(1)

sr_client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
protobuf_deserializer = ProtobufDeserializer(DecisionEvent, {'use.deprecated.format': False})

consumer_conf = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'key.deserializer': StringDeserializer('utf_8'),
    'value.deserializer': protobuf_deserializer,
    'group.id': 'bias-detector-v1',
    'auto.offset.reset': 'latest'
}

consumer = DeserializingConsumer(consumer_conf)
consumer.subscribe([TOPIC])

def calculate_metrics():

    if len(decision_window) < 10:
        return None 

    males = [d for d in decision_window if d['sex'] == 1]
    females = [d for d in decision_window if d['sex'] == 0]

    if not males or not females:
        return None

    male_approved = len([m for m in males if m['decision'] == 1])
    female_approved = len([f for f in females if f['decision'] == 1])

    prob_male = male_approved / len(males)
    prob_female = female_approved / len(females)

    if prob_male == 0:
        dir_score = 1.0 
    else:
        dir_score = prob_female / prob_male

    return {
        "total_processed": len(decision_window),
        "male_approval_rate": round(prob_male, 2),
        "female_approval_rate": round(prob_female, 2),
        "dir_score": round(dir_score, 2),
        "status": "BIASED" if dir_score < 0.8 else "FAIR",
        "timestamp": time.time()
    }

print(f"Bias Detector Started... watching {TOPIC}")

try:
    while True:
        msg = consumer.poll(1.0)

        if msg is None:
            continue
        if msg.error():
            continue

        event = msg.value()

        decision_window.append({
            "sex": event.sex,
            "decision": event.decision
        })

        metrics = calculate_metrics()

        if metrics:
            r.set("live_metrics", json.dumps(metrics))
            
            color = "🟢" if metrics["status"] == "FAIR" else "🔴"
            print(f"{color} DIR: {metrics['dir_score']} | Male: {metrics['male_approval_rate']} | Female: {metrics['female_approval_rate']}")

except KeyboardInterrupt:
    print("Stopping...")
finally:
    consumer.close()