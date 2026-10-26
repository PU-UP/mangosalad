"""Model-facing client: bare status projects; human CLI remains full."""
import sys
from invest_cli import main as client_main


def main():
    original=sys.argv
    args=original[1:]
    if args and args[0]=='status' and '--model-context' not in args and '--report-id' not in args:
        args=[*args,'--model-context']
    sys.argv=[original[0],*args]
    try:
        return client_main()
    finally:
        sys.argv=original


if __name__=='__main__':main()
