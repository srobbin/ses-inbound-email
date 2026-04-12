import os
import boto3


class SigningSecretNotFoundError(Exception):
    pass


def get_signing_secret(domain: str) -> str:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ssm = boto3.client("ssm", region_name=region)
    param_name = f"/ses-inbound-email/{domain}/signing-secret"

    try:
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    except ssm.exceptions.ParameterNotFound as e:
        raise SigningSecretNotFoundError(
            f"No signing secret in SSM for domain: {domain} (param: {param_name})"
        ) from e

    return response["Parameter"]["Value"]
