from uuid import uuid4


def generate_deployment_id() -> str:
    return f"urn:uuid:{uuid4()}"