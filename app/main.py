import argparse
import json
import logging

from app.reader import Reader
from app.settings import get_s3_settings, get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run vacancy MapReduce through Celery")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    from app.orchestrator import Orchestrator

    settings = get_settings()
    s3_settings = get_s3_settings()
    logging.basicConfig(level=settings.log_level)
    orchestrator = Orchestrator(Reader(s3_settings), settings)
    print(json.dumps(orchestrator.run(args.run_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
