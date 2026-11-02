import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payer_service.dlq import main_inspect

if __name__ == "__main__":
    main_inspect()
