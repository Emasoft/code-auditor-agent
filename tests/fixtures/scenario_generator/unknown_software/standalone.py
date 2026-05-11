#!/usr/bin/env python3
# A standalone Python script with no build files, no framework,
# no [project.scripts] entry, no __init__.py package. Type detection
# falls through to unknown_software and the fallback discoverer
# extracts main() + public top-level callables.


def helper():
    return 42


def main():
    print(helper())


if __name__ == "__main__":
    main()
