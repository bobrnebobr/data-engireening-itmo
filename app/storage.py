from app.settings import S3Settings


def storage_options(settings: S3Settings) -> dict[str, str]:
    return {
        "aws_endpoint": str(settings.s3_endpoint).rstrip("/"),
        "aws_allow_http": str(settings.s3_endpoint.scheme == "http").lower(),
        "aws_access_key_id": settings.s3_access_key,
        "aws_secret_access_key": settings.s3_secret_key.get_secret_value(),
        "aws_region": settings.s3_region,
    }


def validate_run_id(run_id: str) -> None:
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be a nonempty single path component")
