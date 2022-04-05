from main_baseline import main
from opts import parse_opts, argparse

if __name__ == '__main__':
    args: argparse.ArgumentParser.parse_args = parse_opts()
    print(args.__dict__)