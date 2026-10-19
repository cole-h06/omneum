from ..run import print_evaluation
from .workflow import run_enterprise


def main():
    result = run_enterprise()
    print_evaluation(result["sources"], result["evaluation"])


if __name__ == "__main__":
    main()
