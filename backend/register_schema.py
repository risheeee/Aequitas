from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import ProtobufSerializer
from confluent_kafka.schema_registry.protobuf import ProtobufSchema
import os

SCHEMA_REGISTRY_URL = "http://localhost:8081"
SUBJECT = "raw_decisions-value"

client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})

proto_file = os.path.join(os.path.dirname(__file__), "schema/DecisionEvent.proto")
with open(proto_file) as f:
    proto_content = f.read()

schema = ProtobufSchema(proto_content, "DecisionEvent")

version = client.register_schema(SUBJECT, schema)
print(f"Schema registered successfully. Version: {version}")

