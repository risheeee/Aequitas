from confluent_kafka import DeserializingConsumer
from confluent_kafka.serialization import StringDeserializer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import ProtobufDeserializer

from backend.schema.DecisionEvent_pb2 import DecisionEvent

sr_client = SchemaRegistryClient({'url': 'http://localhost:8081'})

value_deserializer = ProtobufDeserializer(
    DecisionEvent,
    schema_registry_client=sr_client,
    conf={"use.deprecated.format": False},  
)

consumer_conf = {
    'bootstrap.servers': 'localhost:9093',
    'group.id': 'viewer',
    'auto.offset.reset': 'earliest',
    'key.deserializer': StringDeserializer('utf_8'),
    'value.deserializer': value_deserializer,
}

consumer = DeserializingConsumer(consumer_conf)
consumer.subscribe(['raw_decisions'])

print("Last 20 decisions (next 20 from current offset):")
try:
    for _ in range(20):
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"Consumer error: {msg.error()}")
            continue

        event = msg.value()
        if event is None:
            continue

        print(
            f"{event.applicant_id[:8]} "
            f"| race:{event.race} sex:{event.sex} "
            f"→ {'APPROVED' if event.decision else 'DENIED'} "
            f"(p={event.approval_probability:.3f})"
        )
finally:
    consumer.close()